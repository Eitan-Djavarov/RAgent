"""Upload success card and handoff control to Assistant tab."""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_upload_success(body: dict[str, Any]) -> None:
    document_id = body.get("documentId") or "—"
    chunk_count = body.get("chunkCount") or body.get("chunksCount") or 0
    status = body.get("status") or ("indexed" if body.get("success") else "unknown")
    title = body.get("title") or "Uploaded document"
    system_name = body.get("systemName") or ""

    st.success("Document ingested successfully.")
    st.markdown(
        f"""
        <div style="
            padding:1rem 1.15rem;margin:0.75rem 0 1rem 0;border-radius:0.85rem;
            background:linear-gradient(135deg, rgba(37,99,235,0.08), rgba(14,165,233,0.06));
            border:1px solid rgba(37,99,235,0.25);">
          <div style="font-weight:700;color:#0f172a;margin-bottom:0.35rem;">{title}</div>
          <div style="color:#334155;font-size:0.92rem;">
            <strong>documentId:</strong> <code>{document_id}</code><br/>
            <strong>chunks:</strong> {chunk_count} &nbsp;·&nbsp;
            <strong>status:</strong> {status}
            {" &nbsp;·&nbsp; <strong>system:</strong> " + system_name if system_name else ""}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = st.columns(3)
    metrics[0].metric("Document ID", str(document_id)[:8] + "…")
    metrics[1].metric("Chunks indexed", int(chunk_count))
    metrics[2].metric("Status", str(status))

    if st.button("Query this document in Assistant", type="secondary"):
        st.session_state["assistant_query"] = (
            f"Summarize root cause and recommended mitigations for the uploaded incident "
            f"document '{title}' (documentId={document_id})."
        )
        st.session_state["assistant_system"] = system_name
        st.session_state["auto_ask"] = True
        st.session_state["active_tab"] = "Agentic Incident Assistant"
        st.rerun()
