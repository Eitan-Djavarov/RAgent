"""Typed shapes mirroring backend DTOs for UI binding (display only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApiHttpError(Exception):
    status_code: int
    detail: str
    error_code: str | None = None
    reason: str | None = None
    retry_after: int | None = None
    raw_body: Any = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.detail)


@dataclass
class HealthStatus:
    backend: dict[str, Any] = field(default_factory=dict)
    ai: dict[str, Any] = field(default_factory=dict)
    postgres: dict[str, Any] = field(default_factory=dict)
    qdrant: dict[str, Any] = field(default_factory=dict)
    redis: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "backend": self.backend,
            "ai": self.ai,
            "postgres": self.postgres,
            "qdrant": self.qdrant,
            "redis": self.redis,
        }


@dataclass
class CitationView:
    """Display fields from AskIncident / AI citation payloads."""

    document_id: str = "unknown"
    chunk_text: str = ""
    score: float = 0.0
    citation_index: int | None = None
    doc_id: str | None = None
    system: str | None = None
    severity: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any], fallback_index: int = 1) -> CitationView:
        doc_id = str(payload.get("docId") or payload.get("documentId") or "unknown")
        return cls(
            document_id=str(payload.get("documentId") or doc_id),
            chunk_text=str(payload.get("chunkText") or ""),
            score=float(payload.get("score") or 0.0),
            citation_index=int(payload.get("citationIndex") or fallback_index),
            doc_id=doc_id,
            system=(str(payload["system"]) if payload.get("system") else None)
            or (str(payload["systemName"]) if payload.get("systemName") else None),
            severity=str(payload["severity"]) if payload.get("severity") else None,
        )
