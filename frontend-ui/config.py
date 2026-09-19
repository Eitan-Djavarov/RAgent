"""Environment configuration and static UI labels (no domain logic)."""

from __future__ import annotations

import os

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000").rstrip("/")
AI_URL = os.getenv("AI_URL", "http://localhost:8000").rstrip("/")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("UI_REQUEST_TIMEOUT", "120"))

SAMPLE_QUERIES = [
    "How many Critical incidents?",
    "List incidents by hardware component",
    "What caused the buffer overflow in the AESA radar during target tracking?",
    "How was the EO/IR gimbal drift mitigated during thermal transition?",
    "What were the symptoms of the UAV SATCOM link loss during EW jamming?",
    "How many critical incidents and what caused the UAV jamming failures?",
]

TOOL_BADGES = {
    "HYBRID_RAG": ("Hybrid RAG", "#2563eb"),
    "SQL_METRICS": ("SQL Metrics", "#059669"),
    "HYBRID_COMBINED": ("Combined", "#7c3aed"),
}

TAB_LABELS = [
    "Agentic Incident Assistant",
    "Incident Analytics & SQL Explorer",
    "Upload & Ingest Incident Documents",
]

SEVERITY_OPTIONS = ["", "Low", "Medium", "High", "Critical"]
UPLOAD_SEVERITY_OPTIONS = ["Low", "Medium", "High", "Critical"]

SQL_EXPLORER_OPTIONS = [
    "How many Critical incidents?",
    "How many High incidents?",
    "List incidents by hardware component",
    "Show incidents breakdown by severity",
]

PAGE_TITLE = "Incident Intelligence"
PAGE_ICON = "🛰️"
APP_TITLE = "Incident Intelligence Platform"
APP_CAPTION = "Streamlit console for agentic RAG, SQL metrics, document ingest, and analytics"

ENDPOINTS = {
    "backend_health": f"{BACKEND_URL}/api/health",
    "backend_ready": f"{BACKEND_URL}/api/health/ready",
    "ai_health": f"{AI_URL}/health",
    "qdrant_ready": f"{QDRANT_URL}/readyz",
    "qdrant_health": f"{QDRANT_URL}/healthz",
    "incidents": f"{BACKEND_URL}/api/incidents",
    "ask": f"{BACKEND_URL}/api/incidents/ask",
    "ask_stream": f"{BACKEND_URL}/api/incidents/ask/stream",
    "upload": f"{BACKEND_URL}/api/incidents/upload",
    "incident_delete": f"{BACKEND_URL}/api/incidents/{{id}}",
    "cache_clear": f"{AI_URL}/api/v1/cache",
    "session_clear": f"{AI_URL}/api/v1/sessions/{{id}}",
}
