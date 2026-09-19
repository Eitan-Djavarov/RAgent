"""Streamlit entry — page config then delegate to modular main."""

from __future__ import annotations

import streamlit as st

from config import PAGE_ICON, PAGE_TITLE

st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

from main import main  # noqa: E402

main()
