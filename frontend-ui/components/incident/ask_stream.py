"""SSE ask stream dispatcher — maps stream events into UI state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
import streamlit as st

from api import client as api_client
from api.models import ApiHttpError
from components.analysis import summary_card
from components.incident.stream_body import compose_stream_body
from components.incident.stream_meta import render_stream_metadata
from config import ENDPOINTS, REQUEST_TIMEOUT
from utils import formatting


def dispatch_ask_stream(
    *,
    cleaned: str,
    payload: dict[str, Any],
    session_id: str,
) -> dict[str, Any] | None:
    """Run SSE ask and return the completed turn dict, or None on failure/cancel."""
    with st.chat_message("user"):
        st.markdown(cleaned)

    with st.chat_message("assistant"):
        meta_box = st.empty()
        status = st.status("Connecting to SSE stream…", expanded=True)
        metadata: dict[str, Any] = {}
        done_event: dict[str, Any] = {}
        tokens: list[str] = []
        stream_headers = {"X-Session-Id": session_id, "Accept": "text/event-stream"}

        def token_generator() -> Any:
            nonlocal metadata, done_event
            try:
                for event in api_client.iter_sse_events(
                    ENDPOINTS["ask_stream"],
                    payload,
                    timeout=max(REQUEST_TIMEOUT, 180.0),
                    headers=stream_headers,
                ):
                    kind = event.get("event")
                    if kind == "metadata":
                        metadata = event
                        status.update(label="Metadata received — streaming tokens…", state="running")
                        with meta_box.container():
                            render_stream_metadata(event, cleaned=cleaned)
                        continue
                    if kind == "token":
                        delta = str(event.get("delta") or "")
                        if delta:
                            tokens.append(delta)
                            yield delta
                        continue
                    if kind == "done":
                        done_event = event
                        status.update(label="Stream complete", state="complete")
                        continue
                    if kind == "error":
                        status.update(label="Stream error", state="error")
                        st.error(event.get("detail") or "Streaming failed")
                        return
            except ApiHttpError as exc:
                status.update(label="Blocked by security / rate limit", state="error")
                formatting.render_api_guard_error(exc)
                return
            except requests.RequestException as exc:
                status.update(label="Stream failed", state="error")
                st.error(f"SSE stream failed: {exc}")
                return

        streamed_text = st.write_stream(token_generator())
        if isinstance(streamed_text, str) and streamed_text and not tokens:
            tokens.append(streamed_text)

        full_answer = "".join(tokens) if tokens else (streamed_text or "")
        if not full_answer and not done_event:
            return None

        body = compose_stream_body(
            cleaned=cleaned,
            session_id=session_id,
            full_answer=full_answer,
            done_event=done_event,
            metadata=metadata,
        )
        formatting.faithfulness_badge(body.get("faithfulnessScore"), body.get("isGrounded"))
        summary_card.render_unsupported_claims(body.get("unsupportedClaims"))
        summary_card.render_turn_metrics(
            body,
            latency_ms=float(body["latencyMs"]),
            cached=bool(body.get("cached")),
        )
        left, right = st.columns(2)
        with left:
            st.markdown("#### Root Cause")
            st.write(body.get("rootCause") or "—")
        with right:
            st.markdown("#### Action Items")
            st.write(body.get("actionItems") or "—")

        completed_at = datetime.now(timezone.utc).isoformat()
        body["timestamp"] = completed_at
        return {
            "user": cleaned,
            "rewritten_query": body.get("rewrittenQuery") or cleaned,
            "session_id": body.get("sessionId") or session_id,
            "timestamp": completed_at,
            "response": body,
        }
