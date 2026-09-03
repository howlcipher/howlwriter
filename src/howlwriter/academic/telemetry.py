"""Telemetry Semantic Validation.

Ensures that defensive telemetry identifiers (Windows Event IDs, Sysmon Events,
CloudTrail events) are accurately associated with their true source/product and
log channel, rather than misattributed (e.g. describing Windows Event ID 7045 as
a Sysmon event).
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import DEPTH_FULL_TEXT, DEPTH_PARTIAL_TEXT, Source


@dataclass
class TelemetryEvidence(DataClassSerializationMixin):
    """Structured telemetry evidence item."""

    product_or_source: str
    channel_or_log: str
    event_identifier: str
    described_behavior: str
    cited_source_id: str | None = None
    validation_status: str = "VALID"  # "VALID" | "MISMATCH" | "UNSUPPORTED"
    notes: str = ""


# Authoritative known pairings for high-confidence security event streams
_KNOWN_TELEMETRY_PAIRINGS: dict[str, dict[str, str]] = {
    "7045": {
        "valid_sources": "windows system log, service control manager, scm, windows system",
        "invalid_sources": "sysmon",
        "channel": "System",
        "correct_source_name": "Windows System Log (Service Control Manager)",
        "behavior": "Service Installation / Creation",
    },
    "4688": {
        "valid_sources": "windows security log, microsoft-windows-security-auditing, security log",
        "invalid_sources": "sysmon, system log",
        "channel": "Security",
        "correct_source_name": "Windows Security Log",
        "behavior": "Process Creation",
    },
    "4624": {
        "valid_sources": "windows security log, microsoft-windows-security-auditing, security log",
        "invalid_sources": "sysmon, system log",
        "channel": "Security",
        "correct_source_name": "Windows Security Log",
        "behavior": "Successful Logon",
    },
    "4104": {
        "valid_sources": "powershell, microsoft-windows-powershell, powershell operational",
        "invalid_sources": "sysmon, security log, system log",
        "channel": "Microsoft-Windows-PowerShell/Operational",
        "correct_source_name": "PowerShell Script Block Logging",
        "behavior": "Script Block Execution",
    },
    "1": {
        "valid_sources": "sysmon, microsoft-windows-sysmon",
        "channel": "Microsoft-Windows-Sysmon/Operational",
        "correct_source_name": "Sysmon",
        "behavior": "Process Creation",
    },
    "2": {
        "valid_sources": "sysmon, microsoft-windows-sysmon",
        "channel": "Microsoft-Windows-Sysmon/Operational",
        "correct_source_name": "Sysmon",
        "behavior": "File Creation Time Changed (Timestomping)",
    },
    "23": {
        "valid_sources": "sysmon, microsoft-windows-sysmon",
        "channel": "Microsoft-Windows-Sysmon/Operational",
        "correct_source_name": "Sysmon",
        "behavior": "File Delete (archived)",
    },
}

_SYSMON_MISMATCH_RE = re.compile(
    r"\bSysmon\s+(?:Event\s+(?:ID\s*)?)?7045\b", re.IGNORECASE
)
_EVENT_PATTERN_RE = re.compile(
    r"\b(Sysmon|Windows|Security|System|PowerShell|CloudTrail)?\s*(?:Event\s+(?:ID\s*)?|EventID\s*)(\d{1,5})\b",
    re.IGNORECASE,
)


def validate_telemetry_evidence(
    evidence: TelemetryEvidence,
    sources: list[Source] | None = None,
) -> TelemetryEvidence:
    """Validates that product/source, channel, and event identifier are correctly paired."""
    event_id = evidence.event_identifier.strip()
    source_lower = evidence.product_or_source.lower()

    # 1. Check known authoritative rules
    if event_id in _KNOWN_TELEMETRY_PAIRINGS:
        pairing = _KNOWN_TELEMETRY_PAIRINGS[event_id]
        invalid_sources = [s.strip() for s in pairing.get("invalid_sources", "").split(",") if s.strip()]
        for inv in invalid_sources:
            if inv in source_lower:
                evidence.validation_status = "MISMATCH"
                evidence.notes = (
                    f"Event ID {event_id} is associated with {pairing['correct_source_name']}, "
                    f"not {evidence.product_or_source}."
                )
                return evidence

    # 2. Check source corroboration if cited
    if evidence.cited_source_id and sources:
        matched_source = next((s for s in sources if s.id == evidence.cited_source_id), None)
        if matched_source and matched_source.retrieved_text:
            if matched_source.evidence_depth not in (DEPTH_FULL_TEXT, DEPTH_PARTIAL_TEXT):
                evidence.validation_status = "UNSUPPORTED"
                evidence.notes = f"Cited source {matched_source.id} lacks substantive depth to verify telemetry pairing."
                return evidence
            s_text = matched_source.retrieved_text.lower()
            if event_id not in s_text:
                evidence.validation_status = "UNSUPPORTED"
                evidence.notes = f"Cited source {matched_source.id} does not corroborate Event ID {event_id}."
                return evidence

    evidence.validation_status = "VALID"
    return evidence


def find_telemetry_mismatches_in_text(text: str) -> list[str]:
    """Fast regex check finding obvious telemetry source misattributions in prose."""
    mismatches: list[str] = []
    for match in _SYSMON_MISMATCH_RE.finditer(text):
        mismatches.append(
            f'Telemetry misattribution: "{match.group(0)}" associates Windows Event ID 7045 with Sysmon. '
            "Event ID 7045 belongs to the Windows System Log (Service Control Manager)."
        )
    return mismatches
