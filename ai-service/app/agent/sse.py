from __future__ import annotations

import json
from typing import Any


def format_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"
