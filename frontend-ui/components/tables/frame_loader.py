"""Bind GET /api/incidents list into a display DataFrame (column rename only)."""

from __future__ import annotations

import pandas as pd

from api import client as api_client


def incidents_frame_from_api() -> pd.DataFrame:
    body = api_client.list_incidents()
    if not body:
        return pd.DataFrame()
    frame = pd.DataFrame(body)
    if frame.empty:
        return frame
    rename = {
        "systemName": "system_name",
        "createdAt": "created_at",
        "indexedAt": "indexed_at",
    }
    frame = frame.rename(columns=rename)
    if "severity" in frame.columns:
        frame["severity"] = frame["severity"].astype(str).str.title()
    return frame
