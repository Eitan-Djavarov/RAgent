"""Summary / root-cause / action-item blocks from API payloads."""

from __future__ import annotations

from typing import Any

import streamlit as st

from utils import formatting


def render_unsupported_claims(claims: list[Any] | None) -> None:
    cleaned = [str(item).strip() for item in (claims or []) if str(item).strip()]
    if not cleaned:
        return
    with st.expander(f"Unsupported claims ({len(cleaned)})", expanded=True):
        st.caption("These statements lacked direct backing in retrieved source chunks.")
        for index, claim in enumerate(cleaned, start=1):
            st.markdown(f"{index}. {claim}")


def render_summary_card(body: dict[str, Any]) -> None:
    st.markdown("#### Summary")
    st.info(body.get("summary") or body.get("answer") or "No summary returned.")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Root Cause")
        st.write(body.get("rootCause") or "—")
    with right:
        st.markdown("#### Action Items")
        st.write(body.get("actionItems") or "—")


def render_turn_metrics(body: dict[str, Any], *, latency_ms: float, cached: bool) -> None:
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
        formatting.cache_badge(cached)


def render_rewritten_query(
    rewritten: Any,
    original: Any,
    *,
    expanded: bool,
) -> None:
    if rewritten and original and str(rewritten).strip() != str(original).strip():
        with st.expander("Rewritten Standalone Query", expanded=expanded):
            st.code(str(rewritten), language="text")
            st.caption("Resolved from conversational context for routing, cache, retrieval, and SQL.")
    elif rewritten:
        with st.expander("Rewritten Standalone Query", expanded=False):
            st.code(str(rewritten), language="text")
            st.caption("Query was already self-contained.")
