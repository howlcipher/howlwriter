"""Tests for Source Freshness Gating v1.

Verifies:
1. FreshnessStatus domain enum and SourceFreshness serialization/deserialization.
2. Backward-compatible source objects without freshness metadata.
3. Verification rules (Rule A through Rule F).
4. Readiness integration (READY, NEEDS_REVIEW, BLOCKED).
5. Independence of evidence depth and source freshness.
6. Diagnostic formatting and machine-readable structures.
7. Privacy: no machine-specific path leakage in findings.
8. Phase 15 regression fixture modeled after real-world obsolete authority citation.
"""

from __future__ import annotations

import json
import pytest

from howlwriter.academic.freshness import (
    FreshnessFinding,
    FreshnessSeverity,
    classify_claim_temporal_context,
    evaluate_source_freshness_for_claim,
    extract_version_and_family,
    normalize_version,
)
from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec, SourceRequirements
from howlwriter.academic.verifier import AcademicVerifier
from howlwriter.config.defaults import default_config
from howlwriter.domain.claim import Claim, ClaimTemporalContext, ClaimType
from howlwriter.domain.document import Document
from howlwriter.domain.source import (
    DEPTH_FULL_TEXT,
    DEPTH_METADATA_ONLY,
    FreshnessStatus,
    Source,
    SourceFreshness,
    source_from_dict,
)
from src.control_plane.agent_execution import FakeAgentBackend


def _make_fake_backend(body_markdown: str, claims_made: list[dict] | None = None) -> FakeAgentBackend:
    claims_yaml = "claims_made: []\n"
    if claims_made:
        lines = ["claims_made:"]
        for c in claims_made:
            lines.append(f"  - claim: \"{c.get('claim', '')}\"")
            if "source_id" in c:
                lines.append(f"    source_id: \"{c['source_id']}\"")
        claims_yaml = "\n".join(lines) + "\n"

    indented = "\n".join(f"  {line}" for line in body_markdown.splitlines())
    return FakeAgentBackend(
        agent_id="fake_academic_backend",
        default_stdout=f"""```yaml
body_markdown: |
{indented}
resulting_text: |
{indented}
{claims_yaml}
verdict: PASS
differences: []
rationale: "Aligns with source material."
warnings: []
```""",
    )


# ==============================================================================
# PHASE 14: 1-5 Domain Model & Serialization / Deserialization
# ==============================================================================

@pytest.mark.parametrize(
    "status",
    [
        FreshnessStatus.CURRENT,
        FreshnessStatus.SUPERSEDED,
        FreshnessStatus.HISTORICAL_REQUIRED,
        FreshnessStatus.VERSION_UNKNOWN,
    ],
)
def test_freshness_status_serialization_roundtrip(status: FreshnessStatus):
    freshness = SourceFreshness(
        retrieved_at="2026-08-01",
        published_at="2024-01-01",
        source_version="v15",
        superseded_by="v19.2",
        freshness_status=status,
        intentional_historical_notes="Used for version comparison.",
        authority_family="MITRE ATT&CK",
        document_identifier="enterprise-attack-v15",
        intentional_historical_use=True,
    )
    serialized = freshness.to_dict()
    assert serialized["freshness_status"] == status.value
    assert serialized["authority_family"] == "MITRE ATT&CK"
    assert serialized["intentional_historical_use"] is True

    reconstructed = SourceFreshness.from_dict(serialized)
    assert reconstructed.freshness_status == status
    assert reconstructed.source_version == "v15"
    assert reconstructed.superseded_by == "v19.2"
    assert reconstructed.authority_family == "MITRE ATT&CK"
    assert reconstructed.intentional_historical_use is True


def test_backward_compatible_source_without_freshness_metadata():
    """A legacy source dict with no freshness metadata must deserialize safely."""
    raw = {
        "id": "S001",
        "title": "Legacy Architecture Guide",
        "authors": ["Engineer Bob"],
        "retrieved_text": "Sample substantive text content.",
        "evidence_depth": "FULL_TEXT",
    }
    src = source_from_dict(raw)
    assert src.freshness is not None
    assert src.freshness.freshness_status == FreshnessStatus.VERSION_UNKNOWN
    assert src.freshness.source_version is None
    assert src.freshness.superseded_by is None
    assert src.freshness.intentional_historical_use is False


