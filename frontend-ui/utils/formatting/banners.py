"""Warning / status banners for API guard responses."""

from __future__ import annotations

import streamlit as st

from api.models import ApiHttpError


def cache_hit_banner(latency_ms: float) -> None:
    st.markdown(
        f"""
        <div style="
            padding:0.85rem 1rem;margin:0.2rem 0 1rem 0;border-radius:0.75rem;
            background:linear-gradient(90deg, rgba(16,185,129,0.16), rgba(45,212,191,0.08));
            border:1px solid rgba(5,150,105,0.35);color:#065f46;">
          <strong>Semantic Cache Hit</strong> — response served instantly from Redis
          in <strong>{latency_ms:.1f} ms</strong> (cosine / exact match).
        </div>
        """,
        unsafe_allow_html=True,
    )


def rate_limit_warning(detail: str, retry_after: int | None) -> None:
    seconds = retry_after if retry_after and retry_after > 0 else 60
    st.markdown(
        f"""
        <div style="
            padding:0.95rem 1.1rem;margin:0.4rem 0 1rem 0;border-radius:0.8rem;
            background:linear-gradient(90deg, rgba(245,158,11,0.18), rgba(251,191,36,0.08));
            border:1px solid rgba(217,119,6,0.45);color:#92400e;">
          <strong>Rate limit reached</strong><br/>
          {detail}<br/>
          <span style="font-size:0.92rem;">Please wait about <strong>{seconds}s</strong> before retrying.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.warning(f"Retry countdown: ~{seconds} seconds")


def security_warning_banner(detail: str, reason: str | None = None) -> None:
    reason_line = (
        f"<br/><span style='font-size:0.9rem;'>Flag: <code>{reason}</code></span>"
        if reason
        else ""
    )
    st.markdown(
        f"""
        <div style="
            padding:0.95rem 1.1rem;margin:0.4rem 0 1rem 0;border-radius:0.8rem;
            background:linear-gradient(90deg, rgba(239,68,68,0.16), rgba(249,115,22,0.10));
            border:1px solid rgba(220,38,38,0.45);color:#7f1d1d;">
          <strong>Security Warning</strong> — query blocked by input guardrails.<br/>
          {detail}{reason_line}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_api_guard_error(exc: ApiHttpError) -> None:
    if exc.status_code == 429 or (exc.error_code or "").upper() == "RATE_LIMITED":
        rate_limit_warning(exc.detail, exc.retry_after)
        return
    if exc.status_code == 400 or (exc.error_code or "").upper() == "SECURITY_VIOLATION":
        security_warning_banner(exc.detail, exc.reason or exc.error_code)
        return
    st.error(f"Request failed ({exc.status_code}): {exc.detail}")
