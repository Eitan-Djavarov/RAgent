from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app.agent.grounding_guard import GroundingGuard, GroundingResult
from app.agent.query_rewriter import QueryRewriter
from app.agent.response_assembly import (
    format_sql_rows,
    grounding_event_fields,
    merge_tool_responses,
)
from app.agent.router import ExecutionStrategy, classify_intent
from app.agent.sql_tool import ReadOnlyIncidentSqlTool
from app.agent.sse import format_sse
from app.cache.semantic_cache import SemanticCache
from app.cache.session_memory import SessionMemory
from app.models.schemas import (
    QueryRequest,
    QueryResponse,
    SourceCitation,
    SqlQueryResult,
)
from app.rag.pipeline import RagPipeline

logger = logging.getLogger(__name__)


def _sse(payload: dict[str, Any]) -> str:
    return format_sse(payload)


class AgenticOrchestrator:
    """Routes each ask to HYBRID_RAG, SQL_METRICS, or HYBRID_COMBINED tools."""

    def __init__(
        self,
        rag_pipeline: RagPipeline,
        sql_tool: ReadOnlyIncidentSqlTool,
        semantic_cache: SemanticCache | None = None,
        session_memory: SessionMemory | None = None,
        query_rewriter: QueryRewriter | None = None,
        grounding_guard: GroundingGuard | None = None,
    ) -> None:
        self._rag = rag_pipeline
        self._sql = sql_tool
        self._cache = semantic_cache
        self._session_memory = session_memory
        self._rewriter = query_rewriter
        self._grounding = grounding_guard

    async def ask(self, request: QueryRequest) -> QueryResponse:
        original_query = request.query.strip()
        session_id = (request.session_id or "").strip() or None
        rewritten_query, effective = await self._prepare(request, original_query, session_id)

        if self._cache is not None and self._cache.enabled:
            cached = await self._cache.lookup(effective)
            if cached is not None:
                logger.info(
                    "Serving ask from semantic cache (latency_ms=%.2f)",
                    cached.latency_ms,
                )
                response = cached.model_copy(
                    update={
                        "cached": True,
                        "session_id": session_id,
                        "original_query": original_query,
                        "rewritten_query": rewritten_query,
                    }
                )
                await self._persist_turn(
                    session_id=session_id,
                    original_query=original_query,
                    rewritten_query=rewritten_query,
                    response=response,
                )
                return response

        response = await self._execute(effective)
        response = response.model_copy(
            update={
                "cached": False,
                "session_id": session_id,
                "original_query": original_query,
                "rewritten_query": rewritten_query,
            }
        )
        response = await self._apply_grounding(effective.query, response)

        if self._cache is not None and self._cache.enabled:
            await self._cache.store(effective, response)

        await self._persist_turn(
            session_id=session_id,
            original_query=original_query,
            rewritten_query=rewritten_query,
            response=response,
        )
        return response

    async def ask_stream(self, request: QueryRequest) -> AsyncIterator[str]:
        """Yield SSE frames for metadata, tokens, and done events."""
        started = time.perf_counter()
        original_query = request.query.strip()
        session_id = (request.session_id or "").strip() or None
        rewritten_query, effective = await self._prepare(request, original_query, session_id)

        if self._cache is not None and self._cache.enabled:
            cached = await self._cache.lookup(effective)
            if cached is not None:
                response = cached.model_copy(
                    update={
                        "cached": True,
                        "session_id": session_id,
                        "original_query": original_query,
                        "rewritten_query": rewritten_query,
                    }
                )
                async for frame in self._stream_cached_response(
                    response=response,
                    started=started,
                ):
                    yield frame
                asyncio.create_task(
                    self._persist_turn(
                        session_id=session_id,
                        original_query=original_query,
                        rewritten_query=rewritten_query,
                        response=response,
                    )
                )
                return

        strategy = classify_intent(effective.query)
        logger.info(
            "Streaming intent router selected strategy=%s for query=%r",
            strategy.value,
            effective.query,
        )

        sql_result: SqlQueryResult | None = None
        sources: list[SourceCitation] = []
        if strategy in {ExecutionStrategy.SQL_METRICS, ExecutionStrategy.HYBRID_COMBINED}:
            sql_result = await self._run_sql(effective.query)
            if (
                strategy == ExecutionStrategy.SQL_METRICS
                and sql_result is not None
                and not sql_result.query
            ):
                strategy = ExecutionStrategy.HYBRID_RAG

        if strategy in {ExecutionStrategy.HYBRID_RAG, ExecutionStrategy.HYBRID_COMBINED}:
            top_n = min(effective.top_k or 3, 10)
            sources = await self._rag.retrieve(
                effective.query,
                top_n,
                effective.filter_metadata,
            )

        yield _sse(
            {
                "event": "metadata",
                "toolUsed": strategy.value,
                "citations": [citation.model_dump(by_alias=True) for citation in sources],
                "rewrittenQuery": rewritten_query,
                "originalQuery": original_query,
                "sessionId": session_id,
                "cached": False,
                "sqlQueryResult": (
                    sql_result.model_dump(by_alias=True) if sql_result is not None else None
                ),
            }
        )

        answer_parts: list[str] = []
        if strategy == ExecutionStrategy.SQL_METRICS:
            assembled = self._merge(strategy, None, sql_result, 0.0)
            text = assembled.answer
            for chunk in RagPipeline._chunk_text(text, size=28):
                answer_parts.append(chunk)
                yield _sse({"event": "token", "delta": chunk})
                await asyncio.sleep(0)
            full_answer = text
            analysis = assembled.analysis
            summary = assembled.summary
            root_cause = assembled.root_cause
            action_items = assembled.action_items
            citations = assembled.citations or []
            retrieval_mode = "sql-metrics"
        else:
            async for delta in self._rag.stream_synthesis(effective.query, sources):
                answer_parts.append(delta)
                yield _sse({"event": "token", "delta": delta})
            full_answer = "".join(answer_parts)
            if full_answer.strip():
                analysis = self._rag._parse_structured_output(full_answer, sources)
            else:
                analysis = self._rag._heuristic_analysis(effective.query, sources) if sources else None
                full_answer = (
                    self._rag._format_answer(analysis)
                    if analysis is not None
                    else self._rag._empty_answer()
                )
            summary = analysis.executive_summary if analysis else full_answer
            root_cause = (
                analysis.root_cause_analysis
                if analysis
                else "See answer body for root-cause details."
            )
            action_items = (
                analysis.recommended_mitigations
                if analysis
                else "See answer body for recommended actions."
            )
            citations = sources
            retrieval_mode = "hybrid+rerank"
            if sql_result is not None and strategy == ExecutionStrategy.HYBRID_COMBINED:
                summary = f"{summary}\n\nSQL metrics: {sql_result.interpretation}".strip()
                full_answer = (
                    f"{full_answer}\n\n"
                    f"## SQL Metrics\n{sql_result.interpretation}\n"
                    f"Query: `{sql_result.query}`"
                )

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        response = QueryResponse(
            answer=full_answer,
            sources=citations,
            latency_ms=latency_ms,
            analysis=analysis,
            retrieval_mode=retrieval_mode,
            tool_used=strategy.value,
            sql_query_result=sql_result,
            summary=summary,
            root_cause=root_cause,
            action_items=action_items,
            citations=citations,
            cached=False,
            session_id=session_id,
            original_query=original_query,
            rewritten_query=rewritten_query,
        )
        response = await self._apply_grounding(effective.query, response)

        yield _sse(
            {
                "event": "done",
                "latencyMs": latency_ms,
                "summary": summary,
                "rootCause": root_cause,
                "actionItems": action_items,
                "toolUsed": strategy.value,
                "cached": False,
                "sessionId": session_id,
                "originalQuery": original_query,
                "rewrittenQuery": rewritten_query,
                **self._grounding_event_fields(response),
            }
        )

        asyncio.create_task(self._persist_after_stream(effective, response))

    async def _stream_cached_response(
        self,
        *,
        response: QueryResponse,
        started: float,
    ) -> AsyncIterator[str]:
        citations = response.citations or response.sources
        yield _sse(
            {
                "event": "metadata",
                "toolUsed": response.tool_used,
                "citations": [citation.model_dump(by_alias=True) for citation in citations],
                "rewrittenQuery": response.rewritten_query,
                "originalQuery": response.original_query,
                "sessionId": response.session_id,
                "cached": True,
                "sqlQueryResult": (
                    response.sql_query_result.model_dump(by_alias=True)
                    if response.sql_query_result is not None
                    else None
                ),
                **self._grounding_event_fields(response),
            }
        )
        text = response.answer or response.summary or ""
        for chunk in RagPipeline._chunk_text(text, size=32):
            yield _sse({"event": "token", "delta": chunk})
            await asyncio.sleep(0)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        yield _sse(
            {
                "event": "done",
                "latencyMs": latency_ms,
                "summary": response.summary,
                "rootCause": response.root_cause,
                "actionItems": response.action_items,
                "toolUsed": response.tool_used,
                "cached": True,
                "sessionId": response.session_id,
                "originalQuery": response.original_query,
                "rewrittenQuery": response.rewritten_query,
                **self._grounding_event_fields(response),
            }
        )

    async def _persist_after_stream(
        self,
        effective: QueryRequest,
        response: QueryResponse,
    ) -> None:
        try:
            if self._cache is not None and self._cache.enabled:
                await self._cache.store(effective, response)
            await self._persist_turn(
                session_id=response.session_id,
                original_query=response.original_query or effective.query,
                rewritten_query=response.rewritten_query or effective.query,
                response=response,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Background persist after stream failed")

    async def _prepare(
        self,
        request: QueryRequest,
        original_query: str,
        session_id: str | None,
    ) -> tuple[str, QueryRequest]:
        rewritten_query = original_query
        if session_id and self._session_memory is not None and self._rewriter is not None:
            history = await self._session_memory.get_history(session_id)
            if history:
                rewritten_query = await self._rewriter.rewrite(
                    current_query=original_query,
                    history=history,
                )
                logger.info(
                    "Rewrote conversational query session=%s original=%r rewritten=%r",
                    session_id,
                    original_query,
                    rewritten_query,
                )
        effective = request.model_copy(
            update={
                "query": rewritten_query,
                "session_id": session_id,
            }
        )
        return rewritten_query, effective

    async def _run_sql(self, query: str) -> SqlQueryResult:
        try:
            tool_result = await self._sql.run(query)
            return SqlQueryResult(
                query=tool_result.sql,
                row_count=tool_result.row_count,
                columns=tool_result.columns,
                rows=tool_result.rows,
                interpretation=tool_result.interpretation,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQL metrics tool failed: %s", exc)
            return SqlQueryResult(
                query="",
                row_count=0,
                columns=[],
                rows=[],
                interpretation=f"SQL metrics unavailable: {exc}",
            )

    async def _persist_turn(
        self,
        *,
        session_id: str | None,
        original_query: str,
        rewritten_query: str,
        response: QueryResponse,
    ) -> None:
        if not session_id or self._session_memory is None:
            return
        assistant_text = (
            response.summary
            or response.answer
            or response.root_cause
            or ""
        )
        await self._session_memory.append_turn(
            session_id,
            user_query=original_query,
            assistant_response=assistant_text,
            rewritten_query=rewritten_query,
            tool_used=response.tool_used,
        )

    async def _execute(self, request: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        strategy = classify_intent(request.query)
        logger.info("Intent router selected strategy=%s for query=%r", strategy.value, request.query)

        sql_result: SqlQueryResult | None = None
        rag_response: QueryResponse | None = None

        if strategy in {ExecutionStrategy.SQL_METRICS, ExecutionStrategy.HYBRID_COMBINED}:
            sql_result = await self._run_sql(request.query)
            if strategy == ExecutionStrategy.SQL_METRICS and not sql_result.query:
                strategy = ExecutionStrategy.HYBRID_RAG

        if strategy in {ExecutionStrategy.HYBRID_RAG, ExecutionStrategy.HYBRID_COMBINED}:
            rag_response = await self._rag.query(request)

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return self._merge(strategy, rag_response, sql_result, latency_ms)

    async def _apply_grounding(self, query: str, response: QueryResponse) -> QueryResponse:
        if self._grounding is None:
            return response
        if response.tool_used == ExecutionStrategy.SQL_METRICS.value:
            return response.model_copy(
                update={
                    "faithfulness_score": None,
                    "is_grounded": None,
                    "unsupported_claims": None,
                }
            )

        sources = response.citations or response.sources or []
        try:
            result = await self._grounding.evaluate(
                query=query,
                answer=response.answer or response.summary or "",
                sources=list(sources),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Grounding evaluation failed: %s", exc)
            result = GroundingResult(
                faithfulness_score=0.0,
                is_grounded=False,
                unsupported_claims=["Grounding evaluation unavailable."],
                supported_claims=[],
                evaluation_mode="error",
            )

        return response.model_copy(
            update={
                "faithfulness_score": result.faithfulness_score,
                "is_grounded": result.is_grounded,
                "unsupported_claims": result.unsupported_claims,
            }
        )

    @staticmethod
    def _grounding_event_fields(response: QueryResponse) -> dict[str, Any]:
        return grounding_event_fields(response)

    def _merge(
        self,
        strategy: ExecutionStrategy,
        rag_response: QueryResponse | None,
        sql_result: SqlQueryResult | None,
        latency_ms: float,
    ) -> QueryResponse:
        return merge_tool_responses(strategy, rag_response, sql_result, latency_ms)

    @staticmethod
    def _format_rows(rows: list[dict[str, Any]]) -> str:
        return format_sql_rows(rows)
