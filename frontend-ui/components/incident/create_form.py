"""Agentic assistant ask form — inputs and submission dispatch."""

from __future__ import annotations

from typing import Any

import streamlit as st

from components import analysis_view
from components.incident.ask_stream import dispatch_ask_stream
from config import SAMPLE_QUERIES, SEVERITY_OPTIONS
from state import session_state


def render_assistant(prefill: str | None) -> None:
    session_id = session_state.ensure_chat_session()
    st.markdown("### Agentic Incident Assistant")
    st.write(
        "Multi-turn chat with contextual query rewriting and live token streaming. "
        "The router chooses **SQL Metrics**, **Hybrid RAG**, or **Combined** execution."
    )

    thread = session_state.get_chat_thread()
    if thread:
        st.markdown("#### Chat Thread")
        for index, turn in enumerate(thread):
            analysis_view.render_chat_turn(
                turn,
                turn_index=index,
                expanded_latest=index == len(thread) - 1,
            )
    else:
        st.caption("No messages yet — ask a question to start this session.")

    default_query = prefill or st.session_state.get("last_query") or SAMPLE_QUERIES[2]
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
        min_severity = st.selectbox("Min severity", options=SEVERITY_OPTIONS, index=0)
    with col_c:
        system_name = st.text_input(
            "System filter (optional)",
            value=st.session_state.get("assistant_system", ""),
        )

    auto_ask = bool(st.session_state.pop("auto_ask", False))
    ask_clicked = st.button("Ask agent", type="primary", use_container_width=False)

    if not (ask_clicked or prefill or auto_ask):
        return

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

    turn = dispatch_ask_stream(cleaned=cleaned, payload=payload, session_id=session_id)
    if not turn:
        return

    session_state.append_chat_turn(turn)
    st.session_state["assistant_query_input"] = ""
    st.rerun()
