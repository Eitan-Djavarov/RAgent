"""Analytics metrics and charts from the server incident list."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st


def render_incident_metrics(frame: pd.DataFrame) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Total incidents", len(frame))
    if "severity" in frame.columns:
        critical = int((frame["severity"].str.lower() == "critical").sum())
        c2.metric("Critical", critical)
    if "system_name" in frame.columns:
        c3.metric("Systems", frame["system_name"].nunique())


def render_incident_charts(frame: pd.DataFrame) -> None:
    chart_left, chart_right = st.columns(2)
    with chart_left:
        if "severity" in frame.columns:
            severity_counts = (
                frame["severity"].value_counts().rename_axis("severity").reset_index(name="count")
            )
            fig = px.bar(
                severity_counts,
                x="severity",
                y="count",
                color="severity",
                title="Incidents by Severity",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
    with chart_right:
        if "system_name" in frame.columns:
            system_counts = (
                frame["system_name"].value_counts().rename_axis("component").reset_index(name="count")
            )
            fig = px.pie(
                system_counts,
                names="component",
                values="count",
                title="Incidents by Component / System",
                hole=0.35,
            )
            fig.update_layout(margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)


def render_live_incident_table(frame: pd.DataFrame) -> None:
    st.markdown("#### Live incident table")
    display_cols = [
        col
        for col in ["id", "title", "system_name", "severity", "created_at", "indexed_at"]
        if col in frame.columns
    ]
    st.dataframe(
        frame[display_cols] if display_cols else frame,
        use_container_width=True,
        hide_index=True,
    )
