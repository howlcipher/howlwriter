"""Classifies free-text assignment requirements and routes each kind to the
validator actually suited to check it, instead of forcing every requirement
through coverage.py's content-word-overlap checker.

spec.requirements is a flat list of natural-language sentences. Some are
positive content asks ("include tools and defensive telemetry") that
coverage.py's word-overlap matcher is well suited to verify. Others are
prohibitions ("do not invent identifiers"), length/scope asks ("maximum 10
pages"), or style asks ("keep concise") that structurally cannot score well
under word overlap even when the document fully complies -- overlap can only
confirm content words appeared somewhere, not that a prohibition was
honored or that prose is in fact concise. Running those through coverage.py
anyway produces a misleading "N/M requirements covered" figure.

This module does NOT build a general requirements engine: classification is
a small, deterministic keyword/regex dispatch over four fixed buckets, and
each non-positive bucket is scored by reusing an existing, already-computed
signal (identifier_warnings for the one prohibition sub-type this milestone
auto-validates, word_count_status for length, redundancy findings for
style) rather than new NLP. Unmatched prohibition text is reported as
present but not automatically validated, rather than silently mis-scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

from howlwriter.academic.coverage import CoverageResult, RequirementResult
from howlwriter.academic.identifiers import identifier_kinds_present
from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin

RequirementKind = Literal["positive", "prohibition", "length", "style"]

# Order matters: checked prohibition -> length -> style -> positive, since a
# single requirement sentence can nominally match more than one keyword set
# (e.g. "Do not exceed 10 pages" is both a prohibition and a length ask --
# length constraints have a dedicated validator, so length wins there; but a
# prohibition phrase alone, with no length wording, stays a prohibition).
_PROHIBITION_RE = re.compile(
    r"\b(?:do not|does not|shall not|must not|should not|never invent|never fabricate)\b",
    re.IGNORECASE,
)
_LENGTH_RE = re.compile(
    r"\b(?:maximum|minimum|no more than|no fewer than|at least|at most|"
    r"word limit|page limit|word count|page count|length constraint|\d+\s*pages?\b)",
    re.IGNORECASE,
)
_STYLE_RE = re.compile(
    r"\b(?:concise|conciseness|elaborat\w*|padding|redundan\w*|brief|succinct)\b",
    re.IGNORECASE,
)


def classify_requirement(text: str) -> RequirementKind:
    """Deterministically classifies a single requirement sentence.

    Precedence: length wins over a bare prohibition phrase when the text
    also names an explicit length/page/word bound (that's a length
    constraint expressed as a negative sentence, e.g. "Do not exceed 10
    pages"), since length.py's dedicated validator is strictly more precise
    than the generic identifier-fabrication prohibition check. Otherwise
    prohibition wins over style/positive, then style, then positive.
    """
    has_length = bool(_LENGTH_RE.search(text))
    has_prohibition = bool(_PROHIBITION_RE.search(text))
    if has_length and has_prohibition:
        return "length"
    if has_prohibition:
        return "prohibition"
    if has_length:
        return "length"
    if _STYLE_RE.search(text):
        return "style"
    return "positive"


@dataclass
class RequirementClassification(DataClassSerializationMixin):
    positive: list[str] = field(default_factory=list)
    prohibition: list[str] = field(default_factory=list)
    length: list[str] = field(default_factory=list)
    style: list[str] = field(default_factory=list)


def classify_requirements(requirements: list[str]) -> RequirementClassification:
    result = RequirementClassification()
    for requirement in requirements:
        bucket = classify_requirement(requirement)
        getattr(result, bucket).append(requirement)
    return result


_IDENTIFIER_FABRICATION_RE = re.compile(
    r"\b(?:invent|fabricat\w*)\b.{0,80}\bidentifier", re.IGNORECASE | re.DOTALL
)
_IDENTIFIER_FABRICATION_KEYWORDS = (
    "cve",
    "att&ck",
    "event id",
    "finding name",
    "identifier",
)


def is_identifier_fabrication_prohibition(text: str) -> bool:
    """Narrow sub-type check: is this prohibition specifically about not
    inventing technical identifiers? This is the only prohibition kind this
    milestone auto-validates (via VerificationSummary.identifier_warnings,
    since academic/identifiers.py's find_ungrounded_identifiers already
    enforces exactly this). Any other prohibition text is left unvalidated
    by an automated check and reported as such rather than mis-scored.
    """
    if _IDENTIFIER_FABRICATION_RE.search(text):
        return True
    lowered = text.lower()
    return "invent" in lowered and any(k in lowered for k in _IDENTIFIER_FABRICATION_KEYWORDS)


# Phrases that indicate a positive requirement specifically wants precise
# identifiers (not just topic/category names) of a given
# academic.identifiers._IDENTIFIER_PATTERNS kind.
_IDENTIFIER_KIND_HINTS: dict[str, str] = {
    "technique id": "mitre_attack_technique",
    "technique ids": "mitre_attack_technique",
    "cve id": "cve",
    "cve ids": "cve",
    "cve number": "cve",
    "cve numbers": "cve",
    "event id": "windows_event_id",
    "event ids": "windows_event_id",
    "finding name": "cloud_finding_name",
    "finding names": "cloud_finding_name",
}


def _required_identifier_kind(requirement_text: str) -> str | None:
    lowered = requirement_text.lower()
    for phrase, kind in _IDENTIFIER_KIND_HINTS.items():
        if phrase in lowered:
            return kind
    return None


def apply_identifier_specificity_overrides(
    coverage: CoverageResult, document: Document, grounding_texts: list[str]
) -> CoverageResult:
    """Downgrades a coverage PASS to FAIL for a positive requirement whose
    text specifically names an identifier kind (e.g. "ATT&CK technique
    IDs") when grounded identifiers of that kind are available in the
    grounding corpus but the document contains none of that kind -- generic
    tactic-name word overlap should not certify "the paper used exact
    technique IDs" when it only used category vocabulary.

    Falls back to the original word-overlap result when no grounded
    identifiers of the required kind exist anywhere in grounding_texts --
    a requirement can't be held to using an identifier that was never
    actually available.
    """
    grounding_kinds: set[str] = set()
    for text in grounding_texts:
        if text:
            grounding_kinds |= identifier_kinds_present(text)
    document_kinds = identifier_kinds_present(document.text)

    new_results: list[RequirementResult] = []
    present_count = 0
    for result in coverage.requirement_results:
        kind = _required_identifier_kind(result.requirement)
        if (
            result.status == "PASS"
            and kind is not None
            and kind in grounding_kinds
            and kind not in document_kinds
        ):
            result = RequirementResult(
                requirement=result.requirement,
                status="FAIL",
                overlap_ratio=result.overlap_ratio,
                reason=(
                    f"Word overlap suggests coverage, but no {kind}-shaped identifier "
                    "was found in the document even though grounded identifiers of "
                    "that kind are available in the sources."
                ),
                kind="identifier_specificity",
            )
        new_results.append(result)
        if result.status == "PASS":
            present_count += 1

    status = "PASS" if present_count == len(new_results) else "FAIL"
    return CoverageResult(
        status=status,
        required_count=coverage.required_count,
        present_count=present_count,
        requirement_results=new_results,
    )
