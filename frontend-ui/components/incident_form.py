"""Backward-compatible facade for incident form entrypoints."""

from components.incident.create_form import render_assistant
from components.incident.file_upload_form import render_upload

__all__ = ["render_assistant", "render_upload"]
