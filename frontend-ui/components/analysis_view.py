"""Backward-compatible facade for analysis presentational widgets."""

from components.analysis import (
    render_chat_turn,
    render_citations_list,
    render_export_investigation_report,
    render_unsupported_claims,
    render_upload_success,
)

__all__ = [
    "render_chat_turn",
    "render_citations_list",
    "render_export_investigation_report",
    "render_unsupported_claims",
    "render_upload_success",
]
