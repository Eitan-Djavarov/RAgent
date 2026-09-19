"""System health status indicators for the sidebar."""

from __future__ import annotations

import streamlit as st

from api import client as api_client
from utils import formatting


def render_health_panel() -> None:
    st.markdown("### System Health")
    health = api_client.check_health().as_dict()
    formatting.status_pill(".NET Backend", health["backend"]["ok"])
    formatting.status_pill("FastAPI AI", health["ai"]["ok"])
    formatting.status_pill("PostgreSQL", health["postgres"]["ok"])
    formatting.status_pill("Qdrant", health["qdrant"]["ok"])
    formatting.status_pill("Redis Cache", health["redis"]["ok"])

    if st.button("Refresh health", use_container_width=True):
        st.rerun()

    if st.button("Clear Cache", use_container_width=True, type="secondary"):
        ok, body = api_client.clear_cache()
        if ok:
            deleted = body.get("deletedKeys") if isinstance(body, dict) else "?"
            st.success(f"Semantic cache cleared ({deleted} keys).")
        else:
            st.error(f"Clear cache failed: {body}")
