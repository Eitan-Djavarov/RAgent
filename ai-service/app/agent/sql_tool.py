from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings

logger = logging.getLogger(__name__)

_SEVERITY_ALIASES = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "med": "Medium",
    "low": "Low",
}


@dataclass(slots=True)
class SqlToolResult:
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    interpretation: str


class ReadOnlyIncidentSqlTool:
    """
    Read-only SQL tool over the techdoc.incidents table.

    Only parameterized SELECT templates are executed — never arbitrary SQL.
    """

    def __init__(self, settings: Settings) -> None:
        self._dsn = (
            f"host={settings.postgres_host} "
            f"port={settings.postgres_port} "
            f"dbname={settings.postgres_db} "
            f"user={settings.postgres_user} "
            f"password={settings.postgres_password}"
        )

    async def run(self, natural_language_query: str) -> SqlToolResult:
        plan = self._plan_query(natural_language_query)
        rows = await self._fetch(plan.sql, plan.params)
        columns = list(rows[0].keys()) if rows else plan.expected_columns
        interpretation = self._interpret(plan.kind, rows, natural_language_query)
        return SqlToolResult(
            sql=plan.sql_display,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            interpretation=interpretation,
        )

    async def _fetch(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                self._dsn,
                row_factory=dict_row,
                autocommit=True,
            ) as conn:
                async with conn.cursor() as cur:
                    # Defense-in-depth: refuse anything that is not a single SELECT.
                    normalized = " ".join(sql.strip().split()).lower()
                    if not normalized.startswith("select"):
                        raise ValueError("Only SELECT statements are permitted.")
                    if any(
                        token in normalized
                        for token in (
                            " insert ",
                            " update ",
                            " delete ",
                            " drop ",
                            " alter ",
                            " truncate ",
                            " create ",
                            " grant ",
                            ";",
                        )
                    ):
                        raise ValueError("Refusing non read-only SQL.")
                    await cur.execute(sql, params)
                    records = await cur.fetchall()
                    return [dict(record) for record in records]
        except Exception:
            logger.exception("Read-only SQL tool query failed")
            raise

    @dataclass(slots=True)
    class _Plan:
        kind: str
        sql: str
        sql_display: str
        params: dict[str, Any]
        expected_columns: list[str]

    def _plan_query(self, query: str) -> _Plan:
        text = query.lower()
        severity = self._extract_severity(text)
        system_name = self._extract_system_name(query)

        if "by severity" in text or "breakdown" in text and "severity" in text:
            sql = """
                SELECT severity, COUNT(*)::int AS incident_count
                FROM incidents
                GROUP BY severity
                ORDER BY incident_count DESC
            """
            return self._Plan(
                kind="by_severity",
                sql=sql,
                sql_display=" ".join(sql.split()),
                params={},
                expected_columns=["severity", "incident_count"],
            )

        if any(
            phrase in text
            for phrase in (
                "by system",
                "by hardware",
                "by component",
                "group by system",
                "list incidents by",
            )
        ):
            sql = """
                SELECT system_name, COUNT(*)::int AS incident_count
                FROM incidents
                GROUP BY system_name
                ORDER BY incident_count DESC, system_name ASC
            """
            return self._Plan(
                kind="by_system",
                sql=sql,
                sql_display=" ".join(sql.split()),
                params={},
                expected_columns=["system_name", "incident_count"],
            )

        if severity is not None and any(
            phrase in text for phrase in ("how many", "count", "number of", "total")
        ):
            sql = """
                SELECT COUNT(*)::int AS incident_count
                FROM incidents
                WHERE severity = %(severity)s
            """
            return self._Plan(
                kind="count_severity",
                sql=sql,
                sql_display=(
                    "SELECT COUNT(*)::int AS incident_count FROM incidents "
                    f"WHERE severity = '{severity}'"
                ),
                params={"severity": severity},
                expected_columns=["incident_count"],
            )

        if system_name is not None and any(
            phrase in text for phrase in ("how many", "count", "list", "show")
        ):
            if any(phrase in text for phrase in ("how many", "count", "number of")):
                sql = """
                    SELECT COUNT(*)::int AS incident_count
                    FROM incidents
                    WHERE system_name ILIKE %(system_name)s
                """
                return self._Plan(
                    kind="count_system",
                    sql=sql,
                    sql_display=(
                        "SELECT COUNT(*)::int AS incident_count FROM incidents "
                        f"WHERE system_name ILIKE '%{system_name}%'"
                    ),
                    params={"system_name": f"%{system_name}%"},
                    expected_columns=["incident_count"],
                )

            sql = """
                SELECT id::text, title, system_name, severity, created_at
                FROM incidents
                WHERE system_name ILIKE %(system_name)s
                ORDER BY created_at DESC
                LIMIT 50
            """
            return self._Plan(
                kind="list_system",
                sql=sql,
                sql_display=(
                    "SELECT id::text, title, system_name, severity, created_at FROM incidents "
                    f"WHERE system_name ILIKE '%{system_name}%' ORDER BY created_at DESC LIMIT 50"
                ),
                params={"system_name": f"%{system_name}%"},
                expected_columns=["id", "title", "system_name", "severity", "created_at"],
            )

        if any(phrase in text for phrase in ("list", "show all", "all incidents")):
            sql = """
                SELECT id::text, title, system_name, severity, created_at
                FROM incidents
                ORDER BY created_at DESC
                LIMIT 50
            """
            return self._Plan(
                kind="list_all",
                sql=sql,
                sql_display=" ".join(sql.split()),
                params={},
                expected_columns=["id", "title", "system_name", "severity", "created_at"],
            )

        # Default metric query: overall counts.
        sql = """
            SELECT COUNT(*)::int AS incident_count
            FROM incidents
        """
        return self._Plan(
            kind="count_all",
            sql=sql,
            sql_display="SELECT COUNT(*)::int AS incident_count FROM incidents",
            params={},
            expected_columns=["incident_count"],
        )

    @staticmethod
    def _extract_severity(text: str) -> str | None:
        for alias, canonical in _SEVERITY_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return canonical
        return None

    @staticmethod
    def _extract_system_name(query: str) -> str | None:
        # Prefer explicit system tokens like Radar-AESA-90 / Tactical-UAV-V2.
        match = re.search(r"\b([A-Za-z][A-Za-z0-9_-]{2,})\b", query)
        skip = {
            "how",
            "many",
            "count",
            "list",
            "show",
            "the",
            "incidents",
            "incident",
            "critical",
            "high",
            "medium",
            "low",
            "by",
            "system",
            "hardware",
            "component",
            "severity",
            "what",
            "were",
            "was",
            "are",
            "total",
            "number",
            "of",
            "all",
            "for",
        }
        candidates = re.findall(r"\b([A-Za-z][A-Za-z0-9_-]{2,})\b", query)
        for candidate in candidates:
            if candidate.lower() in skip:
                continue
            if "-" in candidate or candidate.lower() not in skip:
                if any(ch.isdigit() for ch in candidate) or "-" in candidate or candidate[0].isupper():
                    return candidate
        return None

    @staticmethod
    def _interpret(kind: str, rows: list[dict[str, Any]], query: str) -> str:
        if not rows:
            return f"No incident rows matched metrics for query: {query}"

        if kind in {"count_all", "count_severity", "count_system"}:
            count = rows[0].get("incident_count", 0)
            return f"Metric query returned incident_count={count}."

        if kind == "by_severity":
            parts = [
                f"{row.get('severity')}={row.get('incident_count')}" for row in rows
            ]
            return "Incidents by severity: " + ", ".join(parts)

        if kind == "by_system":
            parts = [
                f"{row.get('system_name')}={row.get('incident_count')}" for row in rows[:10]
            ]
            return "Incidents by system/component: " + ", ".join(parts)

        return f"Returned {len(rows)} incident row(s)."
