"""Document upload form — inputs and ingest submission."""

from __future__ import annotations

import streamlit as st

from api import client as api_client
from components import analysis_view, data_tables
from config import UPLOAD_SEVERITY_OPTIONS


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
        severity = st.selectbox("Severity", options=UPLOAD_SEVERITY_OPTIONS, index=2)
        tags = st.text_input("Tags (comma-separated)", placeholder="radar, firmware, tracking")

    submit = st.button("Ingest document", type="primary", disabled=uploaded is None)

    if submit:
        if uploaded is None:
            st.warning("Choose a file first.")
        elif not system_name.strip():
            st.error("System Name is required.")
        else:
            resolved_title = title.strip() or uploaded.name.rsplit(".", 1)[0]
            files = {
                "file": (
                    uploaded.name,
                    uploaded.getvalue(),
                    uploaded.type or "application/octet-stream",
                ),
            }
            data = {
                "title": resolved_title,
                "system": system_name.strip(),
                "severity": severity,
                "subsystemTags": tags.strip(),
            }

            with st.spinner("Extracting, chunking, embedding, and indexing..."):
                ok, body = api_client.upload_document(files=files, data=data)

            if not ok or not isinstance(body, dict):
                st.error(f"Upload failed: {body}")
            else:
                st.session_state["last_upload_result"] = body
                st.session_state.pop("incidents_df", None)
                st.session_state.pop("documents_df", None)
                analysis_view.render_upload_success(body)

    elif "last_upload_result" in st.session_state:
        analysis_view.render_upload_success(st.session_state["last_upload_result"])

    st.divider()
    data_tables.render_document_repository()
