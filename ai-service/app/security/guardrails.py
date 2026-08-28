from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class GuardrailVerdict:
    allowed: bool
    category: str | None = None
    reason: str | None = None
    matched: str | None = None


_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,40}\b(instructions?|prompts?|rules?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "system_prompt_reveal",
        re.compile(
            r"\b(reveal|show|print|dump|expose)\b.{0,40}\b(system\s*prompt|hidden\s*prompt|developer\s*message|internal\s*instructions?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "safety_bypass",
        re.compile(
            r"\b(bypass|disable|circumvent)\b.{0,40}\b(safety|guardrail|filter|policy|content\s*policy)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be|jailbreak|dan\s+mode)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_injection",
        re.compile(
            r"(```system|<\s*/?\s*system\s*>|\[\[SYSTEM\]\]|<<\s*SYS\s*>>|###\s*System\s*:)",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_override",
        re.compile(
            r"\b(do\s+not\s+follow|override)\b.{0,30}\b(policy|safety|restrictions?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)

_SQL_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("drop", re.compile(r"\bDROP\s+(TABLE|DATABASE|INDEX|SCHEMA|VIEW)\b", re.IGNORECASE)),
    ("delete", re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)),
    ("update", re.compile(r"\bUPDATE\s+[A-Za-z_][\w.]*\s+SET\b", re.IGNORECASE)),
    ("insert", re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)),
    ("alter", re.compile(r"\bALTER\s+(TABLE|DATABASE|USER|ROLE)\b", re.IGNORECASE)),
    ("exec", re.compile(r"\b(EXEC|EXECUTE|xp_cmdshell)\s*\(", re.IGNORECASE)),
    ("union", re.compile(r"\bUNION\s+(ALL\s+)?SELECT\b", re.IGNORECASE)),
    ("comment", re.compile(r"(--\s|/\*|\*/|;)\s*(DROP|DELETE|UPDATE|INSERT|ALTER|EXEC)\b", re.IGNORECASE)),
    ("stacked", re.compile(r";\s*(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|EXEC)\b", re.IGNORECASE)),
    ("boolean", re.compile(r"\b(OR|AND)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+['\"]?", re.IGNORECASE)),
    ("sleep", re.compile(r"\b(SLEEP|BENCHMARK|WAITFOR\s+DELAY)\s*\(", re.IGNORECASE)),
)


class InputSecurityGuardrails:
    """Detect prompt-injection and SQL-injection style payloads before tool execution."""

    def inspect(self, text: str) -> GuardrailVerdict:
        candidate = (text or "").strip()
        if not candidate:
            return GuardrailVerdict(
                allowed=False,
                category="empty_input",
                reason="Query text must not be empty.",
            )

        for category, pattern in _PROMPT_INJECTION_PATTERNS:
            match = pattern.search(candidate)
            if match:
                return GuardrailVerdict(
                    allowed=False,
                    category=f"prompt_injection:{category}",
                    reason=(
                        "Query blocked by prompt-injection guardrails. "
                        "Remove instruction-override / system-prompt extraction attempts and retry."
                    ),
                    matched=match.group(0)[:120],
                )

        for category, pattern in _SQL_INJECTION_PATTERNS:
            match = pattern.search(candidate)
            if match:
                return GuardrailVerdict(
                    allowed=False,
                    category=f"sql_injection:{category}",
                    reason=(
                        "Query blocked by SQL-injection guardrails. "
                        "Dangerous SQL keywords/patterns are not permitted in analyst questions."
                    ),
                    matched=match.group(0)[:120],
                )

        return GuardrailVerdict(allowed=True)

    def assert_safe(self, text: str) -> None:
        verdict = self.inspect(text)
        if not verdict.allowed:
            raise SecurityViolationError(
                reason=verdict.reason or "Security violation.",
                category=verdict.category or "security_violation",
                matched=verdict.matched,
            )


class SecurityViolationError(Exception):
    def __init__(self, *, reason: str, category: str, matched: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.category = category
        self.matched = matched


class RateLimitExceededError(Exception):
    def __init__(
        self,
        *,
        limit: int,
        remaining: int,
        retry_after_seconds: int,
        client_key: str,
    ) -> None:
        super().__init__(
            f"Rate limit exceeded ({limit} requests per minute). Retry after {retry_after_seconds}s."
        )
        self.limit = limit
        self.remaining = remaining
        self.retry_after_seconds = retry_after_seconds
        self.client_key = client_key
