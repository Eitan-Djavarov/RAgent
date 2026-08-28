from __future__ import annotations

from typing import Any

from app.agent.router import ExecutionStrategy
from app.models.schemas import QueryResponse, SourceCitation, SqlQueryResult, StructuredIncidentAnalysis


def merge_tool_responses(
    strategy: ExecutionStrategy,
    rag_response: QueryResponse | None,
    sql_result: SqlQueryResult | None,
    latency_ms: float,
) -> QueryResponse:
    if rag_response is not None and strategy != ExecutionStrategy.SQL_METRICS:
        analysis = rag_response.analysis
        summary = analysis.executive_summary if analysis else rag_response.answer
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
        citations = rag_response.sources

        if sql_result is not None and strategy == ExecutionStrategy.HYBRID_COMBINED:
            summary = (
                f"{summary}\n\nSQL metrics: {sql_result.interpretation}"
            ).strip()
            answer = (
                f"{rag_response.answer}\n\n"
                f"## SQL Metrics\n{sql_result.interpretation}\n"
                f"Query: `{sql_result.query}`"
            )
        else:
            answer = rag_response.answer

        return QueryResponse(
            answer=answer,
            sources=citations,
            latency_ms=latency_ms,
            analysis=analysis,
            retrieval_mode=rag_response.retrieval_mode,
            tool_used=strategy.value,
            sql_query_result=sql_result,
            summary=summary,
            root_cause=root_cause,
            action_items=action_items,
            citations=citations,
            cached=False,
        )

    interpretation = (
        sql_result.interpretation
        if sql_result is not None
        else "No SQL metrics were produced."
    )
    rows_preview = format_sql_rows(sql_result.rows if sql_result else [])
    summary = interpretation
    root_cause = (
        "Not applicable for pure metrics queries. "
        "Use an analytical question to retrieve root-cause evidence from reports."
    )
    action_items = (
        "Review the SQL metrics result set and open matching incident reports for deeper analysis."
    )
    answer = (
        "## Executive Summary\n"
        f"{summary}\n\n"
        "## Root Cause Analysis\n"
        f"{root_cause}\n\n"
        "## Recommended Mitigation / Corrective Actions\n"
        f"{action_items}\n\n"
        "## SQL Metrics\n"
        f"{rows_preview}"
    )
    empty_citations: list[SourceCitation] = []
    analysis = StructuredIncidentAnalysis(
        executive_summary=summary,
        root_cause_analysis=root_cause,
        recommended_mitigations=action_items,
        source_citations=empty_citations,
    )
    return QueryResponse(
        answer=answer,
        sources=empty_citations,
        latency_ms=latency_ms,
        analysis=analysis,
        retrieval_mode="sql-metrics",
        tool_used=ExecutionStrategy.SQL_METRICS.value,
        sql_query_result=sql_result,
        summary=summary,
        root_cause=root_cause,
        action_items=action_items,
        citations=empty_citations,
        cached=False,
    )


def format_sql_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No rows returned._"
    lines: list[str] = []
    for index, row in enumerate(rows[:20], start=1):
        rendered = ", ".join(f"{key}={value}" for key, value in row.items())
        lines.append(f"{index}. {rendered}")
    if len(rows) > 20:
        lines.append(f"... ({len(rows) - 20} more rows)")
    return "\n".join(lines)


def grounding_event_fields(response: QueryResponse) -> dict[str, Any]:
    return {
        "faithfulnessScore": response.faithfulness_score,
        "isGrounded": response.is_grounded,
        "unsupportedClaims": response.unsupported_claims or [],
    }
