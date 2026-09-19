"""Document repository table and delete controls."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.tables.document_delete import render_delete_controls
from components.tables.document_table import render_document_table
from components.tables.frame_loader import incidents_frame_from_api


def render_document_repository() -> None:
    st.markdown("### Document Repository & Management")
    st.write(
        "Active indexed incident documents. Deleting a document removes it from "
        "PostgreSQL, Qdrant vectors, and related semantic-cache entries."
    )

    refresh = st.button("Refresh document list", key="refresh_documents")
    if refresh or "documents_df" not in st.session_state:
        with st.spinner("Loading documents..."):
            st.session_state["documents_df"] = incidents_frame_from_api()

    frame: pd.DataFrame = st.session_state.get("documents_df", pd.DataFrame())
    if frame.empty:
        st.info("No documents indexed yet. Upload a file above to get started.")
        return

    render_document_table(frame)
    render_delete_controls(frame)
