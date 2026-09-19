"""Raw Streamlit session keys and UI buffers (no domain rules)."""

from __future__ import annotations

import uuid
from typing import Any

import streamlit as st

from api import client as api_client


def ensure_chat_session() -> str:
    if "session_id" not in st.session_state or not st.session_state["session_id"]:
        st.session_state["session_id"] = str(uuid.uuid4())
    if "chat_thread" not in st.session_state:
        st.session_state["chat_thread"] = []
    return str(st.session_state["session_id"])


def reset_chat_session() -> None:
    old_session = st.session_state.get("session_id")
    if old_session:
        api_client.clear_session(str(old_session))
    st.session_state["session_id"] = str(uuid.uuid4())
    st.session_state["chat_thread"] = []
    st.session_state.pop("assistant_query_input", None)
    st.session_state.pop("last_query", None)


def get_chat_thread() -> list[dict[str, Any]]:
    return list(st.session_state.get("chat_thread") or [])


def append_chat_turn(turn: dict[str, Any]) -> None:
    st.session_state.setdefault("chat_thread", []).append(turn)


def set_loading(flag: bool) -> None:
    st.session_state["ui_loading"] = flag


def set_error(message: str | None) -> None:
    if message:
        st.session_state["ui_error"] = message
    else:
        st.session_state.pop("ui_error", None)


def pop_active_tab() -> str | None:
    return st.session_state.pop("active_tab", None)


def set_active_tab(label: str) -> None:
    st.session_state["active_tab"] = label
