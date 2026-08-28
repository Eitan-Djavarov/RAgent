"""Tech-Doc-Intelligence — Streamlit Incident Intelligence UI."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000").rstrip("/")
AI_URL = os.getenv("AI_URL", "http://localhost:8000").rstrip("/")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("UI_REQUEST_TIMEOUT", "120"))

SAMPLE_QUERIES = [
    "How many Critical incidents?",
    "List incidents by hardware component",
    "What caused the buffer overflow in the AESA radar during target tracking?",
    "How was the EO/IR gimbal drift mitigated during thermal transition?",
    "What were the symptoms of the UAV SATCOM link loss during EW jamming?",
    "How many critical incidents and what caused the UAV jamming failures?",
]

TOOL_BADGES = {
    "HYBRID_RAG": ("Hybrid RAG", "#2563eb"),
    "SQL_METRICS": ("SQL Metrics", "#059669"),
    "HYBRID_COMBINED": ("Combined", "#7c3aed"),
}


class ApiHttpError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        error_code: str | None = None,
        reason: str | None = None,
        retry_after: int | None = None,
        raw_body: Any = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        self.reason = reason
        self.retry_after = retry_after
        self.raw_body = raw_body


def _parse_error_response(response: requests.Response) -> ApiHttpError:
    detail = f"HTTP {response.status_code}"
    error_code = None
    reason = None
    retry_after = None
    raw_body: Any = response.text[:800]
    try:
        payload = response.json()
        raw_body = payload
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("title") or detail)
            error_code = payload.get("errorCode") or payload.get("error_code")
            reason = payload.get("reason")
            retry_val = payload.get("retryAfterSeconds")
            if isinstance(retry_val, int):
                retry_after = retry_val
    except ValueError:
        detail = f"HTTP {response.status_code}: {response.text[:400]}"

    header_retry = response.headers.get("Retry-After")
    if retry_after is None and header_retry and header_retry.isdigit():
        retry_after = int(header_retry)

    return ApiHttpError(
        response.status_code,
        detail,
        error_code=str(error_code) if error_code else None,
        reason=str(reason) if reason else None,
        retry_after=retry_after,
        raw_body=raw_body,
    )


st.set_page_config(
    page_title="Incident Intelligence",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _get(url: str, timeout: float = 5.0) -> tuple[bool, Any]:
    try:
        response = requests.get(url, timeout=timeout)
        if response.ok:
            try:
                return True, response.json()
            except ValueError:
                return True, response.text
        return False, f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)


def _post(url: str, payload: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> tuple[bool, Any]:
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        if response.ok:
            return True, response.json()
        return False, f"HTTP {response.status_code}: {response.text[:400]}"
    except requests.RequestException as exc:
        return False, str(exc)


def _delete(url: str, timeout: float = 15.0) -> tuple[bool, Any]:
    try:
        response = requests.delete(url, timeout=timeout)
        if response.ok:
            try:
                return True, response.json()
            except ValueError:
                return True, response.text
        return False, f"HTTP {response.status_code}: {response.text[:400]}"
    except requests.RequestException as exc:
        return False, str(exc)


def _iter_sse_events(
    url: str,
    payload: dict[str, Any],
    timeout: float = REQUEST_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> Any:
    """Yield parsed SSE JSON payloads from a text/event-stream response."""
    with requests.post(url, json=payload, stream=True, timeout=timeout, headers=headers) as response:
        if not response.ok:
            raise _parse_error_response(response)
        event_data_lines: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            line = raw_line.rstrip("\r")
            if line == "":
                if not event_data_lines:
                    continue
                data = "\n".join(event_data_lines).strip()
                event_data_lines = []
                if not data:
                    continue
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                event_data_lines.append(line[5:].lstrip())
        if event_data_lines:
            data = "\n".join(event_data_lines).strip()
            if data:
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    return


def _post_multipart(
    url: str,
    *,
    files: dict[str, Any],
    data: dict[str, str],
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[bool, Any]:
    try:
        response = requests.post(url, files=files, data=data, timeout=timeout)
        if response.ok:
            return True, response.json()
        return False, f"HTTP {response.status_code}: {response.text[:400]}"
    except requests.RequestException as exc:
        return False, str(exc)


def check_health() -> dict[str, dict[str, Any]]:
    backend_ok, backend_body = _get(f"{BACKEND_URL}/api/health")
    ready_ok, ready_body = _get(f"{BACKEND_URL}/api/health/ready")
    ai_ok, ai_body = _get(f"{AI_URL}/health")
    qdrant_ok, qdrant_body = _get(f"{QDRANT_URL}/readyz")
    if not qdrant_ok:
        qdrant_ok, qdrant_body = _get(f"{QDRANT_URL}/healthz")

    postgres_ok = False
    redis_ok = False
    if ready_ok and isinstance(ready_body, dict):
        checks = ready_body.get("checks") or {}
        postgres_ok = bool(checks.get("postgres"))
        if not ai_ok:
            ai_ok = bool(checks.get("aiService"))

    if ai_ok and isinstance(ai_body, dict):
        details = ai_body.get("details") or {}
        redis_ok = str(details.get("redis", "")).lower() in {"up", "true", "ok", "healthy"}

    return {
        "backend": {"ok": backend_ok, "detail": backend_body},
        "ai": {"ok": ai_ok, "detail": ai_body},
        "postgres": {"ok": postgres_ok, "detail": ready_body if ready_ok else "unreachable"},
        "qdrant": {"ok": qdrant_ok, "detail": qdrant_body},
        "redis": {"ok": redis_ok, "detail": ai_body if ai_ok else "unreachable"},
    }


def status_pill(label: str, ok: bool) -> None:
    color = "#16a34a" if ok else "#dc2626"
    text = "UP" if ok else "DOWN"
    st.markdown(
        f"""
        <div style="
            display:flex;justify-content:space-between;align-items:center;
            padding:0.55rem 0.75rem;margin-bottom:0.45rem;border-radius:0.65rem;
            background:rgba(15,23,42,0.04);border:1px solid rgba(148,163,184,0.35);">
          <span style="font-weight:600;color:#0f172a;">{label}</span>
          <span style="
              font-size:0.75rem;font-weight:700;letter-spacing:0.04em;
              color:white;background:{color};padding:0.2rem 0.55rem;border-radius:999px;">
            {text}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def tool_badge(tool_used: str | None) -> None:
    key = (tool_used or "HYBRID_RAG").upper()
    label, color = TOOL_BADGES.get(key, (key, "#64748b"))
    st.markdown(
        f"""
        <div style="margin:0.4rem 0 1rem 0;">
          <span style="
              display:inline-block;padding:0.35rem 0.8rem;border-radius:999px;
              background:{color};color:white;font-weight:700;font-size:0.85rem;
              letter-spacing:0.03em;">
            Route · {label}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def cache_badge(cached: bool) -> None:
    if cached:
        label, color, bg = "Cache Hit", "#047857", "rgba(16,185,129,0.12)"
    else:
        label, color, bg = "Cache Miss", "#b45309", "rgba(245,158,11,0.12)"
    st.markdown(
        f"""
        <div style="
            display:inline-flex;align-items:center;gap:0.4rem;
            padding:0.35rem 0.75rem;border-radius:999px;margin:0.2rem 0 0.6rem 0;
            background:{bg};border:1px solid {color};color:{color};
            font-weight:700;font-size:0.82rem;letter-spacing:0.03em;">
          {label}
        </div>
        """,
        unsafe_allow_html=True,
    )


def cache_hit_banner(latency_ms: float) -> None:
    st.markdown(
        f"""
        <div style="
            padding:0.85rem 1rem;margin:0.2rem 0 1rem 0;border-radius:0.75rem;
            background:linear-gradient(90deg, rgba(16,185,129,0.16), rgba(45,212,191,0.08));
            border:1px solid rgba(5,150,105,0.35);color:#065f46;">
          <strong>Semantic Cache Hit</strong> — response served instantly from Redis
          in <strong>{latency_ms:.1f} ms</strong> (cosine / exact match).
        </div>
        """,
        unsafe_allow_html=True,
    )


def rate_limit_warning(detail: str, retry_after: int | None) -> None:
    seconds = retry_after if retry_after and retry_after > 0 else 60
    st.markdown(
        f"""
        <div style="
            padding:0.95rem 1.1rem;margin:0.4rem 0 1rem 0;border-radius:0.8rem;
            background:linear-gradient(90deg, rgba(245,158,11,0.18), rgba(251,191,36,0.08));
            border:1px solid rgba(217,119,6,0.45);color:#92400e;">
          <strong>Rate limit reached</strong><br/>
          {detail}<br/>
          <span style="font-size:0.92rem;">Please wait about <strong>{seconds}s</strong> before retrying.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.warning(f"Retry countdown: ~{seconds} seconds")


def security_warning_banner(detail: str, reason: str | None = None) -> None:
    reason_line = f"<br/><span style='font-size:0.9rem;'>Flag: <code>{reason}</code></span>" if reason else ""
    st.markdown(
        f"""
        <div style="
            padding:0.95rem 1.1rem;margin:0.4rem 0 1rem 0;border-radius:0.8rem;
            background:linear-gradient(90deg, rgba(239,68,68,0.16), rgba(249,115,22,0.10));
            border:1px solid rgba(220,38,38,0.45);color:#7f1d1d;">
          <strong>Security Warning</strong> — query blocked by input guardrails.<br/>
          {detail}{reason_line}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_api_guard_error(exc: ApiHttpError) -> None:
    if exc.status_code == 429 or (exc.error_code or "").upper() == "RATE_LIMITED":
        rate_limit_warning(exc.detail, exc.retry_after)
        return
    if exc.status_code == 400 or (exc.error_code or "").upper() == "SECURITY_VIOLATION":
        security_warning_banner(exc.detail, exc.reason or exc.error_code)
        return
    st.error(f"Request failed ({exc.status_code}): {exc.detail}")


def load_incidents() -> pd.DataFrame:
    ok, body = _get(f"{BACKEND_URL}/api/incidents", timeout=15.0)
    if not ok or not isinstance(body, list):
        return pd.DataFrame()
    frame = pd.DataFrame(body)
    if frame.empty:
        return frame
    rename = {
        "systemName": "system_name",
        "createdAt": "created_at",
        "indexedAt": "indexed_at",
    }
    frame = frame.rename(columns=rename)
    if "severity" in frame.columns:
        frame["severity"] = frame["severity"].astype(str).str.title()
    return frame


def ensure_chat_session() -> str:
    if "session_id" not in st.session_state or not st.session_state["session_id"]:
        st.session_state["session_id"] = str(uuid.uuid4())
    if "chat_thread" not in st.session_state:
        st.session_state["chat_thread"] = []
    return str(st.session_state["session_id"])


def reset_chat_session() -> None:
    old_session = st.session_state.get("session_id")
    if old_session:
        _delete(f"{AI_URL}/api/v1/sessions/{old_session}")
    st.session_state["session_id"] = str(uuid.uuid4())
    st.session_state["chat_thread"] = []
    st.session_state.pop("assistant_query_input", None)
    st.session_state.pop("last_query", None)


def render_sidebar() -> str | None:
    ensure_chat_session()
    with st.sidebar:
        st.markdown("## 🛰️ Incident Intelligence")
        st.caption("Agentic assistant for aerospace / defense incident analysis")
        st.caption(f"Session: `{st.session_state['session_id'][:8]}…`")
        st.divider()
        st.markdown("### System Health")
        health = check_health()
        status_pill(".NET Backend", health["backend"]["ok"])
        status_pill("FastAPI AI", health["ai"]["ok"])
        status_pill("PostgreSQL", health["postgres"]["ok"])
        status_pill("Qdrant", health["qdrant"]["ok"])
        status_pill("Redis Cache", health["redis"]["ok"])

        if st.button("Refresh health", use_container_width=True):
            st.rerun()

        if st.button("Clear Cache", use_container_width=True, type="secondary"):
            ok, body = _delete(f"{AI_URL}/api/v1/cache")
            if ok:
                deleted = body.get("deletedKeys") if isinstance(body, dict) else "?"
                st.success(f"Semantic cache cleared ({deleted} keys).")
            else:
                st.error(f"Clear cache failed: {body}")

        if st.button("New Chat / Reset Session", use_container_width=True):
            reset_chat_session()
            st.success("Started a new conversation session.")
            st.rerun()

        st.divider()
        st.markdown("### Sample Queries")
        selected: str | None = None
        for query in SAMPLE_QUERIES:
            if st.button(query, key=f"sample_{hash(query)}", use_container_width=True):
                selected = query
        st.divider()
        st.caption(f"Backend: `{BACKEND_URL}`")
        st.caption(f"AI: `{AI_URL}`")
    return selected


def _render_chat_turn(turn: dict[str, Any], *, expanded_latest: bool = False) -> None:
    with st.chat_message("user"):
        st.markdown(turn.get("user") or "")

    with st.chat_message("assistant"):
        body = turn.get("response") or {}
        tool_used = body.get("toolUsed") or body.get("retrievalMode")
        tool_badge(str(tool_used) if tool_used else None)

        cached = bool(body.get("cached"))
        latency_ms = float(body.get("latencyMs") or 0)
        if cached:
            cache_hit_banner(latency_ms)

        rewritten = body.get("rewrittenQuery") or turn.get("rewritten_query")
        original = body.get("originalQuery") or turn.get("user")
        if rewritten and original and rewritten.strip() != str(original).strip():
            with st.expander("Rewritten Standalone Query", expanded=expanded_latest):
                st.code(str(rewritten), language="text")
                st.caption("Resolved from conversational context for routing, cache, retrieval, and SQL.")
        elif rewritten:
            with st.expander("Rewritten Standalone Query", expanded=False):
                st.code(str(rewritten), language="text")
                st.caption("Query was already self-contained.")

        metric_cols = st.columns(4)
        metric_cols[0].metric("Latency (ms)", f"{latency_ms:.1f}")
        metric_cols[1].metric("Citations", len(body.get("citations") or []))
        sql_result = body.get("sqlQueryResult")
        metric_cols[2].metric(
            "SQL rows",
            (sql_result or {}).get("rowCount", 0) if isinstance(sql_result, dict) else 0,
        )
        with metric_cols[3]:
            st.caption("Cache")
            cache_badge(cached)

        st.markdown("#### Summary")
        st.info(body.get("summary") or body.get("answer") or "No summary returned.")

        left, right = st.columns(2)
        with left:
            st.markdown("#### Root Cause")
            st.write(body.get("rootCause") or "—")
        with right:
            st.markdown("#### Action Items")
            st.write(body.get("actionItems") or "—")

        if isinstance(sql_result, dict) and sql_result.get("rows") is not None:
            with st.expander("SQL query result", expanded=tool_used == "SQL_METRICS"):
                st.code(sql_result.get("query") or "", language="sql")
                st.caption(sql_result.get("interpretation") or "")
                rows = sql_result.get("rows") or []
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        citations = body.get("citations") or []
        st.markdown("#### Citations")
        if not citations:
            st.caption("No citations for this route.")
        for index, citation in enumerate(citations, start=1):
            score = float(citation.get("score") or 0.0)
            doc_id = citation.get("documentId") or "unknown"
            chunk = citation.get("chunkText") or ""
            with st.expander(
                f"[{index}] {doc_id} · similarity {score:.3f}",
                expanded=index == 1 and expanded_latest,
            ):
                st.progress(min(max(score, 0.0), 1.0))
                st.write(chunk)


def render_assistant(prefill: str | None) -> None:
    session_id = ensure_chat_session()
    st.markdown("### Agentic Incident Assistant")
    st.write(
        "Multi-turn chat with contextual query rewriting and live token streaming. "
        "The router chooses **SQL Metrics**, **Hybrid RAG**, or **Combined** execution."
    )

    thread: list[dict[str, Any]] = st.session_state.get("chat_thread", [])
    if thread:
        st.markdown("#### Chat Thread")
        for index, turn in enumerate(thread):
            _render_chat_turn(turn, expanded_latest=index == len(thread) - 1)
    else:
        st.caption("No messages yet — ask a question to start this session.")

    default_query = (
        prefill
        or st.session_state.get("last_query")
        or SAMPLE_QUERIES[2]
    )
    if "assistant_query" in st.session_state:
        st.session_state["assistant_query_input"] = st.session_state.pop("assistant_query")
    elif "assistant_query_input" not in st.session_state:
        st.session_state["assistant_query_input"] = default_query

    st.markdown("#### Ask")
    query = st.text_area(
        "Question",
        height=110,
        placeholder="e.g. What caused AESA buffer overflow during multi-target tracking?",
        key="assistant_query_input",
    )
    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        top_k = st.slider("Top K", min_value=1, max_value=10, value=4)
    with col_b:
        min_severity = st.selectbox(
            "Min severity",
            options=["", "Low", "Medium", "High", "Critical"],
            index=0,
        )
    with col_c:
        system_name = st.text_input(
            "System filter (optional)",
            value=st.session_state.get("assistant_system", ""),
        )

    auto_ask = bool(st.session_state.pop("auto_ask", False))
    ask_clicked = st.button("Ask agent", type="primary", use_container_width=False)

    if ask_clicked or prefill or auto_ask:
        cleaned = (query or "").strip()
        if not cleaned:
            st.warning("Enter a question first.")
            return

        st.session_state["last_query"] = cleaned
        payload: dict[str, Any] = {
            "queryText": cleaned,
            "topK": top_k,
            "sessionId": session_id,
        }
        if min_severity:
            payload["minSeverity"] = min_severity
        if system_name.strip():
            payload["systemName"] = system_name.strip()

        with st.chat_message("user"):
            st.markdown(cleaned)

        with st.chat_message("assistant"):
            meta_box = st.empty()
            status = st.status("Connecting to SSE stream…", expanded=True)

            metadata: dict[str, Any] = {}
            done_event: dict[str, Any] = {}
            tokens: list[str] = []
            body: dict[str, Any] = {}
            stream_headers = {"X-Session-Id": session_id, "Accept": "text/event-stream"}

            def token_generator() -> Any:
                nonlocal metadata, done_event
                try:
                    for event in _iter_sse_events(
                        f"{BACKEND_URL}/api/incidents/ask/stream",
                        payload,
                        timeout=max(REQUEST_TIMEOUT, 180.0),
                        headers=stream_headers,
                    ):
                        kind = event.get("event")
                        if kind == "metadata":
                            metadata = event
                            status.update(label="Metadata received — streaming tokens…", state="running")
                            with meta_box.container():
                                tool_badge(str(event.get("toolUsed") or "HYBRID_RAG"))
                                if event.get("cached"):
                                    cache_hit_banner(0.0)
                                rewritten = event.get("rewrittenQuery")
                                original = event.get("originalQuery") or cleaned
                                if rewritten:
                                    with st.expander(
                                        "Rewritten Standalone Query",
                                        expanded=bool(rewritten != original),
                                    ):
                                        st.code(str(rewritten), language="text")
                                citations = event.get("citations") or []
                                st.caption(f"Citations ready: {len(citations)}")
                                for index, citation in enumerate(citations[:5], start=1):
                                    score = float(citation.get("score") or 0.0)
                                    doc_id = citation.get("documentId") or "unknown"
                                    with st.expander(
                                        f"[{index}] {doc_id} · {score:.3f}",
                                        expanded=index == 1,
                                    ):
                                        st.write(citation.get("chunkText") or "")
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
                    render_api_guard_error(exc)
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
                return

            summary = done_event.get("summary") or full_answer
            body = {
                "summary": summary,
                "rootCause": done_event.get("rootCause") or "—",
                "actionItems": done_event.get("actionItems") or "—",
                "answer": full_answer,
                "citations": metadata.get("citations") or [],
                "toolUsed": done_event.get("toolUsed") or metadata.get("toolUsed"),
                "latencyMs": done_event.get("latencyMs") or 0,
                "cached": bool(done_event.get("cached") or metadata.get("cached")),
                "rewrittenQuery": done_event.get("rewrittenQuery")
                or metadata.get("rewrittenQuery"),
                "originalQuery": done_event.get("originalQuery")
                or metadata.get("originalQuery")
                or cleaned,
                "sqlQueryResult": metadata.get("sqlQueryResult"),
                "sessionId": done_event.get("sessionId") or session_id,
            }

            metric_cols = st.columns(4)
            metric_cols[0].metric("Latency (ms)", f"{float(body['latencyMs']):.1f}")
            metric_cols[1].metric("Citations", len(body.get("citations") or []))
            sql_result = body.get("sqlQueryResult")
            metric_cols[2].metric(
                "SQL rows",
                (sql_result or {}).get("rowCount", 0) if isinstance(sql_result, dict) else 0,
            )
            with metric_cols[3]:
                st.caption("Cache")
                cache_badge(bool(body.get("cached")))

            left, right = st.columns(2)
            with left:
                st.markdown("#### Root Cause")
                st.write(body.get("rootCause") or "—")
            with right:
                st.markdown("#### Action Items")
                st.write(body.get("actionItems") or "—")

        if not body:
            return

        turn = {
            "user": cleaned,
            "rewritten_query": body.get("rewrittenQuery") or cleaned,
            "response": body,
        }
        st.session_state.setdefault("chat_thread", []).append(turn)
        st.session_state["assistant_query_input"] = ""
        st.rerun()


def render_analytics() -> None:
    st.markdown("### Incident Analytics & SQL Explorer")
    st.write("Live charts and table from `GET /api/incidents`, plus quick SQL-style asks.")

    refresh = st.button("Refresh incident data", type="secondary")
    if refresh or "incidents_df" not in st.session_state:
        with st.spinner("Loading incidents from backend..."):
            st.session_state["incidents_df"] = load_incidents()

    frame: pd.DataFrame = st.session_state.get("incidents_df", pd.DataFrame())
    if frame.empty:
        st.warning("No incidents returned. Seed data with `scripts/seed_and_verify.py` first.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total incidents", len(frame))
        if "severity" in frame.columns:
            critical = int((frame["severity"].str.lower() == "critical").sum())
            c2.metric("Critical", critical)
        if "system_name" in frame.columns:
            c3.metric("Systems", frame["system_name"].nunique())

        chart_left, chart_right = st.columns(2)
        with chart_left:
            if "severity" in frame.columns:
                severity_counts = (
                    frame["severity"].value_counts().rename_axis("severity").reset_index(name="count")
                )
                fig = px.bar(
                    severity_counts,
                    x="severity",
                    y="count",
                    color="severity",
                    title="Incidents by Severity",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)
        with chart_right:
            system_col = "system_name" if "system_name" in frame.columns else None
            if system_col:
                system_counts = (
                    frame[system_col].value_counts().rename_axis("component").reset_index(name="count")
                )
                fig = px.pie(
                    system_counts,
                    names="component",
                    values="count",
                    title="Incidents by Component / System",
                    hole=0.35,
                )
                fig.update_layout(margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Live incident table")
        display_cols = [
            col
            for col in ["id", "title", "system_name", "severity", "created_at", "indexed_at"]
            if col in frame.columns
        ]
        st.dataframe(
            frame[display_cols] if display_cols else frame,
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("#### SQL Explorer (via agentic ask)")
    sql_query = st.selectbox(
        "Metric question",
        options=[
            "How many Critical incidents?",
            "How many High incidents?",
            "List incidents by hardware component",
            "Show incidents breakdown by severity",
        ],
    )
    if st.button("Run SQL-style ask", type="primary"):
        with st.spinner("Executing SQL metrics route..."):
            try:
                response = requests.post(
                    f"{BACKEND_URL}/api/incidents/ask",
                    json={"queryText": sql_query, "topK": 3},
                    timeout=REQUEST_TIMEOUT,
                )
                if not response.ok:
                    render_api_guard_error(_parse_error_response(response))
                    return
                body = response.json()
            except requests.RequestException as exc:
                st.error(f"SQL explorer failed: {exc}")
                return
        if not isinstance(body, dict):
            st.error("SQL explorer returned an unexpected payload.")
            return
        tool_badge(str(body.get("toolUsed") or "SQL_METRICS"))
        st.write(body.get("summary") or body.get("answer"))
        sql_result = body.get("sqlQueryResult") or {}
        if sql_result.get("query"):
            st.code(sql_result["query"], language="sql")
        rows = sql_result.get("rows") or []
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_upload() -> None:
    st.markdown("### Upload & Ingest Incident Documents")
    st.write(
        "Drop a PDF, TXT, or Markdown report. The pipeline extracts text, chunks it, "
        "embeds into Qdrant, and syncs metadata into PostgreSQL."
    )

    uploaded = st.file_uploader(
        "Incident document",
        type=["pdf", "txt", "md"],
        accept_multiple_files=False,
        help="Drag and drop or browse — .pdf, .txt, .md",
    )

    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input("Document Title", placeholder="AESA Track Buffer Overflow")
        system_name = st.text_input("System Name", placeholder="AESA Radar")
    with col2:
        severity = st.selectbox(
            "Severity",
            options=["Low", "Medium", "High", "Critical"],
            index=2,
        )
        tags = st.text_input(
            "Tags (comma-separated)",
            placeholder="radar, firmware, tracking",
        )

    submit = st.button("Ingest document", type="primary", disabled=uploaded is None)

    if not submit:
        if "last_upload_result" in st.session_state:
            _render_upload_success(st.session_state["last_upload_result"])
        return

    if uploaded is None:
        st.warning("Choose a file first.")
        return
    if not system_name.strip():
        st.error("System Name is required.")
        return

    resolved_title = title.strip() or uploaded.name.rsplit(".", 1)[0]
    files = {
        "file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream"),
    }
    data = {
        "title": resolved_title,
        "system": system_name.strip(),
        "severity": severity,
        "subsystemTags": tags.strip(),
    }

    with st.spinner("Extracting, chunking, embedding, and indexing..."):
        ok, body = _post_multipart(
            f"{BACKEND_URL}/api/incidents/upload",
            files=files,
            data=data,
            timeout=max(REQUEST_TIMEOUT, 180.0),
        )

    if not ok or not isinstance(body, dict):
        st.error(f"Upload failed: {body}")
        return

    st.session_state["last_upload_result"] = body
    st.session_state.pop("incidents_df", None)
    _render_upload_success(body)


def _render_upload_success(body: dict[str, Any]) -> None:
    document_id = body.get("documentId") or "—"
    chunk_count = body.get("chunkCount") or body.get("chunksCount") or 0
    status = body.get("status") or ("indexed" if body.get("success") else "unknown")
    title = body.get("title") or "Uploaded document"
    system_name = body.get("systemName") or ""

    st.success("Document ingested successfully.")
    st.markdown(
        f"""
        <div style="
            padding:1rem 1.15rem;margin:0.75rem 0 1rem 0;border-radius:0.85rem;
            background:linear-gradient(135deg, rgba(37,99,235,0.08), rgba(14,165,233,0.06));
            border:1px solid rgba(37,99,235,0.25);">
          <div style="font-weight:700;color:#0f172a;margin-bottom:0.35rem;">{title}</div>
          <div style="color:#334155;font-size:0.92rem;">
            <strong>documentId:</strong> <code>{document_id}</code><br/>
            <strong>chunks:</strong> {chunk_count} &nbsp;·&nbsp;
            <strong>status:</strong> {status}
            {" &nbsp;·&nbsp; <strong>system:</strong> " + system_name if system_name else ""}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = st.columns(3)
    metrics[0].metric("Document ID", str(document_id)[:8] + "…")
    metrics[1].metric("Chunks indexed", int(chunk_count))
    metrics[2].metric("Status", str(status))

    if st.button("Query this document in Assistant", type="secondary"):
        st.session_state["assistant_query"] = (
            f"Summarize root cause and recommended mitigations for the uploaded incident "
            f"document '{title}' (documentId={document_id})."
        )
        st.session_state["assistant_system"] = system_name
        st.session_state["auto_ask"] = True
        st.session_state["active_tab"] = "Agentic Incident Assistant"
        st.rerun()


def main() -> None:
    st.markdown(
        """
        <style>
          .block-container { padding-top: 1.2rem; }
          div[data-testid="stSidebar"] { background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Incident Intelligence Platform")
    st.caption("Streamlit console for agentic RAG, SQL metrics, document ingest, and analytics")

    prefill = render_sidebar()
    tab_labels = [
        "Agentic Incident Assistant",
        "Incident Analytics & SQL Explorer",
        "Upload & Ingest Incident Documents",
    ]
    forced = st.session_state.pop("active_tab", None)
    if forced in tab_labels:
        st.session_state["ui_tab"] = forced
    selected = st.radio(
        "Workspace",
        options=tab_labels,
        horizontal=True,
        label_visibility="collapsed",
        key="ui_tab",
    )

    if selected == tab_labels[0]:
        render_assistant(prefill)
    elif selected == tab_labels[1]:
        render_analytics()
    else:
        render_upload()


if __name__ == "__main__":
    main()
