"""Badge and pill HTML helpers (display only)."""

from __future__ import annotations

import streamlit as st

from config import TOOL_BADGES

_FAITHFULNESS_DISPLAY_CUTOFF = 0.8


def status_pill(label: str, ok: bool) -> None:
    color = "#16a34a" if ok else "#dc2626"
    text = "UP" if ok else "DOWN"
    st.markdown(
        f"""
        <div style="
            display:flex;justify-content:space-between;align-items:center;
            padding:0.55rem 0.75rem;margin-bottom:0.45rem;border-radius:0.65rem;
            background:rgba(15,23,42,0.04);border:1px solid rgba(148,163,184,0.35);">
          <span style="font-weight:600;color:#0f172a;">{label}</span>
          <span style="
              font-size:0.75rem;font-weight:700;letter-spacing:0.04em;
              color:white;background:{color};padding:0.2rem 0.55rem;border-radius:999px;">
            {text}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def tool_badge(tool_used: str | None) -> None:
    key = (tool_used or "HYBRID_RAG").upper()
    label, color = TOOL_BADGES.get(key, (key, "#64748b"))
    st.markdown(
        f"""
        <div style="margin:0.4rem 0 1rem 0;">
          <span style="
              display:inline-block;padding:0.35rem 0.8rem;border-radius:999px;
              background:{color};color:white;font-weight:700;font-size:0.85rem;
              letter-spacing:0.03em;">
            Route · {label}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def cache_badge(cached: bool) -> None:
    if cached:
        label, color, bg = "Cache Hit", "#047857", "rgba(16,185,129,0.12)"
    else:
        label, color, bg = "Cache Miss", "#b45309", "rgba(245,158,11,0.12)"
    st.markdown(
        f"""
        <div style="
            display:inline-flex;align-items:center;gap:0.4rem;
            padding:0.35rem 0.75rem;border-radius:999px;margin:0.2rem 0 0.6rem 0;
            background:{bg};border:1px solid {color};color:{color};
            font-weight:700;font-size:0.82rem;letter-spacing:0.03em;">
          {label}
        </div>
        """,
        unsafe_allow_html=True,
    )


def faithfulness_badge(
    faithfulness_score: float | None,
    is_grounded: bool | None,
) -> None:
    if faithfulness_score is None and is_grounded is None:
        return
    score = float(faithfulness_score) if faithfulness_score is not None else 0.0
    pct = int(round(score * 100))
    if is_grounded is None:
        grounded = score >= _FAITHFULNESS_DISPLAY_CUTOFF
    else:
        grounded = bool(is_grounded)
    if grounded:
        label = f"Faithfulness: {pct}% (Verified Grounded)"
        color, bg = "#047857", "rgba(16,185,129,0.12)"
    else:
        label = f"Faithfulness: {pct}% (Low Grounding / Review Claims)"
        color, bg = (
            ("#b91c1c", "rgba(239,68,68,0.12)")
            if pct < 50
            else ("#c2410c", "rgba(249,115,22,0.14)")
        )
    st.markdown(
        f"""
        <div style="
            display:inline-flex;align-items:center;gap:0.4rem;
            padding:0.35rem 0.75rem;border-radius:999px;margin:0.2rem 0.4rem 0.6rem 0;
            background:{bg};border:1px solid {color};color:{color};
            font-weight:700;font-size:0.82rem;letter-spacing:0.02em;">
          {label}
        </div>
        """,
        unsafe_allow_html=True,
    )


def citation_index_badge(index: int) -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f"min-width:1.6rem;height:1.6rem;margin-right:0.45rem;border-radius:999px;"
        f"background:#0f766e;color:white;font-weight:700;font-size:0.78rem;"
        f'letter-spacing:0.02em;">[{int(index)}]</span>'
    )
