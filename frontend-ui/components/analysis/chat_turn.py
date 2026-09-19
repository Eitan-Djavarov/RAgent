"""Compose a single chat turn from analysis sub-widgets."""

from __future__ import annotations

from typing import Any

import streamlit as st

from components.analysis import citation_list, export_bar, sql_result_view, summary_card
from utils import formatting


def render_chat_turn(
    turn: dict[str, Any],
    *,
    turn_index: int,
    expanded_latest: bool = False,
) -> None:
    with st.chat_message("user"):
        st.markdown(turn.get("user") or "")

    with st.chat_message("assistant"):
        body = turn.get("response") or {}
        tool_used = body.get("toolUsed") or body.get("retrievalMode")
        formatting.tool_badge(str(tool_used) if tool_used else None)
        formatting.faithfulness_badge(
            body.get("faithfulnessScore"),
            body.get("isGrounded"),
        )

        cached = bool(body.get("cached"))
        latency_ms = float(body.get("latencyMs") or 0)
        if cached:
            formatting.cache_hit_banner(latency_ms)

        rewritten = body.get("rewrittenQuery") or turn.get("rewritten_query")
        original = body.get("originalQuery") or turn.get("user")
        summary_card.render_rewritten_query(
            rewritten, original, expanded=expanded_latest
        )
        summary_card.render_turn_metrics(body, latency_ms=latency_ms, cached=cached)
        summary_card.render_unsupported_claims(body.get("unsupportedClaims"))
        summary_card.render_summary_card(body)
        sql_result_view.render_sql_result_view(
            body.get("sqlQueryResult"),
            expanded=tool_used == "SQL_METRICS",
        )
        citation_list.render_citations_section(
            body.get("citations") or [],
            expanded_first=expanded_latest,
        )

        session_token = formatting.safe_filename_token(
            str(
                turn.get("session_id")
                or body.get("sessionId")
                or st.session_state.get("session_id")
                or "session"
            )
        )
        export_bar.render_export_investigation_report(
            turn,
            key_prefix=f"export_{session_token}_{turn_index}",
        )
