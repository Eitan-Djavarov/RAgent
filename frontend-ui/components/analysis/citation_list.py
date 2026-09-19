"""Citation badges, metadata pills, and expandable source quotes."""

from __future__ import annotations

from typing import Any

import streamlit as st

from utils import formatting


def render_citations_list(
    citations: list[Any],
    *,
    expanded_first: bool = False,
    limit: int | None = None,
) -> None:
    if not citations:
        st.caption("No citations for this route.")
        return
    items = citations[:limit] if limit is not None else citations
    for fallback_index, citation in enumerate(items, start=1):
        if not isinstance(citation, dict):
            continue
        index = int(citation.get("citationIndex") or fallback_index)
        score = float(citation.get("score") or 0.0)
        doc_id = citation.get("docId") or citation.get("documentId") or "unknown"
        system = citation.get("system") or citation.get("systemName") or "—"
        severity = citation.get("severity") or "—"
        chunk = citation.get("chunkText") or ""
        badge = formatting.citation_index_badge(index)
        st.markdown(
            f"""
            <div style="margin:0.35rem 0 0.15rem 0;display:flex;align-items:center;gap:0.35rem;">
              {badge}
              <span style="font-weight:600;color:#134e4a;">
                {doc_id} · {system} · {severity} · similarity {score:.3f}
              </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander(
            f"[{index}] Source detail · {doc_id}",
            expanded=fallback_index == 1 and expanded_first,
        ):
            st.caption(f"System: {system} · Severity: {severity}")
            st.progress(min(max(score, 0.0), 1.0))
            st.write(chunk)


def render_citations_section(citations: list[Any], *, expanded_first: bool = False) -> None:
    st.markdown("#### Citations")
    st.caption("Inline markers like [1] / [2] in the answer map to these numbered sources.")
    render_citations_list(citations, expanded_first=expanded_first)
