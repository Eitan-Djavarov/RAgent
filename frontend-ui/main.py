"""Entry point — routing, view composition, layout, and theme."""

from __future__ import annotations

import streamlit as st

from components import data_tables, incident_form, sidebar
from config import APP_CAPTION, APP_TITLE, PAGE_ICON, PAGE_TITLE, TAB_LABELS
from utils import formatting


def main() -> None:
    formatting.apply_app_theme()
    st.title(APP_TITLE)
    st.caption(APP_CAPTION)

    prefill = sidebar.render_sidebar()
    forced = st.session_state.pop("active_tab", None)
    if forced in TAB_LABELS:
        st.session_state["ui_tab"] = forced
    selected = st.radio(
        "Workspace",
        options=TAB_LABELS,
        horizontal=True,
        label_visibility="collapsed",
        key="ui_tab",
    )

    if selected == TAB_LABELS[0]:
        incident_form.render_assistant(prefill)
    elif selected == TAB_LABELS[1]:
        data_tables.render_analytics()
    else:
        incident_form.render_upload()


def run() -> None:
    """Invoke after Streamlit page config is set (see app.py)."""
    main()


if __name__ == "__main__":
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    main()
