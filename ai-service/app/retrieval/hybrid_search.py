from __future__ import annotations

import logging
from typing import Any

from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.citations.indexing import index_citations
from app.core.config import Settings
from app.models.schemas import SourceCitation
from app.rag.bm25_store import Bm25Store
from app.rag.reranker import CrossEncoderReranker
from app.retrieval.parent_expansion import (
    RetrievalHit,
    expand_and_dedupe_parents,
    filter_by_min_score,
    meets_min_score_threshold,
)

logger = logging.getLogger(__name__)


class HybridSearcher:
    """Dense + BM25 fusion, optional rerank, parent expansion, min-score gate."""

    def __init__(
        self,
        settings: Settings,
        embeddings: HuggingFaceEmbeddings,
        qdrant: QdrantClient,
        bm25_store: Bm25Store,
        reranker: CrossEncoderReranker,
    ) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._qdrant = qdrant
        self._bm25 = bm25_store
        self._reranker = reranker

    def search(
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
        ranked_hits = candidates

        if self._settings.enable_rerank and len(candidates) > 1:
            try:
                reranked = self._reranker.rerank(
                    query=query,
                    candidates=[
                        (item.document_id, item.chunk_text, item.score) for item in candidates
                    ],
                    top_n=max(top_n * 3, top_n),
                )
                by_key = {(item.document_id, item.chunk_text): item for item in candidates}
                rebuilt: list[RetrievalHit] = []
                for document_id, chunk_text, score in reranked:
                    prior = by_key.get((document_id, chunk_text))
                    rebuilt.append(
                        RetrievalHit(
                            document_id=document_id,
                            chunk_text=chunk_text,
                            score=round(self._sigmoid(score), 6),
                            parent_id=prior.parent_id if prior else None,
                            parent_text=prior.parent_text if prior else None,
                            system=prior.system if prior else None,
                            severity=prior.severity if prior else None,
                        )
                    )
                ranked_hits = rebuilt
            except Exception as exc:  # noqa: BLE001
                logger.warning("CrossEncoder rerank failed; using hybrid fusion ranking: %s", exc)

        provisional = [
            SourceCitation(
                document_id=hit.document_id,
                chunk_text=hit.chunk_text,
                score=hit.score,
                parent_id=hit.parent_id,
            )
            for hit in ranked_hits
        ]
        if not meets_min_score_threshold(
            provisional,
            min_score=self._settings.min_retrieval_score,
        ):
            logger.info(
                "All retrieval hits below min_retrieval_score=%.2f; short-circuiting synthesis",
                self._settings.min_retrieval_score,
            )
            return []

        above_floor = [
            hit
            for hit in ranked_hits
            if self._settings.min_retrieval_score <= 0
            or hit.score >= self._settings.min_retrieval_score
        ]
        expanded = expand_and_dedupe_parents(above_floor, top_n=top_n)
        filtered = filter_by_min_score(expanded, min_score=self._settings.min_retrieval_score)
        return index_citations(filtered)

    def _hybrid_fuse(
        self,
        query: str,
        filter_metadata: dict[str, Any] | None,
    ) -> list[RetrievalHit]:
        query_vector = self._embeddings.embed_query(query)
        query_filter = self._build_metadata_filter(filter_metadata)

        dense_hits = self._qdrant.search(
            collection_name=self._settings.collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=self._settings.hybrid_dense_top_k,
            with_payload=True,
        )

        dense_scores: dict[str, RetrievalHit] = {}
        for hit in dense_hits:
            payload: dict[str, Any] = hit.payload or {}
            chunk_text = str(payload.get("chunk_text", ""))
            document_id = str(payload.get("document_id", "unknown"))
            if not chunk_text:
                continue
            parent_id = payload.get("parent_id")
            parent_text = payload.get("parent_text")
            system, severity = extract_system_severity(payload)
            key = f"{document_id}::{hash(chunk_text)}"
            dense_scores[key] = RetrievalHit(
                document_id=document_id,
                chunk_text=chunk_text,
                score=float(hit.score),
                parent_id=str(parent_id) if parent_id else None,
                parent_text=str(parent_text) if parent_text else None,
                system=system,
                severity=severity,
            )

        bm25_hits = self._bm25.search(query, top_k=self._settings.hybrid_bm25_top_k)
        bm25_scores: dict[str, RetrievalHit] = {}
        for doc, score in bm25_hits:
            key = f"{doc.document_id}::{hash(doc.chunk_text)}"
            if filter_metadata:
                if key not in dense_scores and query_filter is not None:
                    if not passes_text_metadata_gate(doc.chunk_text, filter_metadata):
                        continue
            bm25_scores[key] = RetrievalHit(
                document_id=doc.document_id,
                chunk_text=doc.chunk_text,
                score=float(score),
                parent_id=doc.parent_id,
                parent_text=doc.parent_text,
            )

        all_keys = set(dense_scores) | set(bm25_scores)
        fused: list[RetrievalHit] = []
        dense_w = self._settings.hybrid_dense_weight
        bm25_w = self._settings.hybrid_bm25_weight
        weight_sum = dense_w + bm25_w
        if weight_sum <= 0:
            dense_w, bm25_w, weight_sum = 0.6, 0.4, 1.0

        for key in all_keys:
            dense_hit = dense_scores.get(key)
            sparse_hit = bm25_scores.get(key)
            document_id = (
                dense_hit.document_id
                if dense_hit is not None
                else (sparse_hit.document_id if sparse_hit is not None else "unknown")
            )
            chunk_text = (
                dense_hit.chunk_text
                if dense_hit is not None
                else (sparse_hit.chunk_text if sparse_hit is not None else "")
            )
            parent_id = None
            parent_text = None
            system = None
            severity = None
            if dense_hit is not None:
                parent_id = dense_hit.parent_id
                parent_text = dense_hit.parent_text
                system = dense_hit.system
                severity = dense_hit.severity
            if sparse_hit is not None:
                parent_id = parent_id or sparse_hit.parent_id
                parent_text = parent_text or sparse_hit.parent_text
                system = system or sparse_hit.system
                severity = severity or sparse_hit.severity
            dense = dense_hit.score if dense_hit is not None else 0.0
            sparse = sparse_hit.score if sparse_hit is not None else 0.0
            hybrid = ((dense_w * dense) + (bm25_w * sparse)) / weight_sum
            fused.append(
                RetrievalHit(
                    document_id=document_id,
                    chunk_text=chunk_text,
                    score=round(hybrid, 6),
                    parent_id=parent_id,
                    parent_text=parent_text,
                    system=system,
                    severity=severity,
                )
            )

        fused.sort(key=lambda item: item.score, reverse=True)
        return fused

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

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            z = pow(2.718281828, -value)
            return 1.0 / (1.0 + z)
        z = pow(2.718281828, value)
        return z / (1.0 + z)


def extract_system_severity(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    metadata = payload.get("metadata")
    system = (
        payload.get("meta_systemName")
        or payload.get("systemName")
        or payload.get("system")
    )
    severity = payload.get("meta_severity") or payload.get("severity")
    if isinstance(metadata, dict):
        system = system or metadata.get("systemName") or metadata.get("system")
        severity = severity or metadata.get("severity")
    system_text = str(system).strip() if system is not None else ""
    severity_text = str(severity).strip() if severity is not None else ""
    return (system_text or None, severity_text or None)


def passes_text_metadata_gate(chunk_text: str, filter_metadata: dict[str, Any]) -> bool:
    lowered = chunk_text.lower()
    for value in filter_metadata.values():
        if isinstance(value, str) and value.lower() not in lowered:
            if value.lower() not in {"incident"}:
                return False
    return True
