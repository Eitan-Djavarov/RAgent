"""Tabular SQL outputs and query inspection expanders."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def render_sql_result_view(
    sql_result: dict[str, Any] | None,
    *,
    expanded: bool = False,
) -> None:
    if not isinstance(sql_result, dict) or sql_result.get("rows") is None:
        return
    with st.expander("SQL query result", expanded=expanded):
        st.code(sql_result.get("query") or "", language="sql")
        st.caption(sql_result.get("interpretation") or "")
        rows = sql_result.get("rows") or []
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_sql_explorer_result(body: dict[str, Any]) -> None:
    from utils import formatting

    formatting.tool_badge(str(body.get("toolUsed") or "SQL_METRICS"))
    st.write(body.get("summary") or body.get("answer"))
    sql_result = body.get("sqlQueryResult") or {}
    if sql_result.get("query"):
        st.code(sql_result["query"], language="sql")
    rows = sql_result.get("rows") or []
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
