"""App-level Streamlit theme CSS."""

from __future__ import annotations

import streamlit as st


def apply_app_theme() -> None:
    st.markdown(
        """
        <style>
          .block-container { padding-top: 1.2rem; }
          div[data-testid="stSidebar"] { background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); }
        </style>
        """,
        unsafe_allow_html=True,
    )
