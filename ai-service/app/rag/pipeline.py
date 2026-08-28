from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient

from app.core.config import Settings, get_settings
from app.ingestion.hierarchical_chunker import HierarchicalChunker
from app.ingestion.qdrant_indexer import QdrantIndexer
from app.models.schemas import (
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    SourceCitation,
    StructuredIncidentAnalysis,
)
from app.prompts.synthesis import build_synthesis_user_prompt
from app.rag.bm25_store import Bm25Store
from app.rag.llm_synthesis import (
    build_context,
    chunk_text,
    complete_ollama,
    complete_openai,
    empty_answer,
    format_answer,
    heuristic_analysis,
    parse_structured_output,
    stream_ollama,
    stream_openai,
)
from app.rag.reranker import CrossEncoderReranker
from app.retrieval.hybrid_search import HybridSearcher
from app.retrieval.parent_expansion import LOW_RELEVANCE_MESSAGE

logger = logging.getLogger(__name__)


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
        self._chunker = HierarchicalChunker(
            parent_chunk_size=settings.parent_chunk_size,
            parent_chunk_overlap=settings.parent_chunk_overlap,
            child_chunk_size=settings.child_chunk_size,
            child_chunk_overlap=settings.child_chunk_overlap,
        )
        self._indexer = QdrantIndexer(
            settings=settings,
            embeddings=embeddings,
            qdrant=qdrant,
            bm25_store=self._bm25,
            chunker=self._chunker,
        )
        self._searcher = HybridSearcher(
            settings=settings,
            embeddings=embeddings,
            qdrant=qdrant,
            bm25_store=self._bm25,
            reranker=self._reranker,
        )
        self._ensure_collection()

    def embed_query(self, text: str) -> list[float]:
        return list(self._embeddings.embed_query(text))

    def _ensure_collection(self) -> None:
        self._indexer.ensure_collection()

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
        return self._indexer.ingest(request)

    async def query(self, request: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        top_n = min(request.top_k or self._settings.rerank_top_n, self._settings.rerank_top_n)

        sources = await self.retrieve(request.query, top_n, request.filter_metadata)
        if not sources:
            latency_ms = (time.perf_counter() - started) * 1000.0
            return QueryResponse(
                answer=self._empty_answer(),
                sources=[],
                latency_ms=round(latency_ms, 2),
                analysis=None,
                retrieval_mode=(
                    "hybrid+rerank+parent" if self._settings.enable_rerank else "hybrid+parent"
                ),
                summary=LOW_RELEVANCE_MESSAGE,
                root_cause=(
                    "Insufficient grounded evidence above the minimum retrieval score threshold."
                ),
                action_items=(
                    "Refine the query, lower filters, or ingest additional incident reports, "
                    "then retry."
                ),
                citations=[],
            )

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
            retrieval_mode=(
                "hybrid+rerank+parent" if self._settings.enable_rerank else "hybrid+parent"
            ),
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

    def _hybrid_retrieve_and_rerank(
        self,
        query: str,
        top_n: int,
        filter_metadata: dict[str, Any] | None,
    ) -> list[SourceCitation]:
        return self._searcher.search(query, top_n, filter_metadata)

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
        user_prompt = build_synthesis_user_prompt(query=query, context=context)

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
        async for delta in stream_openai(self._settings, user_prompt):
            yield delta

    async def _stream_ollama(self, user_prompt: str) -> Any:
        async for delta in stream_ollama(self._settings, user_prompt):
            yield delta

    @staticmethod
    def _chunk_text(text: str, size: int = 24) -> list[str]:
        return chunk_text(text, size)

    def _delete_existing_document(self, document_id: str) -> None:
        self._indexer.delete_vectors(document_id)

    def delete_document(self, document_id: str) -> int:
        """Delete all Qdrant points and BM25 entries for a document. Returns vector count removed."""
        return self._indexer.delete_document(document_id)

    def count_document_chunks(self, document_id: str) -> int:
        return self._indexer.count_document_chunks(document_id)

    def count_chunks_by_document(self) -> dict[str, int]:
        return self._indexer.count_chunks_by_document()

    async def _generate_structured_analysis(
        self,
        query: str,
        sources: list[SourceCitation],
        structured: bool,
    ) -> StructuredIncidentAnalysis | None:
        if not sources:
            return None

        context = self._build_context(sources)
        user_prompt = build_synthesis_user_prompt(query=query, context=context)

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
        return await complete_openai(self._settings, user_prompt)

    async def _answer_with_ollama(self, user_prompt: str) -> str:
        return await complete_ollama(self._settings, user_prompt)

    def _heuristic_analysis(
        self,
        query: str,
        sources: list[SourceCitation],
    ) -> StructuredIncidentAnalysis:
        return heuristic_analysis(query, sources)

    def _parse_structured_output(
        self,
        raw: str,
        sources: list[SourceCitation],
    ) -> StructuredIncidentAnalysis:
        return parse_structured_output(raw, sources)

    @staticmethod
    def _build_context(sources: list[SourceCitation]) -> str:
        return build_context(sources)

    @staticmethod
    def _format_answer(analysis: StructuredIncidentAnalysis) -> str:
        return format_answer(analysis)

    @staticmethod
    def _empty_answer() -> str:
        return empty_answer()


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
