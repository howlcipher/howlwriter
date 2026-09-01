"""Minimum-sufficient-coverage checking for explicit assignment requirements.

spec.requirements is a free-text checklist that is fed into the WRITER prompt
verbatim but, until this module existed, was never actually verified against
the resulting document -- an assignment could ask for "include tools and
defensive telemetry" and the pipeline would report READY even if the final
draft silently dropped one of those elements during compression.

This deliberately reuses check_outline_conformance()'s spirit (lexical
presence, not semantic understanding) but is coarser than outline matching:
requirements are often full sentences spanning multiple paragraphs (e.g.
"Compare eBPF runtime security against ptrace and LSM hooks"), so matching is
done via content-word overlap against the whole document body rather than
per-heading/per-topic-sentence matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin

_CONTENT_WORD_RE = re.compile(r"\b\w{4,}\b")
_DEFAULT_OVERLAP_THRESHOLD = 0.6


@dataclass
class RequirementResult(DataClassSerializationMixin):
    requirement: str
    status: str  # "PASS" | "FAIL"
    overlap_ratio: float = 0.0
    reason: str = ""


@dataclass
class CoverageResult(DataClassSerializationMixin):
    status: str
    required_count: int = 0
    present_count: int = 0
    requirement_results: list[RequirementResult] = field(default_factory=list)


def _content_words(text: str) -> set[str]:
    return set(_CONTENT_WORD_RE.findall(text.lower()))


def check_requirements_coverage(
    document: Document,
    requirements: list[str],
    overlap_threshold: float = _DEFAULT_OVERLAP_THRESHOLD,
) -> CoverageResult:
    """Checks whether each explicit assignment requirement is represented
    somewhere in the document body, via content-word overlap.

    This is intentionally not a semantic matcher -- it is the same fidelity
    bar as check_outline_conformance()'s topic-sentence matching, just
    applied against the whole body instead of per-paragraph.
    """
    if not requirements:
        return CoverageResult(status="PASS", required_count=0, present_count=0)

    body_words = _content_words(document.text)

    results: list[RequirementResult] = []
    present_count = 0
    for requirement in requirements:
        req_words = _content_words(requirement)
        if not req_words:
            # A requirement with no meaningful content words (e.g. pure
            # punctuation) cannot be meaningfully checked; treat it as
            # trivially satisfied rather than always failing it.
            results.append(
                RequirementResult(
                    requirement=requirement,
                    status="PASS",
                    overlap_ratio=1.0,
                    reason="No checkable content words in requirement text.",
                )
            )
            present_count += 1
            continue

        overlap = len(req_words & body_words) / len(req_words)
        if overlap >= overlap_threshold:
            results.append(
                RequirementResult(
                    requirement=requirement,
                    status="PASS",
                    overlap_ratio=round(overlap, 3),
                    reason="Sufficient content-word overlap with document body.",
                )
            )
            present_count += 1
        else:
            results.append(
                RequirementResult(
                    requirement=requirement,
                    status="FAIL",
                    overlap_ratio=round(overlap, 3),
                    reason="Requirement not clearly represented in the document body.",
                )
            )

    status = "PASS" if present_count == len(requirements) else "FAIL"
    return CoverageResult(
        status=status,
        required_count=len(requirements),
        present_count=present_count,
        requirement_results=results,
    )
