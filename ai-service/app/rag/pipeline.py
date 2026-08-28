from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any

import httpx
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import Settings, get_settings
from app.models.schemas import (
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    SourceCitation,
    StructuredIncidentAnalysis,
)
from app.rag.bm25_store import Bm25Store
from app.rag.reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)

STRUCTURED_SYSTEM_PROMPT = """You are a senior aerospace/defense systems incident analyst for Tech-Doc-Intelligence.
Use ONLY the retrieved technical report passages. Do not invent facts.

Return your analysis in EXACTLY this Markdown structure:

## Executive Summary
<2-4 sentences summarizing the incident pattern and operational impact>

## Root Cause Analysis
<root causes strictly grounded in the retrieved reports; cite document ids inline>

## Recommended Mitigation / Corrective Actions
<numbered, actionable mitigations drawn from the reports>

## Source Citations
- document_id=<id>; confidence=<0-1>; excerpt=<short quote>
(repeat for each used source)
"""


class RagPipeline:
    """Hybrid dense+BM25 retrieval with CrossEncoder re-ranking and structured analysis."""

    def __init__(
        self,
        settings: Settings,
        embeddings: HuggingFaceEmbeddings,
        qdrant: QdrantClient,
        bm25_store: Bm25Store | None = None,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._qdrant = qdrant
        self._bm25 = bm25_store or Bm25Store()
        self._reranker = reranker or CrossEncoderReranker(settings.cross_encoder_model)
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        self._ensure_collection()

    def embed_query(self, text: str) -> list[float]:
        return list(self._embeddings.embed_query(text))

    def _ensure_collection(self) -> None:
        collection = self._settings.collection_name
        existing = {c.name for c in self._qdrant.get_collections().collections}
        if collection in existing:
            return

        logger.info(
            "Creating Qdrant collection %s (dim=%s)",
            collection,
            self._settings.embedding_dimension,
        )
        self._qdrant.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(
                size=self._settings.embedding_dimension,
                distance=qmodels.Distance.COSINE,
            ),
        )
        self._qdrant.create_payload_index(
            collection_name=collection,
            field_name="document_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )

    def is_ready(self) -> tuple[bool, str]:
        try:
            names = {c.name for c in self._qdrant.get_collections().collections}
            if self._settings.collection_name in names:
                return True, "ok"
            return False, "collection_missing"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    async def ingest(self, request: IngestRequest) -> IngestResponse:
        return await asyncio.to_thread(self._ingest_sync, request)

    def _ingest_sync(self, request: IngestRequest) -> IngestResponse:
        chunks = self._splitter.split_text(request.content)
        if not chunks:
            return IngestResponse(
                success=False,
                document_id=request.document_id,
                chunks_count=0,
                message="No indexable chunks were produced from the document content.",
            )

        self._delete_existing_document(request.document_id)
        self._bm25.remove_document(request.document_id)

        vectors = self._embeddings.embed_documents(chunks)
        points: list[qmodels.PointStruct] = []
        point_ids: list[str] = []
        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            point_id = str(uuid.uuid4())
            point_ids.append(point_id)
            payload: dict[str, Any] = {
                "document_id": request.document_id,
                "title": request.title,
                "chunk_index": index,
                "chunk_text": chunk,
                "metadata": request.metadata,
            }
            for key, value in request.metadata.items():
                if isinstance(value, (str, int, float, bool)):
                    payload[f"meta_{key}"] = value

            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        self._qdrant.upsert(
            collection_name=self._settings.collection_name,
            points=points,
            wait=True,
        )
        self._bm25.add_chunks(
            document_id=request.document_id,
            title=request.title,
            point_ids=point_ids,
            chunk_texts=chunks,
        )
        logger.info(
            "Ingested document %s (%s chunks)",
            request.document_id,
            len(points),
        )
        return IngestResponse(
            success=True,
            document_id=request.document_id,
            chunks_count=len(points),
            message=(
                f"Indexed {len(points)} chunks into collection "
                f"'{self._settings.collection_name}' (dense + BM25)."
            ),
        )

    async def query(self, request: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        top_n = min(request.top_k or self._settings.rerank_top_n, self._settings.rerank_top_n)

        sources = await self.retrieve(request.query, top_n, request.filter_metadata)
        analysis = await self._generate_structured_analysis(
            query=request.query,
            sources=sources,
            structured=request.structured,
        )
        answer = self._format_answer(analysis) if analysis else self._empty_answer()
        latency_ms = (time.perf_counter() - started) * 1000.0
        return QueryResponse(
            answer=answer,
            sources=sources,
            latency_ms=round(latency_ms, 2),
            analysis=analysis if request.structured else None,
            retrieval_mode="hybrid+rerank" if self._settings.enable_rerank else "hybrid",
        )

    async def retrieve(
        self,
        query: str,
        top_n: int,
        filter_metadata: dict[str, Any] | None,
    ) -> list[SourceCitation]:
        return await asyncio.to_thread(
            self._hybrid_retrieve_and_rerank,
            query,
            top_n,
            filter_metadata,
        )

    async def stream_synthesis(
        self,
        query: str,
        sources: list[SourceCitation],
    ) -> Any:
        """Yield token deltas while synthesizing structured analysis Markdown."""
        if not sources:
            text = self._empty_answer()
            for chunk in self._chunk_text(text, size=24):
                yield chunk
            return

        context = self._build_context(sources)
        user_prompt = (
            f"Analyst question:\n{query}\n\n"
            f"Retrieved technical report passages:\n{context}\n\n"
            "Produce the structured incident analysis now."
        )

        if self._settings.openai_api_key:
            emitted = False
            try:
                async for delta in self._stream_openai(user_prompt):
                    emitted = True
                    yield delta
                if emitted:
                    return
            except Exception as exc:  # noqa: BLE001
                if emitted:
                    return
                logger.warning("OpenAI stream failed, trying Ollama: %s", exc)

        emitted = False
        try:
            async for delta in self._stream_ollama(user_prompt):
                emitted = True
                yield delta
            if emitted:
                return
        except Exception as exc:  # noqa: BLE001
            if emitted:
                return
            logger.warning("Ollama stream failed, using heuristic: %s", exc)

        heuristic = self._heuristic_analysis(query, sources)
        text = self._format_answer(heuristic)
        for chunk in self._chunk_text(text, size=24):
            yield chunk

    async def _stream_openai(self, user_prompt: str) -> Any:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        stream = await client.chat.completions.create(
            model=self._settings.openai_model,
            messages=[
                {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            stream=True,
        )
        async for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta.content
            if delta:
                yield delta

    async def _stream_ollama(self, user_prompt: str) -> Any:
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._settings.ollama_model,
            "stream": True,
            "messages": [
                {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = data.get("message") or {}
                    delta = message.get("content")
                    if isinstance(delta, str) and delta:
                        yield delta
                    if data.get("done") is True:
                        break

    @staticmethod
    def _chunk_text(text: str, size: int = 24) -> list[str]:
        if not text:
            return []
        return [text[index : index + size] for index in range(0, len(text), size)]

    def _delete_existing_document(self, document_id: str) -> None:
        self._qdrant.delete(
            collection_name=self._settings.collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )

    def _build_metadata_filter(
        self,
        filter_metadata: dict[str, Any] | None,
    ) -> qmodels.Filter | None:
        if not filter_metadata:
            return None

        conditions: list[qmodels.FieldCondition] = []
        for key, value in filter_metadata.items():
            if isinstance(value, (str, int, float, bool)):
                conditions.append(
                    qmodels.FieldCondition(
                        key=f"meta_{key}",
                        match=qmodels.MatchValue(value=value),
                    )
                )
        if not conditions:
            return None
        return qmodels.Filter(must=conditions)

    def _hybrid_retrieve_and_rerank(
        self,
        query: str,
        top_n: int,
        filter_metadata: dict[str, Any] | None,
    ) -> list[SourceCitation]:
        fused = self._hybrid_fuse(query, filter_metadata)
        if not fused:
            return []

        candidate_n = min(self._settings.rerank_candidates, len(fused))
        candidates = fused[:candidate_n]

        if self._settings.enable_rerank and len(candidates) > 1:
            try:
                reranked = self._reranker.rerank(
                    query=query,
                    candidates=[
                        (item.document_id, item.chunk_text, item.score) for item in candidates
                    ],
                    top_n=top_n,
                )
                return [
                    SourceCitation(
                        document_id=document_id,
                        chunk_text=chunk_text,
                        score=round(self._sigmoid(score), 6),
                    )
                    for document_id, chunk_text, score in reranked
                ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("CrossEncoder rerank failed; using hybrid fusion ranking: %s", exc)

        return candidates[:top_n]

    def _hybrid_fuse(
        self,
        query: str,
        filter_metadata: dict[str, Any] | None,
    ) -> list[SourceCitation]:
        query_vector = self._embeddings.embed_query(query)
        query_filter = self._build_metadata_filter(filter_metadata)

        dense_hits = self._qdrant.search(
            collection_name=self._settings.collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=self._settings.hybrid_dense_top_k,
            with_payload=True,
        )

        dense_scores: dict[str, tuple[str, str, float]] = {}
        for hit in dense_hits:
            payload: dict[str, Any] = hit.payload or {}
            chunk_text = str(payload.get("chunk_text", ""))
            document_id = str(payload.get("document_id", "unknown"))
            if not chunk_text:
                continue
            key = f"{document_id}::{hash(chunk_text)}"
            dense_scores[key] = (document_id, chunk_text, float(hit.score))

        bm25_hits = self._bm25.search(query, top_k=self._settings.hybrid_bm25_top_k)
        bm25_scores: dict[str, tuple[str, str, float]] = {}
        for doc, score in bm25_hits:
            if filter_metadata:
                # BM25 store has no metadata filter; skip if dense path used filters and
                # this chunk never appeared in dense results under that filter.
                key = f"{doc.document_id}::{hash(doc.chunk_text)}"
                if key not in dense_scores and query_filter is not None:
                    # Allow BM25-only hits when no dense hit, but apply cheap metadata gate
                    # by requiring type/system tags to appear in text when filtered.
                    if not self._passes_text_metadata_gate(doc.chunk_text, filter_metadata):
                        continue
            key = f"{doc.document_id}::{hash(doc.chunk_text)}"
            bm25_scores[key] = (doc.document_id, doc.chunk_text, float(score))

        all_keys = set(dense_scores) | set(bm25_scores)
        fused: list[SourceCitation] = []
        dense_w = self._settings.hybrid_dense_weight
        bm25_w = self._settings.hybrid_bm25_weight
        weight_sum = dense_w + bm25_w
        if weight_sum <= 0:
            dense_w, bm25_w, weight_sum = 0.6, 0.4, 1.0

        for key in all_keys:
            document_id = ""
            chunk_text = ""
            dense = 0.0
            sparse = 0.0
            if key in dense_scores:
                document_id, chunk_text, dense = dense_scores[key]
            if key in bm25_scores:
                document_id, chunk_text, sparse = bm25_scores[key]
            hybrid = ((dense_w * dense) + (bm25_w * sparse)) / weight_sum
            fused.append(
                SourceCitation(
                    document_id=document_id,
                    chunk_text=chunk_text,
                    score=round(hybrid, 6),
                )
            )

        fused.sort(key=lambda item: item.score, reverse=True)
        return fused

    @staticmethod
    def _passes_text_metadata_gate(chunk_text: str, filter_metadata: dict[str, Any]) -> bool:
        lowered = chunk_text.lower()
        for value in filter_metadata.values():
            if isinstance(value, str) and value.lower() not in lowered:
                # soft gate: if any string filter value is absent, still allow when
                # the filter is the generic type=incident marker only.
                if value.lower() not in {"incident"}:
                    return False
        return True

    @staticmethod
    def _sigmoid(value: float) -> float:
        # Numerically stable-ish mapping of CrossEncoder logits to 0..1 confidence.
        if value >= 0:
            z = pow(2.718281828, -value)
            return 1.0 / (1.0 + z)
        z = pow(2.718281828, value)
        return z / (1.0 + z)

    async def _generate_structured_analysis(
        self,
        query: str,
        sources: list[SourceCitation],
        structured: bool,
    ) -> StructuredIncidentAnalysis | None:
        if not sources:
            return None

        context = self._build_context(sources)
        user_prompt = (
            f"Analyst question:\n{query}\n\n"
            f"Retrieved technical report passages:\n{context}\n\n"
            "Produce the structured incident analysis now."
        )

        raw: str | None = None
        if self._settings.openai_api_key:
            try:
                raw = await self._answer_with_openai(user_prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenAI structured analysis failed, trying Ollama: %s", exc)

        if raw is None:
            try:
                raw = await self._answer_with_ollama(user_prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ollama structured analysis failed, using heuristic: %s", exc)
                return self._heuristic_analysis(query, sources)

        analysis = self._parse_structured_output(raw, sources)
        if not structured:
            return analysis
        return analysis

    async def _answer_with_openai(self, user_prompt: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        completion = await client.chat.completions.create(
            model=self._settings.openai_model,
            messages=[
                {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        message = completion.choices[0].message.content
        if not message:
            raise RuntimeError("OpenAI returned an empty completion.")
        return message.strip()

    async def _answer_with_ollama(self, user_prompt: str) -> str:
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}).get("content")
        if not isinstance(message, str) or not message.strip():
            raise RuntimeError("Ollama returned an empty completion.")
        return message.strip()

    def _heuristic_analysis(
        self,
        query: str,
        sources: list[SourceCitation],
    ) -> StructuredIncidentAnalysis:
        joined = "\n".join(source.chunk_text for source in sources)
        root = self._extract_section(
            joined,
            markers=("root cause", "causal", "caused by", "primary causal"),
            fallback=sources[0].chunk_text[:500],
        )
        mitigation = self._extract_section(
            joined,
            markers=("mitigation", "corrective", "workaround", "recommended"),
            fallback="Review the cited reports and apply the listed field mitigations.",
        )
        summary = (
            f"Based on {len(sources)} re-ranked technical passages related to '{query}', "
            f"the strongest evidence points to issues described in document "
            f"{sources[0].document_id} (confidence {sources[0].score:.2f})."
        )
        return StructuredIncidentAnalysis(
            executive_summary=summary,
            root_cause_analysis=root,
            recommended_mitigations=mitigation,
            source_citations=sources,
        )

    @staticmethod
    def _extract_section(text: str, markers: tuple[str, ...], fallback: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        matched = [
            sentence.strip()
            for sentence in sentences
            if any(marker in sentence.lower() for marker in markers)
        ]
        if matched:
            return " ".join(matched[:4])
        return fallback

    def _parse_structured_output(
        self,
        raw: str,
        sources: list[SourceCitation],
    ) -> StructuredIncidentAnalysis:
        executive = self._section_between(raw, "Executive Summary", "Root Cause Analysis")
        root = self._section_between(raw, "Root Cause Analysis", "Recommended Mitigation")
        if not root:
            root = self._section_between(
                raw,
                "Root Cause Analysis",
                "Recommended Mitigation / Corrective Actions",
            )
        mitigation = self._section_between(
            raw,
            "Recommended Mitigation / Corrective Actions",
            "Source Citations",
        )
        if not mitigation:
            mitigation = self._section_between(raw, "Recommended Mitigation", "Source Citations")

        return StructuredIncidentAnalysis(
            executive_summary=executive or raw[:400],
            root_cause_analysis=root or "Insufficient grounded root-cause detail in model output.",
            recommended_mitigations=mitigation
            or "See source citations for reported mitigations.",
            source_citations=sources,
        )

    @staticmethod
    def _section_between(text: str, start: str, end: str) -> str:
        pattern = rf"##\s*{re.escape(start)}\s*(.*?)(?=##\s*{re.escape(end)}|$)"
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return match.group(1).strip()

    @staticmethod
    def _build_context(sources: list[SourceCitation]) -> str:
        return "\n\n".join(
            f"[{index + 1}] document_id={source.document_id} confidence={source.score:.4f}\n"
            f"{source.chunk_text}"
            for index, source in enumerate(sources)
        )

    @staticmethod
    def _format_answer(analysis: StructuredIncidentAnalysis) -> str:
        citations = "\n".join(
            f"- document_id={c.document_id}; confidence={c.score:.4f}; "
            f"excerpt={c.chunk_text[:180].replace(chr(10), ' ')}"
            for c in analysis.source_citations
        )
        return (
            "## Executive Summary\n"
            f"{analysis.executive_summary}\n\n"
            "## Root Cause Analysis\n"
            f"{analysis.root_cause_analysis}\n\n"
            "## Recommended Mitigation / Corrective Actions\n"
            f"{analysis.recommended_mitigations}\n\n"
            "## Source Citations\n"
            f"{citations}"
        )

    @staticmethod
    def _empty_answer() -> str:
        return (
            "## Executive Summary\n"
            "No relevant indexed technical reports were retrieved for this query.\n\n"
            "## Root Cause Analysis\n"
            "Insufficient evidence.\n\n"
            "## Recommended Mitigation / Corrective Actions\n"
            "Ingest incident reports, then re-run the analysis.\n\n"
            "## Source Citations\n"
            "- none"
        )


def build_embeddings(settings: Settings) -> HuggingFaceEmbeddings:
    model_name = settings.embedding_model
    if "/" not in model_name:
        model_name = f"sentence-transformers/{model_name}"

    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def build_qdrant_client(settings: Settings) -> QdrantClient:
    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key,
        prefer_grpc=False,
        timeout=30,
    )


def get_rag_pipeline() -> RagPipeline:
    settings = get_settings()
    return RagPipeline(
        settings=settings,
        embeddings=build_embeddings(settings),
        qdrant=build_qdrant_client(settings),
        bm25_store=Bm25Store(),
        reranker=CrossEncoderReranker(settings.cross_encoder_model),
    )
