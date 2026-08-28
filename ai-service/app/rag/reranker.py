from __future__ import annotations

import logging
import threading
from typing import Protocol

logger = logging.getLogger(__name__)


class RerankCandidate(Protocol):
    chunk_text: str
    score: float


class CrossEncoderReranker:
    """Lazy-loaded CrossEncoder reranker (sentence-transformers)."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            from sentence_transformers import CrossEncoder

            logger.info("Loading CrossEncoder reranker %s", self._model_name)
            self._model = CrossEncoder(self._model_name)
            return self._model

    def rerank(
        self,
        query: str,
        candidates: list[tuple[str, str, float]],
        top_n: int,
    ) -> list[tuple[str, str, float]]:
        """
        Re-rank candidates.

        Args:
            query: user query
            candidates: list of (document_id, chunk_text, prior_score)
            top_n: number of results to keep
        """
        if not candidates:
            return []
        if top_n <= 0:
            return []
        if len(candidates) == 1 or top_n >= len(candidates):
            # Still score single/small sets for consistent confidence values.
            pass

        model = self._ensure_model()
        pairs = [(query, chunk_text) for _, chunk_text, _ in candidates]
        scores = model.predict(pairs)  # type: ignore[attr-defined]
        scored = [
            (document_id, chunk_text, float(score))
            for (document_id, chunk_text, _), score in zip(candidates, scores, strict=True)
        ]
        scored.sort(key=lambda item: item[2], reverse=True)
        return scored[:top_n]
