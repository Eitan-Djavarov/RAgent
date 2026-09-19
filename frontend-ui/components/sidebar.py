"""Sidebar — compose health indicators and navigation controls."""

from __future__ import annotations

import streamlit as st

from components.sidebar_panels.health_panel import render_health_panel
from components.sidebar_panels.nav_controls import (
    render_endpoint_captions,
    render_sample_queries,
    render_session_actions,
    render_session_header,
)


def render_sidebar() -> str | None:
    with st.sidebar:
        render_session_header()
        st.divider()
        render_health_panel()
        render_session_actions()
        st.divider()
        selected = render_sample_queries()
        st.divider()
        render_endpoint_captions()
    return selected
