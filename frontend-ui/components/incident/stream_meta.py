"""Render SSE metadata panel (route badge, rewritten query, citations)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from components import analysis_view
from utils import formatting


def render_stream_metadata(event: dict[str, Any], *, cleaned: str) -> None:
    formatting.tool_badge(str(event.get("toolUsed") or "HYBRID_RAG"))
    if event.get("cached"):
        formatting.cache_hit_banner(0.0)
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
    analysis_view.render_citations_list(citations, expanded_first=True, limit=5)
