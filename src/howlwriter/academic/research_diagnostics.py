"""Structured diagnostics for external research retrieval.

External lookups are best-effort: a network failure must not abort a run that
can continue with the sources it already has. But "the provider found nothing"
and "the provider failed and we moved on" are different facts, and the report
has to be able to tell them apart. Messages are short, URL-free and never
include request headers, so nothing sensitive reaches the report.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from howlwriter.domain.serialization import DataClassSerializationMixin

OUTCOME_RESULTS = "results"
OUTCOME_NO_RESULTS = "no_results"
OUTCOME_FAILED = "failed"

CATEGORY_NETWORK = "network"
CATEGORY_TIMEOUT = "timeout"
CATEGORY_RATE_LIMITED = "rate_limited"
CATEGORY_HTTP_ERROR = "http_error"
CATEGORY_PARSE_ERROR = "parse_error"
CATEGORY_UNEXPECTED = "unexpected"

_MAX_MESSAGE = 160


@dataclass
class ResearchDiagnostic(DataClassSerializationMixin):
    provider: str
    query: str
    outcome: str
    result_count: int = 0
    category: str | None = None
    retryable: bool | None = None
    message: str = ""
    fallback_continued: bool = True

    @property
    def failed(self) -> bool:
        return self.outcome == OUTCOME_FAILED


def _safe_message(text: str) -> str:
    text = re.sub(r"https?://\S+", "<url>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_MESSAGE]


def classify_exception(exc: BaseException) -> tuple[str, bool | None, str]:
    """Return (category, retryable, safe_message) for a retrieval exception."""
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code == 429:
            return CATEGORY_RATE_LIMITED, True, "HTTP 429 rate limited"
        return CATEGORY_HTTP_ERROR, code >= 500, f"HTTP {code} {_safe_message(str(exc.reason or ''))}".strip()
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return CATEGORY_TIMEOUT, True, "request timed out"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return CATEGORY_TIMEOUT, True, "request timed out"
        return CATEGORY_NETWORK, True, _safe_message(f"network error: {reason}")
    if isinstance(exc, (json.JSONDecodeError, ET.ParseError, UnicodeDecodeError)):
        return CATEGORY_PARSE_ERROR, False, f"unparseable response ({type(exc).__name__})"
    if isinstance(exc, OSError):
        return CATEGORY_NETWORK, True, _safe_message(f"I/O error: {exc.strerror or type(exc).__name__}")
    return CATEGORY_UNEXPECTED, None, f"{type(exc).__name__}"


def failure(provider: str, query: str, exc: BaseException) -> ResearchDiagnostic:
    category, retryable, message = classify_exception(exc)
    return ResearchDiagnostic(
        provider=provider, query=query, outcome=OUTCOME_FAILED,
        category=category, retryable=retryable, message=message,
    )


def success(provider: str, query: str, count: int) -> ResearchDiagnostic:
    return ResearchDiagnostic(
        provider=provider, query=query,
        outcome=OUTCOME_RESULTS if count else OUTCOME_NO_RESULTS, result_count=count,
    )


def summarize(diagnostics: list[ResearchDiagnostic]) -> dict:
    """Per-provider rollup suitable for a report or provenance record."""
    providers: dict[str, dict] = {}
    for d in diagnostics:
        p = providers.setdefault(d.provider, {"queries": 0, "failed": 0, "no_results": 0, "results": 0, "sources": 0})
        p["queries"] += 1
        p["sources"] += d.result_count
        if d.outcome == OUTCOME_FAILED:
            p["failed"] += 1
        elif d.outcome == OUTCOME_NO_RESULTS:
            p["no_results"] += 1
        else:
            p["results"] += 1
    return {
        "providers": providers,
        "failures": [d.to_dict() for d in diagnostics if d.failed],
        "total_queries": len(diagnostics),
    }
