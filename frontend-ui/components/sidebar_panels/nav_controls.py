"""Sidebar navigation controls: session reset, samples, captions."""

from __future__ import annotations

import streamlit as st

from config import AI_URL, BACKEND_URL, SAMPLE_QUERIES
from state import session_state


def render_session_header() -> None:
    session_state.ensure_chat_session()
    st.markdown("## 🛰️ Incident Intelligence")
    st.caption("Agentic assistant for aerospace / defense incident analysis")
    st.caption(f"Session: `{st.session_state['session_id'][:8]}…`")


def render_session_actions() -> None:
    if st.button("New Chat / Reset Session", use_container_width=True):
        session_state.reset_chat_session()
        st.success("Started a new conversation session.")
        st.rerun()


def render_sample_queries() -> str | None:
    st.markdown("### Sample Queries")
    selected: str | None = None
    for query in SAMPLE_QUERIES:
        if st.button(query, key=f"sample_{hash(query)}", use_container_width=True):
            selected = query
    return selected


def render_endpoint_captions() -> None:
    st.caption(f"Backend: `{BACKEND_URL}`")
    st.caption(f"AI: `{AI_URL}`")
