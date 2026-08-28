from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if len(token) > 2]


@dataclass(slots=True)
class Bm25Document:
    point_id: str
    document_id: str
    chunk_text: str
    title: str
    parent_id: str | None = None
    parent_text: str | None = None


class Bm25Store:
    """In-memory BM25 sparse index synchronized with ingested chunks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._docs: list[Bm25Document] = []
        self._tokenized: list[list[str]] = []
        self._bm25: BM25Okapi | None = None

    def clear(self) -> None:
        with self._lock:
            self._docs = []
            self._tokenized = []
            self._bm25 = None

    def remove_document(self, document_id: str) -> None:
        with self._lock:
            keep_docs: list[Bm25Document] = []
            keep_tokens: list[list[str]] = []
            for doc, tokens in zip(self._docs, self._tokenized, strict=True):
                if doc.document_id != document_id:
                    keep_docs.append(doc)
                    keep_tokens.append(tokens)
            self._docs = keep_docs
            self._tokenized = keep_tokens
            self._rebuild_unlocked()

    def add_chunks(
        self,
        *,
        document_id: str,
        title: str,
        point_ids: list[str],
        chunk_texts: list[str],
        parent_ids: list[str | None] | None = None,
        parent_texts: list[str | None] | None = None,
    ) -> None:
        resolved_parent_ids = parent_ids or [None] * len(point_ids)
        resolved_parent_texts = parent_texts or [None] * len(point_ids)
        if len(resolved_parent_ids) != len(point_ids) or len(resolved_parent_texts) != len(point_ids):
            raise ValueError("parent_ids/parent_texts length must match point_ids")
        with self._lock:
            for point_id, chunk_text, parent_id, parent_text in zip(
                point_ids,
                chunk_texts,
                resolved_parent_ids,
                resolved_parent_texts,
                strict=True,
            ):
                self._docs.append(
                    Bm25Document(
                        point_id=point_id,
                        document_id=document_id,
                        chunk_text=chunk_text,
                        title=title,
                        parent_id=parent_id,
                        parent_text=parent_text,
                    )
                )
                self._tokenized.append(tokenize(f"{title} {chunk_text}"))
            self._rebuild_unlocked()

    def search(self, query: str, top_k: int) -> list[tuple[Bm25Document, float]]:
        with self._lock:
            if not self._docs or self._bm25 is None or top_k <= 0:
                return []
            scores = self._bm25.get_scores(tokenize(query))
            ranked = sorted(
                enumerate(scores),
                key=lambda item: float(item[1]),
                reverse=True,
            )[:top_k]
            max_score = max((float(score) for _, score in ranked), default=0.0)
            results: list[tuple[Bm25Document, float]] = []
            for index, score in ranked:
                raw = float(score)
                normalized = (raw / max_score) if max_score > 0 else 0.0
                results.append((self._docs[index], normalized))
            return results

    def _rebuild_unlocked(self) -> None:
        if not self._tokenized:
            self._bm25 = None
            return
        self._bm25 = BM25Okapi(self._tokenized)
        logger.debug("BM25 index rebuilt with %s documents", len(self._docs))
