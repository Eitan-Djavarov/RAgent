"""Download actions for investigation reports (Markdown / JSON)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from utils import formatting


def render_export_investigation_report(
    turn: dict[str, Any],
    *,
    key_prefix: str,
) -> None:
    payload = formatting.investigation_report_payload(turn)
    md_name, json_name = formatting.investigation_report_filenames(payload)
    markdown_report = formatting.investigation_report_markdown(payload)
    json_report = formatting.dump_json(payload)

    st.markdown("#### Export Investigation Report")
    st.caption("Download a structured Markdown brief or machine-readable JSON summary for this turn.")
    col_md, col_json = st.columns(2)
    with col_md:
        st.download_button(
            label="Download Markdown Report (.md)",
            data=markdown_report.encode("utf-8"),
            file_name=md_name,
            mime="text/markdown",
            key=f"{key_prefix}_md",
            use_container_width=True,
        )
    with col_json:
        st.download_button(
            label="Download JSON Summary (.json)",
            data=json_report.encode("utf-8"),
            file_name=json_name,
            mime="application/json",
            key=f"{key_prefix}_json",
            use_container_width=True,
        )
