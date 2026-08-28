from __future__ import annotations

import re

from app.models.schemas import SourceCitation

_MARKER_RE = re.compile(r"\[(\d+)\]")


def index_citations(sources: list[SourceCitation]) -> list[SourceCitation]:
    """Assign 1-based citation_index values and normalize doc_id/system/severity."""
    indexed: list[SourceCitation] = []
    for position, source in enumerate(sources, start=1):
        indexed.append(
            source.model_copy(
                update={
                    "citation_index": position,
                    "doc_id": source.doc_id or source.document_id,
                    "document_id": source.document_id or source.doc_id or "unknown",
                    "system": (source.system or "").strip() or None,
                    "severity": (source.severity or "").strip() or None,
                }
            )
        )
    return indexed


def extract_citation_markers(text: str) -> list[int]:
    """Return unique citation marker numbers in first-seen order."""
    seen: set[int] = set()
    ordered: list[int] = []
    for match in _MARKER_RE.finditer(text or ""):
        value = int(match.group(1))
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def markers_are_valid(text: str, citations: list[SourceCitation]) -> bool:
    """True when every inline marker maps to a citation_index in the response list."""
    allowed = {c.citation_index for c in citations if c.citation_index > 0}
    if not allowed:
        return extract_citation_markers(text) == []
    markers = extract_citation_markers(text)
    if not markers:
        return False
    return all(marker in allowed for marker in markers)


def attach_heuristic_markers(text: str, citation_index: int) -> str:
    """Append a citation marker to a heuristic sentence if none is present."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    if _MARKER_RE.search(cleaned):
        return cleaned
    if cleaned.endswith((".", "!", "?")):
        return f"{cleaned[:-1]} [{citation_index}]{cleaned[-1]}"
    return f"{cleaned} [{citation_index}]"
