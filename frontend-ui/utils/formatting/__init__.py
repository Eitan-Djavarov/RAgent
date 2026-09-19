"""Visual formatting helpers — re-export facade."""

from utils.formatting.badges import (
    cache_badge,
    citation_index_badge,
    faithfulness_badge,
    status_pill,
    tool_badge,
)
from utils.formatting.banners import (
    cache_hit_banner,
    rate_limit_warning,
    render_api_guard_error,
    security_warning_banner,
)
from utils.formatting.report_markdown import investigation_report_markdown
from utils.formatting.report_payload import (
    dump_json,
    investigation_report_filenames,
    investigation_report_payload,
    safe_filename_token,
    turn_timestamp_iso,
)
from utils.formatting.theme import apply_app_theme

__all__ = [
    "apply_app_theme",
    "cache_badge",
    "cache_hit_banner",
    "citation_index_badge",
    "dump_json",
    "faithfulness_badge",
    "investigation_report_filenames",
    "investigation_report_markdown",
    "investigation_report_payload",
    "rate_limit_warning",
    "render_api_guard_error",
    "safe_filename_token",
    "security_warning_banner",
    "status_pill",
    "tool_badge",
    "turn_timestamp_iso",
]
