from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import SourceCitation

LOW_RELEVANCE_MESSAGE = (
    "No sufficiently relevant incident context was found in the indexed documents."
)


@dataclass(slots=True)
class RetrievalHit:
    """Intermediate retrieval hit before parent expansion."""

    document_id: str
    chunk_text: str
    score: float
    parent_id: str | None = None
    parent_text: str | None = None
    system: str | None = None
    severity: str | None = None


def expand_and_dedupe_parents(
    hits: list[RetrievalHit],
    *,
    top_n: int | None = None,
) -> list[SourceCitation]:
    """
    Expand child hits to parent paragraphs and deduplicate by parent_id.

    Ranking order is preserved (highest child score first). When multiple children
    map to the same parent, the first (best-scoring) occurrence wins.
    """
    expanded: list[SourceCitation] = []
    seen_parents: set[str] = set()

    for hit in hits:
        parent_key = (hit.parent_id or "").strip() or f"{hit.document_id}::{hash(hit.chunk_text)}"
        if parent_key in seen_parents:
            continue
        seen_parents.add(parent_key)
        parent_body = (hit.parent_text or "").strip() or hit.chunk_text
        expanded.append(
            SourceCitation(
                document_id=hit.document_id,
                doc_id=hit.document_id,
                chunk_text=parent_body,
                score=hit.score,
                parent_id=parent_key,
                system=hit.system,
                severity=hit.severity,
            )
        )
        if top_n is not None and len(expanded) >= top_n:
            break
    return expanded


def filter_by_min_score(
    sources: list[SourceCitation],
    *,
    min_score: float,
) -> list[SourceCitation]:
    """Keep citations meeting the minimum relevance threshold."""
    if min_score <= 0:
        return list(sources)
    return [source for source in sources if source.score >= min_score]


def meets_min_score_threshold(
    sources: list[SourceCitation],
    *,
    min_score: float,
) -> bool:
    """True when at least one citation meets the configured relevance floor."""
    if not sources:
        return False
    if min_score <= 0:
        return True
    return any(source.score >= min_score for source in sources)


def low_relevance_answer() -> str:
    return (
        "## Executive Summary\n"
        f"{LOW_RELEVANCE_MESSAGE}\n\n"
        "## Root Cause Analysis\n"
        "Insufficient grounded evidence above the minimum retrieval score threshold.\n\n"
        "## Recommended Mitigation / Corrective Actions\n"
        "Refine the query, lower filters, or ingest additional incident reports, then retry.\n\n"
        "## Source Citations\n"
        "- none"
    )
