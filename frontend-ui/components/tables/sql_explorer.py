"""SQL Explorer bar — selectbox + ask dispatch (display of API result)."""

from __future__ import annotations

import requests
import streamlit as st

from api import client as api_client
from components.analysis.sql_result_view import render_sql_explorer_result
from config import SQL_EXPLORER_OPTIONS
from utils import formatting


def render_sql_explorer() -> None:
    st.markdown("#### SQL Explorer (via agentic ask)")
    sql_query = st.selectbox("Metric question", options=SQL_EXPLORER_OPTIONS)
    if not st.button("Run SQL-style ask", type="primary"):
        return
    with st.spinner("Executing SQL metrics route..."):
        try:
            response = api_client.ask_incident({"queryText": sql_query, "topK": 3})
            if not response.ok:
                formatting.render_api_guard_error(api_client.parse_error_response(response))
                return
            body = response.json()
        except requests.RequestException as exc:
            st.error(f"SQL explorer failed: {exc}")
            return
    if not isinstance(body, dict):
        st.error("SQL explorer returned an unexpected payload.")
        return
    render_sql_explorer_result(body)
