"""Verification records: what was checked, by what, on what evidence, with what limits.

A statement that something "was verified", from a model or from earlier prose, is
not verification. A record names the check actually performed, the component that
performed it, the evidence it saw, the resulting status and what it could not
establish. Mechanical properties are checked deterministically; a semantic review
by a model is recorded with its provider, and independence from the writer is
stated only when it was recorded, never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.domain.serialization import DataClassSerializationMixin

PASS = "PASS"
FAIL = "FAIL"
NEEDS_REVIEW = "NEEDS_REVIEW"
UNAVAILABLE = "UNAVAILABLE"  # the check could not complete; absence of evidence, not a pass
NOT_RUN = "NOT_RUN"

DETERMINISTIC = "deterministic"
EXTERNAL_RECORD = "external-record"
SEMANTIC_REVIEW = "semantic-review"


@dataclass
class VerificationRecord(DataClassSerializationMixin):
    check: str
    component: str
    method: str
    status: str
    evidence: str = ""
    limitations: list[str] = field(default_factory=list)
    scope: str = ""  # deliverable id or "package"
    provider: str | None = None  # for model-backed checks
    independent_of_writer: bool | None = None  # None: not recorded, so not claimed


def semantic_review_record(
    scope: str, *, writer_provider: str | None, reviewer_provider: str | None
) -> VerificationRecord:
    """Record a semantic review honestly: not run, or run with independence stated from the providers."""
    if not reviewer_provider:
        return VerificationRecord(
            "semantic review", "model reviewer", SEMANTIC_REVIEW, NOT_RUN, scope=scope,
            evidence="no model review was performed",
            limitations=["Meaning and claim support were checked by deterministic rules only."])
    independent = bool(writer_provider) and reviewer_provider != writer_provider
    return VerificationRecord(
        "semantic review", "model reviewer", SEMANTIC_REVIEW, UNAVAILABLE, scope=scope, provider=reviewer_provider,
        independent_of_writer=independent if writer_provider else None,
        evidence="reviewer provider recorded; this record does not contain the review verdict",
        limitations=["Independence is judged from provider names only; it does not establish that the "
                     "reviewer's errors are uncorrelated with the writer's."])
