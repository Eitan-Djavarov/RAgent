"""Document delete selectbox / confirm / API dispatch."""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests
import streamlit as st

from api import client as api_client
from utils import formatting


def render_delete_controls(frame: pd.DataFrame) -> None:
    options: list[tuple[str, str]] = []
    for _, row in frame.iterrows():
        doc_id = str(row.get("id") or "")
        title = str(row.get("title") or "Untitled")
        if doc_id:
            options.append((f"{title} ({doc_id[:8]}…)", doc_id))

    if not options:
        return

    labels = [label for label, _ in options]
    selected_label = st.selectbox("Select document to delete", options=labels, key="delete_doc_select")
    selected_id = next(doc_id for label, doc_id in options if label == selected_label)

    confirm = st.checkbox(
        "I understand this permanently deletes the document from Postgres, Qdrant, and cache.",
        key="delete_doc_confirm",
    )
    if st.button("Delete Document", type="primary", disabled=not confirm, key="delete_doc_btn"):
        _delete_document(selected_id)


def _delete_document(selected_id: str) -> None:
    with st.spinner("Cascade deleting document..."):
        try:
            response = api_client.delete_incident(selected_id)
            if response.status_code == 404:
                st.warning("Document was not found (may already be deleted).")
            elif not response.ok:
                formatting.render_api_guard_error(api_client.parse_error_response(response))
                return
            else:
                body: dict[str, Any] = response.json()
                st.success(
                    f"Deleted `{selected_id}` — "
                    f"vectors={body.get('vectorsDeleted', 0)}, "
                    f"cache={body.get('cacheEntriesInvalidated', 0)}."
                )
                st.toast("Document deleted", icon="🗑️")
        except requests.RequestException as exc:
            st.error(f"Delete failed: {exc}")
            return

    st.session_state.pop("documents_df", None)
    st.session_state.pop("incidents_df", None)
    st.session_state.pop("last_upload_result", None)
    st.rerun()
