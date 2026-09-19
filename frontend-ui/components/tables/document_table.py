"""Document list table display (column rename for labels only)."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_document_table(frame: pd.DataFrame) -> None:
    display = frame.copy()
    rename = {
        "id": "ID",
        "title": "Title",
        "system_name": "System",
        "severity": "Severity",
        "created_at": "Created Date",
    }
    for src, dst in rename.items():
        if src in display.columns:
            display = display.rename(columns={src: dst})

    show_cols = [
        col for col in ["Title", "System", "Severity", "ID", "Created Date"] if col in display.columns
    ]
    st.dataframe(display[show_cols], use_container_width=True, hide_index=True)
