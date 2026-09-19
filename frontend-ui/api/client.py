"""Lean HTTP/SSE client — serialization, errors, timeouts only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import requests

from api.models import ApiHttpError, HealthStatus
from config import ENDPOINTS, REQUEST_TIMEOUT


def parse_error_response(response: requests.Response) -> ApiHttpError:
    detail = f"HTTP {response.status_code}"
    error_code = None
    reason = None
    retry_after = None
    raw_body: Any = response.text[:800]
    try:
        payload = response.json()
        raw_body = payload
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("title") or detail)
            error_code = payload.get("errorCode") or payload.get("error_code")
            reason = payload.get("reason")
            retry_val = payload.get("retryAfterSeconds")
            if isinstance(retry_val, int):
                retry_after = retry_val
    except ValueError:
        detail = f"HTTP {response.status_code}: {response.text[:400]}"

    header_retry = response.headers.get("Retry-After")
    if retry_after is None and header_retry and header_retry.isdigit():
        retry_after = int(header_retry)

    return ApiHttpError(
        status_code=response.status_code,
        detail=detail,
        error_code=str(error_code) if error_code else None,
        reason=str(reason) if reason else None,
        retry_after=retry_after,
        raw_body=raw_body,
    )


def get_json(url: str, timeout: float = 5.0) -> tuple[bool, Any]:
    try:
        response = requests.get(url, timeout=timeout)
        if response.ok:
            try:
                return True, response.json()
            except ValueError:
                return True, response.text
        return False, f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[bool, Any]:
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        if response.ok:
            return True, response.json()
        return False, f"HTTP {response.status_code}: {response.text[:400]}"
    except requests.RequestException as exc:
        return False, str(exc)


def post_json_raw(
    url: str,
    payload: dict[str, Any],
    timeout: float = REQUEST_TIMEOUT,
) -> requests.Response:
    return requests.post(url, json=payload, timeout=timeout)


def delete_json(url: str, timeout: float = 15.0) -> tuple[bool, Any]:
    try:
        response = requests.delete(url, timeout=timeout)
        if response.ok:
            try:
                return True, response.json()
            except ValueError:
                return True, response.text
        return False, f"HTTP {response.status_code}: {response.text[:400]}"
    except requests.RequestException as exc:
        return False, str(exc)


def delete_raw(url: str, timeout: float = REQUEST_TIMEOUT) -> requests.Response:
    return requests.delete(url, timeout=timeout)


def post_multipart(
    url: str,
    *,
    files: dict[str, Any],
    data: dict[str, str],
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[bool, Any]:
    try:
        response = requests.post(url, files=files, data=data, timeout=timeout)
        if response.ok:
            return True, response.json()
        return False, f"HTTP {response.status_code}: {response.text[:400]}"
    except requests.RequestException as exc:
        return False, str(exc)


def iter_sse_events(
    url: str,
    payload: dict[str, Any],
    timeout: float = REQUEST_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed SSE JSON payloads from a text/event-stream response."""
    with requests.post(url, json=payload, stream=True, timeout=timeout, headers=headers) as response:
        if not response.ok:
            raise parse_error_response(response)
        event_data_lines: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            line = raw_line.rstrip("\r")
            if line == "":
                if not event_data_lines:
                    continue
                data = "\n".join(event_data_lines).strip()
                event_data_lines = []
                if not data:
                    continue
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                event_data_lines.append(line[5:].lstrip())
        if event_data_lines:
            data = "\n".join(event_data_lines).strip()
            if data:
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    return


def check_health() -> HealthStatus:
    """Map health/ready endpoints into display flags (no business decisions)."""
    backend_ok, backend_body = get_json(ENDPOINTS["backend_health"])
    ready_ok, ready_body = get_json(ENDPOINTS["backend_ready"])
    ai_ok, ai_body = get_json(ENDPOINTS["ai_health"])
    qdrant_ok, qdrant_body = get_json(ENDPOINTS["qdrant_ready"])
    if not qdrant_ok:
        qdrant_ok, qdrant_body = get_json(ENDPOINTS["qdrant_health"])

    postgres_ok = False
    redis_ok = False
    if ready_ok and isinstance(ready_body, dict):
        checks = ready_body.get("checks") or {}
        postgres_ok = bool(checks.get("postgres"))
        if not ai_ok:
            ai_ok = bool(checks.get("aiService"))

    if ai_ok and isinstance(ai_body, dict):
        details = ai_body.get("details") or {}
        redis_ok = str(details.get("redis", "")).lower() in {"up", "true", "ok", "healthy"}

    return HealthStatus(
        backend={"ok": backend_ok, "detail": backend_body},
        ai={"ok": ai_ok, "detail": ai_body},
        postgres={"ok": postgres_ok, "detail": ready_body if ready_ok else "unreachable"},
        qdrant={"ok": qdrant_ok, "detail": qdrant_body},
        redis={"ok": redis_ok, "detail": ai_body if ai_ok else "unreachable"},
    )


def list_incidents() -> list[dict[str, Any]]:
    ok, body = get_json(ENDPOINTS["incidents"], timeout=15.0)
    if not ok or not isinstance(body, list):
        return []
    return [item for item in body if isinstance(item, dict)]


def clear_cache() -> tuple[bool, Any]:
    return delete_json(ENDPOINTS["cache_clear"])


def clear_session(session_id: str) -> tuple[bool, Any]:
    return delete_json(ENDPOINTS["session_clear"].format(id=session_id))


def ask_incident(payload: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> requests.Response:
    return post_json_raw(ENDPOINTS["ask"], payload, timeout=timeout)


def delete_incident(document_id: str) -> requests.Response:
    return delete_raw(ENDPOINTS["incident_delete"].format(id=document_id))


def upload_document(
    *,
    files: dict[str, Any],
    data: dict[str, str],
    timeout: float | None = None,
) -> tuple[bool, Any]:
    return post_multipart(
        ENDPOINTS["upload"],
        files=files,
        data=data,
        timeout=timeout if timeout is not None else max(REQUEST_TIMEOUT, 180.0),
    )
