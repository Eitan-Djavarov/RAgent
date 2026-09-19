"""Map SSE done/metadata events into the display response body."""

from __future__ import annotations

from typing import Any


def compose_stream_body(
    *,
    cleaned: str,
    session_id: str,
    full_answer: str,
    done_event: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    summary = done_event.get("summary") or full_answer
    return {
        "summary": summary,
        "rootCause": done_event.get("rootCause") or "—",
        "actionItems": done_event.get("actionItems") or "—",
        "answer": full_answer,
        "citations": metadata.get("citations") or [],
        "toolUsed": done_event.get("toolUsed") or metadata.get("toolUsed"),
        "latencyMs": done_event.get("latencyMs") or 0,
        "cached": bool(done_event.get("cached") or metadata.get("cached")),
        "rewrittenQuery": done_event.get("rewrittenQuery") or metadata.get("rewrittenQuery"),
        "originalQuery": done_event.get("originalQuery")
        or metadata.get("originalQuery")
        or cleaned,
        "sqlQueryResult": metadata.get("sqlQueryResult"),
        "sessionId": done_event.get("sessionId") or session_id,
        "faithfulnessScore": done_event.get("faithfulnessScore")
        if done_event.get("faithfulnessScore") is not None
        else metadata.get("faithfulnessScore"),
        "isGrounded": done_event.get("isGrounded")
        if done_event.get("isGrounded") is not None
        else metadata.get("isGrounded"),
        "unsupportedClaims": done_event.get("unsupportedClaims")
        or metadata.get("unsupportedClaims")
        or [],
    }
