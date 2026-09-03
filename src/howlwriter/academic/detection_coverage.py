"""Technique-Specific Detection Coverage.

Provides deterministic validation that every selected ATT&CK technique has
an explicit, mapped defensive detection and telemetry analysis or explicit
observability categorization, preventing broad generic paragraphs from
satisfying per-technique detection requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
import re

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin


class DetectionObservabilityStatus(str, enum.Enum):
    DETECTABLE_WITH_MAPPING = "DETECTABLE_WITH_MAPPING"
    PARTIALLY_OBSERVABLE = "PARTIALLY_OBSERVABLE"
    NOT_DIRECTLY_OBSERVABLE = "NOT_DIRECTLY_OBSERVABLE"
    MISSING_DETECTION = "MISSING_DETECTION"


@dataclass
class TechniqueDetectionCoverage(DataClassSerializationMixin):
    """Detection coverage evaluation for a single technique."""

    technique_id: str
    status: DetectionObservabilityStatus = DetectionObservabilityStatus.MISSING_DETECTION
    detection_evidence: list[str] = field(default_factory=list)
    choke_points: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class TechniqueDetectionSummary(DataClassSerializationMixin):
    """Aggregate summary of detection coverage across all selected techniques."""

    technique_coverages: dict[str, TechniqueDetectionCoverage] = field(default_factory=dict)
    status: str = "FAIL"  # "PASS" | "FAIL"
    total_techniques: int = 0
    detectable_count: int = 0
    partially_observable_count: int = 0
    not_directly_observable_count: int = 0
    missing_detection_count: int = 0
    missing_techniques: list[str] = field(default_factory=list)


_TELEMETRY_INDICATORS = (
    "log", "logs", "telemetry", "event id", "eventid", "sysmon", "cloudtrail",
    "sensor", "choke point", "chokepoint", "alert", "monitoring", "edr",
    "packet capture", "dpi", "tls ja3", "flow", "auditd", "auth.log",
    "firewall", "snort", "suricata", "zeek", "netflow", "detection",
)

_NOT_DIRECTLY_OBSERVABLE_INDICATORS = (
    "outside the defended boundary",
    "outside defended boundary",
    "no direct internal host telemetry",
    "0 internal host telemetry",
    "not directly observable",
    "pre-compromise",
    "no internal logs",
    "unobservable internally",
)

_PARTIALLY_OBSERVABLE_INDICATORS = (
    "partially observable",
    "partial observability",
    "limited visibility",
    "blind spot",
    "asymmetric outbound flow",
    "blends with ambient",
    "reactive detection only",
    "ephemeral artifact",
)


def evaluate_technique_detection_coverage(
    document: Document,
    technique_ids: list[str],
) -> TechniqueDetectionSummary:
    """Evaluates detection coverage deterministically for each technique."""
    coverages: dict[str, TechniqueDetectionCoverage] = {}
    missing: list[str] = []

    # Get body paragraphs
    body_paragraphs = document.body_paragraphs()
    body_texts = [p.raw_text for p in body_paragraphs]

    for tech_id in technique_ids:
        tech_clean = tech_id.strip()
        matched_paragraphs: list[str] = []

        # Find paragraphs referencing this technique or its immediate context
        for p_text in body_texts:
            if tech_clean.lower() in p_text.lower():
                matched_paragraphs.append(p_text)

        if not matched_paragraphs:
            # Technique not found in body
            cov = TechniqueDetectionCoverage(
                technique_id=tech_clean,
                status=DetectionObservabilityStatus.MISSING_DETECTION,
                notes=f"Technique {tech_clean} is not referenced in the document body.",
            )
            coverages[tech_clean] = cov
            missing.append(tech_clean)
            continue

        # Examine matched paragraphs for detection and telemetry discussion
        combined_text = "\n\n".join(matched_paragraphs).lower()

        # Check for explicit NOT_DIRECTLY_OBSERVABLE
        if any(ind in combined_text for ind in _NOT_DIRECTLY_OBSERVABLE_INDICATORS):
            cov = TechniqueDetectionCoverage(
                technique_id=tech_clean,
                status=DetectionObservabilityStatus.NOT_DIRECTLY_OBSERVABLE,
                notes="Explicitly recognized as external/pre-compromise with zero internal host telemetry.",
            )
            coverages[tech_clean] = cov
            continue

        # Check for PARTIALLY_OBSERVABLE
        if any(ind in combined_text for ind in _PARTIALLY_OBSERVABLE_INDICATORS):
            cov = TechniqueDetectionCoverage(
                technique_id=tech_clean,
                status=DetectionObservabilityStatus.PARTIALLY_OBSERVABLE,
                notes="Documented with explicit partial observability or environmental blind spots.",
            )
            coverages[tech_clean] = cov
            continue

        # Check for DETECTABLE_WITH_MAPPING
        telemetry_hits = [ind for ind in _TELEMETRY_INDICATORS if ind in combined_text]
        if telemetry_hits:
            cov = TechniqueDetectionCoverage(
                technique_id=tech_clean,
                status=DetectionObservabilityStatus.DETECTABLE_WITH_MAPPING,
                detection_evidence=telemetry_hits,
                notes=f"Mapped to telemetry: {', '.join(telemetry_hits[:4])}.",
            )
            coverages[tech_clean] = cov
        else:
            cov = TechniqueDetectionCoverage(
                technique_id=tech_clean,
                status=DetectionObservabilityStatus.MISSING_DETECTION,
                notes=f"Technique {tech_clean} is discussed without mapped detection telemetry or observability caveats.",
            )
            coverages[tech_clean] = cov
            missing.append(tech_clean)

    detectable_cnt = sum(
        1 for c in coverages.values() if c.status == DetectionObservabilityStatus.DETECTABLE_WITH_MAPPING
    )
    partial_cnt = sum(
        1 for c in coverages.values() if c.status == DetectionObservabilityStatus.PARTIALLY_OBSERVABLE
    )
    unobservable_cnt = sum(
        1 for c in coverages.values() if c.status == DetectionObservabilityStatus.NOT_DIRECTLY_OBSERVABLE
    )
    missing_cnt = len(missing)

    status = "PASS" if missing_cnt == 0 else "FAIL"

    return TechniqueDetectionSummary(
        technique_coverages=coverages,
        status=status,
        total_techniques=len(technique_ids),
        detectable_count=detectable_cnt,
        partially_observable_count=partial_cnt,
        not_directly_observable_count=unobservable_cnt,
        missing_detection_count=missing_cnt,
        missing_techniques=missing,
    )
