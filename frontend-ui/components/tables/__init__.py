"""Table / analytics presentational widgets."""

from components.tables.analytics_view import render_analytics
from components.tables.document_repository import render_document_repository
from components.tables.frame_loader import incidents_frame_from_api

__all__ = [
    "incidents_frame_from_api",
    "render_analytics",
    "render_document_repository",
]
