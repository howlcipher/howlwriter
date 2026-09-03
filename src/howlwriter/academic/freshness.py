"""Source freshness domain logic, evaluation rules, and diagnostics.

Enforces source freshness gating during academic claim verification:
prevents obsolete or superseded sources from silently supporting current-state
claims without explicit historical justification, while keeping freshness
strictly independent from evidence depth.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Any

from howlwriter.domain.claim import Claim, ClaimTemporalContext
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import FreshnessStatus, Source


class FreshnessSeverity(str, enum.Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


@dataclass
class FreshnessFinding(DataClassSerializationMixin):
    """A machine-readable freshness verification finding."""

    source_id: str
    claim_id: str
    freshness_status: FreshnessStatus
    severity: FreshnessSeverity
    reason: str
    source_title: str = ""
    source_version: str | None = None
    superseded_by: str | None = None
    claim_text: str = ""
    action: str = ""

    def render_diagnostic(self) -> str:
        """Render a human-readable diagnostic message matching Phase 8 formatting."""
        status_val = (
            self.freshness_status.value
            if isinstance(self.freshness_status, enum.Enum)
            else str(self.freshness_status)
        )
        lines = [
            "Source freshness warning",
            "",
            "Source:",
            self.source_title or self.source_id,
            "",
            "Status:",
            status_val,
        ]
        if self.superseded_by:
            lines.extend(["", "Superseded by:", str(self.superseded_by)])
        if self.claim_text:
            lines.extend(["", "Affected claim:", f'"{self.claim_text}"'])
        if self.action:
            lines.extend(["", "Action:", self.action])
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> FreshnessFinding:
        data = dict(data)
        if "freshness_status" in data and isinstance(data["freshness_status"], str):
            try:
                data["freshness_status"] = FreshnessStatus(data["freshness_status"])
            except ValueError:
                data["freshness_status"] = FreshnessStatus.VERSION_UNKNOWN
        if "severity" in data and isinstance(data["severity"], str):
            try:
                data["severity"] = FreshnessSeverity(data["severity"])
            except ValueError:
                data["severity"] = FreshnessSeverity.WARNING
        return super().from_dict(data)


def normalize_version(v: str | None) -> str | None:
    """Normalize version string for deterministic comparison (e.g. 'v15' -> '15', 'Rev. 2' -> '2')."""
    if not v:
        return None
    s = str(v).strip().lower()
    s = re.sub(r"^(?:revision|rev\.?)\s*", "", s)
    s = re.sub(r"^v", "", s)
    return s.strip()


def extract_version_and_family(text: str) -> tuple[str | None, str | None]:
    """Extracts (authority_family, version) from text if present."""
    if not text:
        return None, None

    # MITRE ATT&CK: e.g. "MITRE ATT&CK v19.2", "ATT&CK v15"
    m = re.search(
        r"\b(?:MITRE\s+)?ATT&CK(?:\s+Enterprise)?\s+(?:v|version\s*)(\d+(?:\.\d+)?)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return "MITRE ATT&CK", f"v{m.group(1)}"

    # NIST SP publications: e.g. "NIST SP 800-61 Rev. 2" or "NIST 800-53 Rev. 5"
    m = re.search(
        r"\bNIST(?:\s+SP|\s+Special\s+Publication)?\s*(?:800-\d+|FIPS\s+\d+)?(?:\s+(?:Rev\.?|Revision)\s*(\d+))\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return "NIST", f"Rev. {m.group(1)}"

    # Named Framework / Standard: e.g. "Framework v2", "Framework v3", "Standard v1.0"
    m = re.search(
        r"\b([A-Za-z0-9_-]+)\s+(?:v|version\s*|Rev\.?\s*)(\d+(?:\.\d+)?)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        word = m.group(1)
        if word.lower() not in ("the", "a", "an", "and", "in", "to", "on", "at", "by", "for", "with"):
            return word, f"v{m.group(2)}"

    # Standalone version token: e.g. "v19.2", "v15"
    m = re.search(r"\bv(\d+(?:\.\d+)?)\b", text, re.IGNORECASE)
    if m:
        return None, f"v{m.group(1)}"

    return None, None


_CURRENT_STATE_PATTERNS = (
    re.compile(r"\b(?:currently|as of today|presently|contemporary|modern)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:current|latest)\s+(?:[\w-]+\s+){0,3}(?:guidance|recommendations?|standards?|models?|frameworks?|releases?|versions?|authority|revisions?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:now)\s+(?:recommends?|defines?|requires?|separates?|categorizes?|mandates?)\b",
        re.IGNORECASE,
    ),
)

_HISTORICAL_PATTERNS = (
    re.compile(r"\b(?:historically|originally|previously|formerly|deprecated|prior to|past guidance|legacy)\b", re.IGNORECASE),
    re.compile(r"\bin\s+(?:19\d\d|20[01]\d|202[0-4])\b", re.IGNORECASE),
    re.compile(r"\b(?:in|under)\s+(?:Rev\.?\s*\d+|version\s*\d+|v\d+|[A-Za-z0-9_-]+\s+v\d+)\b", re.IGNORECASE),
    re.compile(r"\b(?:categorized|defined|recommended|specified|mandated|described)\b", re.IGNORECASE),
)


def classify_claim_temporal_context(
    claim_or_text: Claim | str,
    *,
    explicit_context: ClaimTemporalContext = ClaimTemporalContext.UNKNOWN,
    explicit_target_version: str | None = None,
    explicit_target_family: str | None = None,
    explicit_historical_use: bool = False,
) -> tuple[ClaimTemporalContext, str | None, str | None]:
    """Deterministically classify temporal context and version requirement for a claim.

    Returns:
        (ClaimTemporalContext, target_version, target_family)
    """
    if isinstance(claim_or_text, Claim):
        claim_text = claim_or_text.text
        if claim_or_text.intentional_historical_use or bool(claim_or_text.historical_use_reason):
            explicit_historical_use = True
        if claim_or_text.temporal_context != ClaimTemporalContext.UNKNOWN:
            explicit_context = claim_or_text.temporal_context
        if claim_or_text.target_version:
            explicit_target_version = claim_or_text.target_version
        if claim_or_text.target_family:
            explicit_target_family = claim_or_text.target_family
    else:
        claim_text = str(claim_or_text)

    fam_extracted, ver_extracted = extract_version_and_family(claim_text)
    effective_family = explicit_target_family or fam_extracted
    effective_version = explicit_target_version or ver_extracted

    if explicit_historical_use:
        return ClaimTemporalContext.HISTORICAL, effective_version, effective_family

    if explicit_context != ClaimTemporalContext.UNKNOWN:
        return explicit_context, effective_version, effective_family

    # Check for historical markers
    has_historical_marker = any(p.search(claim_text) for p in _HISTORICAL_PATTERNS)
    has_current_marker = any(p.search(claim_text) for p in _CURRENT_STATE_PATTERNS)

    if has_historical_marker and not has_current_marker:
        return ClaimTemporalContext.HISTORICAL, effective_version, effective_family

    if has_current_marker:
        return ClaimTemporalContext.CURRENT_STATE, effective_version, effective_family

    if effective_version:
        return ClaimTemporalContext.VERSION_SPECIFIC, effective_version, effective_family

    return ClaimTemporalContext.TIME_INSENSITIVE, None, None


def evaluate_source_freshness_for_claim(
    claim: Claim,
    source: Source,
    spec: Any | None = None,
) -> tuple[FreshnessSeverity, FreshnessFinding | None]:
    """Evaluates source freshness against a specific claim.

    Deterministic rules:
    - Rule A: CURRENT source + current-state claim -> PASS
    - Rule B: SUPERSEDED source + current-state claim -> NEEDS_REVIEW finding
    - Rule C: SUPERSEDED source + explicit historical use -> PASS
    - Rule D: HISTORICAL_REQUIRED + historical claim -> PASS
    - Rule E: VERSION_UNKNOWN + current-state claim -> NEEDS_REVIEW finding
    - Rule F: Source version does not match requested claim version -> BLOCKED finding
    """
    context, target_version, target_family = classify_claim_temporal_context(claim)

    freshness = source.freshness
    source_status = freshness.freshness_status

    # Check explicit intentional historical use
    is_intentional_historical = (
        claim.intentional_historical_use
        or bool(claim.historical_use_reason)
        or context == ClaimTemporalContext.HISTORICAL
        or freshness.intentional_historical_use
        or bool(freshness.intentional_historical_notes)
        or (
            spec is not None
            and getattr(spec, "source_requirements", None) is not None
            and (
                getattr(spec.source_requirements, "allow_historical_sources", False)
                or source.id in getattr(spec.source_requirements, "historical_sources_allowed", [])
            )
        )
    )

    # 1. Rule F: Version Mismatch
    # If the claim targets a specific version, verify the source matches it.
    if target_version and freshness.source_version:
        norm_target = normalize_version(target_version)
        norm_source = normalize_version(freshness.source_version)
        if norm_target != norm_source:
            # Check family compatibility if both are known
            family_matches = True
            if target_family and freshness.authority_family:
                family_matches = target_family.lower() in freshness.authority_family.lower() or freshness.authority_family.lower() in target_family.lower()

            if family_matches:
                finding = FreshnessFinding(
                    source_id=source.id,
                    claim_id=claim.id,
                    freshness_status=source_status,
                    severity=FreshnessSeverity.BLOCKED,
                    reason=(
                        f"Source version '{freshness.source_version}' does not match explicitly requested version "
                        f"'{target_version}' for {freshness.authority_family or source.title}."
                    ),
                    source_title=source.title,
                    source_version=freshness.source_version,
                    superseded_by=freshness.superseded_by,
                    claim_text=claim.text,
                    action=f"Use authoritative source for version '{target_version}' or update the claim version requirement.",
                )
                return FreshnessSeverity.BLOCKED, finding

    # 2. Rule B: SUPERSEDED source used for current-state claim
    if source_status == FreshnessStatus.SUPERSEDED and context == ClaimTemporalContext.CURRENT_STATE:
        superseded_info = f" ({freshness.superseded_by})" if freshness.superseded_by else ""
        finding = FreshnessFinding(
            source_id=source.id,
            claim_id=claim.id,
            freshness_status=source_status,
            severity=FreshnessSeverity.NEEDS_REVIEW,
            reason=f"Current-state claim supported by superseded authority '{source.title}'.",
            source_title=source.title,
            source_version=freshness.source_version,
            superseded_by=freshness.superseded_by,
            claim_text=claim.text,
            action=f"Review the claim against the current revision{superseded_info} or qualify the claim to indicate historical context.",
        )
        return FreshnessSeverity.NEEDS_REVIEW, finding

    # 3. HISTORICAL_REQUIRED with current-state claim
    if source_status == FreshnessStatus.HISTORICAL_REQUIRED and context == ClaimTemporalContext.CURRENT_STATE:
        finding = FreshnessFinding(
            source_id=source.id,
            claim_id=claim.id,
            freshness_status=source_status,
            severity=FreshnessSeverity.NEEDS_REVIEW,
            reason=f"Source '{source.title}' is marked HISTORICAL_REQUIRED, but claim asserts current-state authority.",
            source_title=source.title,
            source_version=freshness.source_version,
            superseded_by=freshness.superseded_by,
            claim_text=claim.text,
            action="Update the claim to historical context or replace with current authority.",
        )
        return FreshnessSeverity.NEEDS_REVIEW, finding

    # 4. Rule C & D: Intentional Historical Use
    if is_intentional_historical or source_status == FreshnessStatus.HISTORICAL_REQUIRED:
        return FreshnessSeverity.PASS, None

    # 5. Rule E: VERSION_UNKNOWN with current-state claim
    if source_status == FreshnessStatus.VERSION_UNKNOWN:
        if context == ClaimTemporalContext.CURRENT_STATE:
            finding = FreshnessFinding(
                source_id=source.id,
                claim_id=claim.id,
                freshness_status=source_status,
                severity=FreshnessSeverity.NEEDS_REVIEW,
                reason=f"Current-state claim supported by source '{source.title}' with VERSION_UNKNOWN.",
                source_title=source.title,
                source_version=None,
                superseded_by=None,
                claim_text=claim.text,
                action="Verify whether this source represents current authority and specify freshness_status.",
            )
            return FreshnessSeverity.NEEDS_REVIEW, finding

    # 6. Rule A: CURRENT source or time-insensitive claim without conflict
    return FreshnessSeverity.PASS, None
