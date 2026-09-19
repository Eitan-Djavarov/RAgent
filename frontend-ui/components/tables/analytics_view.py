"""Analytics workspace orchestration."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.tables.analytics_charts import (
    render_incident_charts,
    render_incident_metrics,
    render_live_incident_table,
)
from components.tables.frame_loader import incidents_frame_from_api
from components.tables.sql_explorer import render_sql_explorer


def render_analytics() -> None:
    st.markdown("### Incident Analytics & SQL Explorer")
    st.write("Live charts and table from `GET /api/incidents`, plus quick SQL-style asks.")

    refresh = st.button("Refresh incident data", type="secondary")
    if refresh or "incidents_df" not in st.session_state:
        with st.spinner("Loading incidents from backend..."):
            st.session_state["incidents_df"] = incidents_frame_from_api()

    frame: pd.DataFrame = st.session_state.get("incidents_df", pd.DataFrame())
    if frame.empty:
        st.warning("No incidents returned. Seed data with `scripts/seed_and_verify.py` first.")
    else:
        render_incident_metrics(frame)
        render_incident_charts(frame)
        render_live_incident_table(frame)

    render_sql_explorer()
