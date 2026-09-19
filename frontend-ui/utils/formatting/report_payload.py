"""Investigation report payload assembly and Markdown/JSON serialization."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import streamlit as st


def safe_filename_token(value: str | None, *, fallback: str = "session") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned or fallback


def turn_timestamp_iso(turn: dict[str, Any]) -> str:
    raw = turn.get("timestamp") or (turn.get("response") or {}).get("timestamp")
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


def investigation_report_payload(turn: dict[str, Any]) -> dict[str, Any]:
    """Assemble download payload from API turn fields only (no client enrichment)."""
    body = turn.get("response") or {}
    session_id = (
        turn.get("session_id")
        or body.get("sessionId")
        or st.session_state.get("session_id")
        or "unknown"
    )
    original = body.get("originalQuery") or turn.get("user") or ""
    rewritten = body.get("rewrittenQuery") or turn.get("rewritten_query") or original
    citations_raw = body.get("citations") or []
    citations: list[dict[str, Any]] = []
    for index, citation in enumerate(citations_raw, start=1):
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("documentId") or citation.get("docId") or "unknown")
        citations.append(
            {
                "citationIndex": citation.get("citationIndex") or index,
                "documentId": doc_id,
                "docId": citation.get("docId") or doc_id,
                "systemName": citation.get("systemName") or citation.get("system") or "—",
                "system": citation.get("system") or citation.get("systemName") or "—",
                "severity": citation.get("severity") or "—",
                "score": citation.get("score"),
                "chunkText": citation.get("chunkText") or "",
            }
        )
    return {
        "title": "Incident Investigation Report",
        "timestamp": turn_timestamp_iso(turn),
        "sessionId": str(session_id),
        "toolUsed": body.get("toolUsed") or body.get("retrievalMode"),
        "faithfulnessScore": body.get("faithfulnessScore"),
        "isGrounded": body.get("isGrounded"),
        "unsupportedClaims": body.get("unsupportedClaims") or [],
        "latencyMs": body.get("latencyMs"),
        "cached": bool(body.get("cached")),
        "query": original,
        "rewrittenQuery": rewritten,
        "summary": body.get("summary"),
        "rootCause": body.get("rootCause"),
        "actionItems": body.get("actionItems"),
        "answer": body.get("answer") or body.get("summary") or "",
        "citations": citations,
        "sqlQueryResult": body.get("sqlQueryResult"),
    }


def investigation_report_filenames(payload: dict[str, Any]) -> tuple[str, str]:
    session_token = safe_filename_token(str(payload.get("sessionId") or "session"))
    ts = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
    try:
        stamp = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%Y%m%d-%H%M%S")
    except ValueError:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"incident-report-{session_token}-{stamp}"
    return f"{base}.md", f"{base}.json"


def dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