def test_source_freshness_partial_dict():
    """Partial freshness dict with unknown or missing keys must deserialize safely."""
    raw = {
        "id": "S002",
        "title": "Partial Metadata Report",
        "authors": ["Alice"],
        "freshness": {
            "source_version": "2.1",
            "unknown_extra_field": "ignore_me",
        },
    }
    src = source_from_dict(raw)
    assert src.freshness.source_version == "2.1"
    assert src.freshness.freshness_status == FreshnessStatus.VERSION_UNKNOWN


# ==============================================================================
# PHASE 14: 6-12 Verification Rules (Rules A - F)
# ==============================================================================

def test_rule_a_current_source_current_claim_passes():
    """Rule A: CURRENT source + current-state claim -> PASS."""
    src = Source(
        id="S001",
        title="MITRE ATT&CK Enterprise v19.2",
        authors=["MITRE"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="MITRE ATT&CK currently categorizes sub-techniques under parent techniques.",
        freshness=SourceFreshness(
            source_version="v19.2",
            freshness_status=FreshnessStatus.CURRENT,
            authority_family="MITRE ATT&CK",
        ),
    )
    claim = Claim(
        id="C001",
        text="MITRE ATT&CK currently categorizes sub-techniques under parent techniques.",
        claim_type=ClaimType.FACTUAL,
    )
    severity, finding = evaluate_source_freshness_for_claim(claim, src)
    assert severity == FreshnessSeverity.PASS
    assert finding is None

    # End-to-end verifier check
    doc = Document.parse("MITRE ATT&CK currently categorizes sub-techniques under parent techniques (S001).")
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(
        doc,
        [src],
        stated_claims=[{"claim": "MITRE ATT&CK currently categorizes sub-techniques under parent techniques."}],
    )
    assert summary.supported_claims == 1
    assert summary.unsupported_claims == 0
    assert len(summary.freshness_findings) == 0
    assert summary.status == "PASS"


def test_rule_b_superseded_source_current_claim_produces_review_finding():
    """Rule B: SUPERSEDED source + current-state claim -> NEEDS_REVIEW finding."""
    src = Source(
        id="S001",
        title="NIST SP 800-61 Rev. 2",
        authors=["NIST"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="Incident response life cycle involves four phases: preparation, detection, containment, and recovery.",
        freshness=SourceFreshness(
            source_version="Rev. 2",
            freshness_status=FreshnessStatus.SUPERSEDED,
            superseded_by="NIST SP 800-61 Rev. 3",
            authority_family="NIST",
        ),
    )
    claim = Claim(
        id="C001",
        text="NIST currently recommends an incident response life cycle with four phases.",
        claim_type=ClaimType.FACTUAL,
    )
    severity, finding = evaluate_source_freshness_for_claim(claim, src)
    assert severity == FreshnessSeverity.NEEDS_REVIEW
    assert finding is not None
    assert finding.source_id == "S001"
    assert finding.freshness_status == FreshnessStatus.SUPERSEDED
    assert finding.superseded_by == "NIST SP 800-61 Rev. 3"
    assert "Current-state claim supported by superseded authority" in finding.reason
    assert "Review the claim against the current revision" in finding.action

    # End-to-end verifier check
    doc = Document.parse("NIST currently recommends an incident response life cycle with four phases (S001).")
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(
        doc,
        [src],
        stated_claims=[{"claim": "NIST currently recommends an incident response life cycle with four phases."}],
    )
    assert summary.supported_claims == 1
    assert len(summary.freshness_findings) == 1
    assert summary.freshness_findings[0].superseded_by == "NIST SP 800-61 Rev. 3"
    assert summary.status == "NEEDS_REVIEW"


def test_rule_c_superseded_source_intentional_historical_claim_passes():
    """Rule C: SUPERSEDED source + explicit historical claim -> PASS."""
    src = Source(
        id="S001",
        title="NIST SP 800-61 Revision 2",
        authors=["NIST"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="Incident response life cycle involves preparation, detection, containment, and post-incident activity.",
        freshness=SourceFreshness(
            source_version="Revision 2",
            freshness_status=FreshnessStatus.SUPERSEDED,
            superseded_by="NIST SP 800-61 Revision 3",
            authority_family="NIST",
            intentional_historical_use=True,
            intentional_historical_notes="Historical comparison against modern incident response guidance.",
        ),
    )
    claim = Claim(
        id="C001",
        text="In 2012, NIST SP 800-61 Revision 2 recommended a four-phase incident response life cycle.",
        claim_type=ClaimType.FACTUAL,
        temporal_context=ClaimTemporalContext.HISTORICAL,
    )
    severity, finding = evaluate_source_freshness_for_claim(claim, src)
    assert severity == FreshnessSeverity.PASS
    assert finding is None

    doc = Document.parse("In 2012, NIST SP 800-61 Revision 2 recommended a four-phase incident response life cycle (S001).")
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(doc, [src])
    assert summary.supported_claims == 1
    assert summary.unsupported_claims == 0
    assert len(summary.freshness_findings) == 0
    assert summary.status == "PASS"


def test_rule_d_historical_required_passes_for_historical_claims():
    """Rule D: HISTORICAL_REQUIRED + historical claim -> PASS."""
    src = Source(
        id="S001",
        title="RFC 793 Transmission Control Protocol",
        authors=["Postel, Jon"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="Historically, RFC 793 established the fundamental three-way handshake.",
        freshness=SourceFreshness(
            source_version="RFC 793",
            freshness_status=FreshnessStatus.HISTORICAL_REQUIRED,
            superseded_by="RFC 9293",
            intentional_historical_notes="Original 1981 specification required for historical architecture section.",
        ),
    )
    claim = Claim(
        id="C001",
        text="Originally, RFC 793 defined the TCP connection handshake.",
        claim_type=ClaimType.FACTUAL,
    )
    severity, finding = evaluate_source_freshness_for_claim(claim, src)
    assert severity == FreshnessSeverity.PASS
    assert finding is None


def test_rule_d_historical_required_on_current_claim_flags_needs_review():
    """Rule D variant: HISTORICAL_REQUIRED + current-state claim -> NEEDS_REVIEW."""
    src = Source(
        id="S001",
        title="RFC 793 Transmission Control Protocol",
        authors=["Postel, Jon"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="The TCP specification requires standard segment headers.",
        freshness=SourceFreshness(
            source_version="RFC 793",
            freshness_status=FreshnessStatus.HISTORICAL_REQUIRED,
            superseded_by="RFC 9293",
        ),
    )
    claim = Claim(
        id="C001",
        text="The current standard requires RFC 793 segment format.",
        claim_type=ClaimType.FACTUAL,
    )
    severity, finding = evaluate_source_freshness_for_claim(claim, src)
    assert severity == FreshnessSeverity.NEEDS_REVIEW
    assert finding is not None
    assert "marked HISTORICAL_REQUIRED, but claim asserts current-state" in finding.reason


def test_rule_e_version_unknown_on_current_claim_flags_needs_review():
    """Rule E: VERSION_UNKNOWN + current-state claim -> NEEDS_REVIEW."""
    src = Source(
        id="S001",
        title="Security Compliance Manual",
        authors=["Anonymous"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="Zero trust architecture currently mandates continuous authentication.",
        freshness=SourceFreshness(
            freshness_status=FreshnessStatus.VERSION_UNKNOWN,
        ),
    )
    claim = Claim(
        id="C001",
        text="Zero trust architecture currently mandates continuous authentication.",
        claim_type=ClaimType.FACTUAL,
    )
    severity, finding = evaluate_source_freshness_for_claim(claim, src)
    assert severity == FreshnessSeverity.NEEDS_REVIEW
    assert finding is not None
    assert "with VERSION_UNKNOWN" in finding.reason


def test_rule_f_version_mismatch_blocks_claim():
    """Rule F: Source version does not match explicitly requested claim version -> BLOCKED."""
    src = Source(
        id="S001",
        title="MITRE ATT&CK Enterprise v15",
        authors=["MITRE"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="MITRE ATT&CK defines T1490 as Inhibit System Recovery.",
        freshness=SourceFreshness(
            source_version="v15",
            freshness_status=FreshnessStatus.SUPERSEDED,
            superseded_by="v19.2",
            authority_family="MITRE ATT&CK",
        ),
    )
    claim = Claim(
        id="C001",
        text="MITRE ATT&CK v19.2 defines T1490 as Inhibit System Recovery.",
        claim_type=ClaimType.FACTUAL,
        target_version="v19.2",
        target_family="MITRE ATT&CK",
    )
    severity, finding = evaluate_source_freshness_for_claim(claim, src)
    assert severity == FreshnessSeverity.BLOCKED
    assert finding is not None
    assert "does not match explicitly requested version 'v19.2'" in finding.reason

    # End-to-end verifier check: claim becomes UNSUPPORTED because of version mismatch
    doc = Document.parse("MITRE ATT&CK v19.2 defines T1490 as Inhibit System Recovery (S001).")
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(doc, [src])
    assert summary.unsupported_claims == 1
    assert summary.supported_claims == 0
    assert summary.status == "BLOCKED"
    assert len(summary.freshness_findings) == 1
    assert summary.freshness_findings[0].severity == FreshnessSeverity.BLOCKED


def test_superseded_by_appears_in_diagnostics():
    """Test 12: superseded_by appears in diagnostics and human-readable warnings."""
    finding = FreshnessFinding(
        source_id="S001",
        claim_id="C001",
        freshness_status=FreshnessStatus.SUPERSEDED,
        severity=FreshnessSeverity.NEEDS_REVIEW,
        reason="Current-state claim supported by superseded authority",
        source_title="NIST SP 800-61 Rev. 2",
        source_version="Rev. 2",
        superseded_by="NIST SP 800-61 Rev. 3",
        claim_text="NIST currently recommends...",
        action="Review the claim against the current revision (NIST SP 800-61 Rev. 3).",
    )
    diagnostic = finding.render_diagnostic()
    assert "Source:" in diagnostic
    assert "NIST SP 800-61 Rev. 2" in diagnostic
    assert "Status:\nSUPERSEDED" in diagnostic
    assert "Superseded by:\nNIST SP 800-61 Rev. 3" in diagnostic
    assert "Affected claim:\n\"NIST currently recommends...\"" in diagnostic
    assert "Action:\nReview the claim against the current revision" in diagnostic


# ==============================================================================
# PHASE 14: 13-15 Readiness Integration
# ==============================================================================

def test_pipeline_readiness_demoted_by_superseded_source_on_current_claim(tmp_path, monkeypatch):
    """Test 13: SUPERSEDED source on current-state claim produces NEEDS_REVIEW readiness."""
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = AssignmentSpec(
        title="Incident Response Architecture",
        topic="Evaluate current incident response methodologies.",
        target_words=50,
        word_tolerance_percent=50.0,
        source_requirements=dict(minimum_sources=1),
        outline=["Overview", "Guidance"],
    )
    src = Source(
        id="S001",
        title="NIST SP 800-61 Rev. 2",
        authors=["NIST"],
        retrieved_text="Current incident response guidance recommends structured preparation and containment phases.",
        evidence_depth=DEPTH_FULL_TEXT,
        freshness=SourceFreshness(
            source_version="Rev. 2",
            freshness_status=FreshnessStatus.SUPERSEDED,
            superseded_by="NIST SP 800-61 Rev. 3",
        ),
    )
    body = """# Incident Response Architecture

## Overview
Current incident response guidance recommends structured preparation and containment phases (S001).

## Guidance
Incident handling relies on coordinated remediation and verification across host endpoints.
"""
    backend = _make_fake_backend(
        body,
        claims_made=[{
            "claim": "Current incident response guidance recommends structured preparation and containment phases",
            "source_id": "S001",
        }],
    )

    res = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[src],
        custom_backend=backend,
    )
    assert res.report.status == "NEEDS_REVIEW"
    assert res.report.freshness_warnings is not None and res.report.freshness_warnings >= 1
    assert len(res.report.freshness_findings) >= 1
    assert res.report.freshness_findings[0]["superseded_by"] == "NIST SP 800-61 Rev. 3"
    assert "Source Freshness Warnings:" in res.report.render_text()


def test_pipeline_readiness_preserved_for_intentional_historical_source(tmp_path, monkeypatch):
    """Test 14: Intentional historical research does not degrade readiness."""
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = AssignmentSpec(
        title="Historical Incident Response Evolution",
        topic="Compare historical NIST incident response guidance with modern standards.",
        target_words=50,
        word_tolerance_percent=50.0,
        source_requirements=SourceRequirements(minimum_sources=1, allow_historical_sources=True),
        outline=["Overview", "Guidance"],
    )
    src = Source(
        id="S001",
        title="NIST SP 800-61 Revision 2",
        authors=["NIST"],
        retrieved_text="In 2012, NIST SP 800-61 Revision 2 established four primary incident response phases.",
        evidence_depth=DEPTH_FULL_TEXT,
        freshness=SourceFreshness(
            source_version="Revision 2",
            freshness_status=FreshnessStatus.SUPERSEDED,
            superseded_by="NIST SP 800-61 Revision 3",
            intentional_historical_use=True,
        ),
    )
    body = """# Historical Incident Response Evolution

## Overview
In 2012, NIST SP 800-61 Revision 2 established four primary incident response phases (S001).

## Guidance
Historical frameworks provided the foundation for modern cybersecurity standards and lifecycle guidance.
"""
    backend = _make_fake_backend(
        body,
        claims_made=[{
            "claim": "In 2012, NIST SP 800-61 Revision 2 established four primary incident response phases",
            "source_id": "S001",
            "intentional_historical_use": True,
        }],
    )

    res = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[src],
        custom_backend=backend,
    )
    assert res.report.status == "READY"
    assert res.report.freshness_warnings is None or res.report.freshness_warnings == 0
    assert len(res.report.freshness_findings) == 0


def test_pipeline_readiness_blocked_on_explicit_version_mismatch(tmp_path, monkeypatch):
    """Test 15: Version mismatch follows BLOCKED status."""
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = AssignmentSpec(
        title="ATT&CK Model Verification",
        topic="Verify specific ATT&CK v19.2 definitions.",
        target_words=50,
        word_tolerance_percent=50.0,
        source_requirements=dict(minimum_sources=1),
        outline=["Overview", "Analysis"],
    )
    src = Source(
        id="S001",
        title="MITRE ATT&CK Enterprise v15",
        authors=["MITRE"],
        retrieved_text="MITRE ATT&CK v15 categorizes T1490 as Inhibit System Recovery.",
        evidence_depth=DEPTH_FULL_TEXT,
        freshness=SourceFreshness(
            source_version="v15",
            freshness_status=FreshnessStatus.SUPERSEDED,
            superseded_by="v19.2",
            authority_family="MITRE ATT&CK",
        ),
    )
    body = """# ATT&CK Model Verification

## Overview
MITRE ATT&CK v19.2 defines T1490 as Inhibit System Recovery (S001).

## Analysis
Technique mappings require accurate framework versions and strict telemetry alignment.
"""
    backend = _make_fake_backend(
        body,
        claims_made=[{
            "claim": "MITRE ATT&CK v19.2 defines T1490 as Inhibit System Recovery",
            "source_id": "S001",
        }],
    )

    res = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[src],
        custom_backend=backend,
    )
    assert res.report.status == "BLOCKED"
    assert any(f["severity"] == "BLOCKED" for f in res.report.freshness_findings)


# ==============================================================================
# PHASE 14: 16-20 Pipeline & Evidence Independence & Privacy
# ==============================================================================

def test_freshness_survives_source_evidence_claim_verification():
    """Test 16: Freshness metadata survives source -> evidence -> claim verification."""
    src = Source(
        id="S001",
        title="Modern Authorization Models",
        authors=["Author"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="Dynamic authorization reduces token privileges by 42%.",
        freshness=SourceFreshness(
            source_version="v2",
            freshness_status=FreshnessStatus.CURRENT,
            published_at="2026-01-01",
            retrieved_at="2026-08-01",
        ),
    )
    doc = Document.parse("Dynamic authorization reduces token privileges by 42% (S001).")
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(
        doc,
        [src],
        stated_claims=[{"claim": "Dynamic authorization reduces token privileges by 42%."}],
    )

    # Provenance graph retains source freshness intact
    stored_source = graph.sources["S001"]
    assert stored_source.freshness.freshness_status == FreshnessStatus.CURRENT
    assert stored_source.freshness.source_version == "v2"

    ev = graph.evidence[0]
    assert ev.source_id == "S001"
    assert ev.supports is True
    assert "Corroborated by Modern Authorization Models" in ev.notes


def test_existing_papers_without_freshness_metadata_still_function(tmp_path, monkeypatch):
    """Test 17: Existing papers without freshness metadata still pass with zero false alarms."""
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = AssignmentSpec(
        title="General Computer Systems",
        topic="Overview of operating systems concepts.",
        target_words=50,
        word_tolerance_percent=50.0,
        source_requirements=dict(minimum_sources=1),
        outline=["Overview", "Architecture"],
    )
    # Legacy source with no freshness
    src = Source(
        id="S001",
        title="Operating System Concepts",
        authors=["Silberschatz, Abraham"],
        retrieved_text="An operating system manages computer hardware and software resources.",
        evidence_depth=DEPTH_FULL_TEXT,
    )
    body = """# General Computer Systems

## Overview
An operating system manages computer hardware and software resources (S001).

## Architecture
Virtual memory provides an abstraction of physical RAM across isolated address spaces.
"""
    backend = _make_fake_backend(
        body,
        claims_made=[{
            "claim": "An operating system manages computer hardware and software resources",
            "source_id": "S001",
        }],
    )

    res = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[src],
        custom_backend=backend,
    )
    assert res.report.status == "READY"
    assert res.report.freshness_warnings is None or res.report.freshness_warnings == 0


def test_evidence_depth_remains_independent_of_freshness():
    """Test 18: Evidence depth (e.g. FULL_TEXT vs METADATA_ONLY) is orthogonal to freshness."""
    # Source A: FULL_TEXT + SUPERSEDED
    s_full_superseded = Source(
        id="S001",
        title="Old Full Spec",
        authors=["Author"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="Full technical text of the deprecated specification.",
        freshness=SourceFreshness(freshness_status=FreshnessStatus.SUPERSEDED),
    )
    # Source B: METADATA_ONLY + CURRENT
    s_meta_current = Source(
        id="S002",
        title="Current Standard Metadata",
        authors=["Author"],
        evidence_depth=DEPTH_METADATA_ONLY,
        retrieved_text="Published in 2026.",
        freshness=SourceFreshness(freshness_status=FreshnessStatus.CURRENT),
    )

    assert s_full_superseded.is_substantive_evidence is True
    assert s_full_superseded.freshness.freshness_status == FreshnessStatus.SUPERSEDED

    assert s_meta_current.is_substantive_evidence is False
    assert s_meta_current.freshness.freshness_status == FreshnessStatus.CURRENT


def test_freshness_finding_serializes_and_roundtrips():
    """Test 19: FreshnessFinding serialization and deserialization."""
    finding = FreshnessFinding(
        source_id="S001",
        claim_id="C001",
        freshness_status=FreshnessStatus.SUPERSEDED,
        severity=FreshnessSeverity.NEEDS_REVIEW,
        reason="Current-state claim supported by superseded authority",
        source_title="NIST SP 800-61 Rev. 2",
        source_version="Rev. 2",
        superseded_by="NIST SP 800-61 Rev. 3",
        claim_text="Current guidance recommends X.",
        action="Review the claim against the current revision or mark this citation as intentional historical use.",
    )
    d = finding.to_dict()
    assert d["freshness_status"] == "SUPERSEDED"
    assert d["severity"] == "NEEDS_REVIEW"
    assert d["superseded_by"] == "NIST SP 800-61 Rev. 3"

    json_str = finding.to_json()
    parsed = json.loads(json_str)
    assert parsed["source_id"] == "S001"

    rebuilt = FreshnessFinding.from_dict(parsed)
    assert rebuilt.freshness_status == FreshnessStatus.SUPERSEDED
    assert rebuilt.severity == FreshnessSeverity.NEEDS_REVIEW
    assert rebuilt.superseded_by == "NIST SP 800-61 Rev. 3"


def test_no_machine_specific_path_leakage_in_freshness_findings():
    """Test 20: Diagnostics and findings do not leak local file paths."""
    finding = FreshnessFinding(
        source_id="S001",
        claim_id="C001",
        freshness_status=FreshnessStatus.SUPERSEDED,
        severity=FreshnessSeverity.NEEDS_REVIEW,
        reason="Current-state claim supported by superseded authority",
        source_title="Framework Guide",
        source_version="2",
        superseded_by="3",
        claim_text="Current guidance recommends X.",
        action="Review the claim against the current revision.",
    )
    diag = finding.render_diagnostic()
    assert "/home/" not in diag
    assert "/media/" not in diag
    assert "C:\\" not in diag
    assert "/var/" not in diag


# ==============================================================================
# PHASE 15: REGRESSION TEST THE LAB 01 CLASS OF FAILURE
# ==============================================================================

def test_regression_lab_01_superseded_authority_failure_class():
    """Regression test: Paper cites Framework v2 when Framework v3 is current.

    Case 1: Paper claim asserts 'Current guidance recommends X.' -> NEEDS_REVIEW.
    Case 2: Paper claim asserts 'In Framework v2, guidance recommended X.' -> PASS.
    """
    src = Source(
        id="S001",
        title="Framework Specification v2",
        authors=["Standards Body"],
        evidence_depth=DEPTH_FULL_TEXT,
        retrieved_text="Framework v2 guidance recommended mandatory multi-factor authentication for administrative accounts.",
        freshness=SourceFreshness(
            source_version="v2",
            freshness_status=FreshnessStatus.SUPERSEDED,
            superseded_by="Framework Specification v3",
            authority_family="Framework",
        ),
    )

    # Case 1: Unqualified current-state assertion
    doc1 = Document.parse("Current guidance recommends mandatory multi-factor authentication for administrative accounts (S001).")
    verifier = AcademicVerifier()
    _, summary1 = verifier.build_provenance_and_verify(
        doc1,
        [src],
        stated_claims=[{"claim": "Current guidance recommends mandatory multi-factor authentication for administrative accounts."}],
    )
    assert summary1.status == "NEEDS_REVIEW"
    assert len(summary1.freshness_findings) == 1
    assert summary1.freshness_findings[0].severity == FreshnessSeverity.NEEDS_REVIEW
    assert summary1.freshness_findings[0].superseded_by == "Framework Specification v3"

    # Case 2: Explicit historical context
    doc2 = Document.parse("In Framework v2, guidance recommended mandatory multi-factor authentication for administrative accounts (S001).")
    _, summary2 = verifier.build_provenance_and_verify(
        doc2,
        [src],
        stated_claims=[{
            "claim": "In Framework v2, guidance recommended mandatory multi-factor authentication for administrative accounts.",
            "temporal_context": "HISTORICAL",
        }],
    )
    assert summary2.status == "PASS"
    assert len(summary2.freshness_findings) == 0


def test_helper_version_and_family_extraction():
    """Verify version and family extraction logic on common authority formats."""
    assert extract_version_and_family("MITRE ATT&CK v19.2 defines T1490") == ("MITRE ATT&CK", "v19.2")
    assert extract_version_and_family("ATT&CK v15 categorized this behavior") == ("MITRE ATT&CK", "v15")
    assert extract_version_and_family("NIST SP 800-61 Rev. 2 guidelines") == ("NIST", "Rev. 2")
    assert extract_version_and_family("Framework v3 guidance") == ("Framework", "v3")
    assert extract_version_and_family("Rclone is a tool") == (None, None)

    assert normalize_version("v19.2") == "19.2"
    assert normalize_version("19.2") == "19.2"
    assert normalize_version("Rev. 2") == "2"
    assert normalize_version("Revision 3") == "3"


def test_classify_claim_temporal_context():
    """Verify temporal context classification for claims."""
    ctx, ver, fam = classify_claim_temporal_context("Current guidance recommends mandatory MFA.")
    assert ctx == ClaimTemporalContext.CURRENT_STATE

    ctx, ver, fam = classify_claim_temporal_context("In 2012, NIST recommended four phases.")
    assert ctx == ClaimTemporalContext.HISTORICAL

    ctx, ver, fam = classify_claim_temporal_context("MITRE ATT&CK v19.2 defines T1490.")
    assert ctx == ClaimTemporalContext.VERSION_SPECIFIC
    assert fam == "MITRE ATT&CK"
    assert ver == "v19.2"

    ctx, ver, fam = classify_claim_temporal_context("Operating systems manage memory.")
    assert ctx == ClaimTemporalContext.TIME_INSENSITIVE

