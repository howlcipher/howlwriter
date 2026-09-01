"""Unsupported-specificity / technical-identifier grounding checks.

Mirrors the shape of the existing direct-quotation integrity check in
verifier.py: regex-extract candidate spans from the final document, and flag
any that are not found verbatim (case-insensitive substring) in any grounding
text. Applied to precise-looking technical identifiers and suspiciously
precise numeric claims instead of quotations.

This is deliberately generalized beyond cybersecurity: any domain that uses
precise identifiers or decimal-precision figures (CVEs, ATT&CK techniques,
event/finding IDs, case numbers, statute citations, exact percentages) is
susceptible to the same "invented specificity" failure mode HowlWriter must
avoid for citations, authors, and quotations. When a precise identifier isn't
grounded in the supplied source material, the correct behavior is to
generalize the writing, not to fabricate a plausible-looking exact value.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from howlwriter.domain.serialization import DataClassSerializationMixin

# Ship the higher-confidence, lower-false-positive-risk patterns first.
_IDENTIFIER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cve", re.compile(r"\bCVE-\d{4}-\d{4,7}\b")),
    ("mitre_attack_technique", re.compile(r"\bT\d{4}(?:\.\d{3})?\b")),
    ("windows_event_id", re.compile(r"\bEvent\s?ID\s*\d{2,5}\b", re.IGNORECASE)),
    ("cloud_finding_name", re.compile(r"\b[A-Z][a-zA-Z]+:[A-Z][a-zA-Z]+/[A-Za-z]+\b")),
    ("precise_percentage", re.compile(r"\b\d{1,3}\.\d{1,2}%")),
    (
        "precise_entropy_or_jitter",
        re.compile(
            r"\b(?:entropy|jitter)\s*(?:of|=|:|>|<)?\s*\d+(?:\.\d+)?%?\b",
            re.IGNORECASE,
        ),
    ),
]


@dataclass
class IdentifierFinding(DataClassSerializationMixin):
    identifier: str
    kind: str
    context_snippet: str


def _context_snippet(text: str, start: int, end: int, radius: int = 40) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return text[lo:hi].strip()


def find_ungrounded_identifiers(
    document_text: str, grounding_texts: list[str]
) -> list[IdentifierFinding]:
    """Finds precise technical-identifier-shaped spans in document_text that
    do not appear verbatim in any of grounding_texts.

    grounding_texts should include every source's retrieved_text plus any
    other legitimately-authoritative text available to the writer (e.g. the
    assignment's own topic/requirements, which may themselves reference exact
    identifiers the assignment wants discussed).
    """
    lowered_grounding = [g.lower() for g in (grounding_texts or []) if g]

    findings: list[IdentifierFinding] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _IDENTIFIER_PATTERNS:
        for match in pattern.finditer(document_text):
            identifier = match.group(0)
            key = (kind, identifier.lower())
            if key in seen:
                continue
            grounded = any(identifier.lower() in g for g in lowered_grounding)
            if grounded:
                continue
            seen.add(key)
            findings.append(
                IdentifierFinding(
                    identifier=identifier,
                    kind=kind,
                    context_snippet=_context_snippet(document_text, match.start(), match.end()),
                )
            )

    return findings
