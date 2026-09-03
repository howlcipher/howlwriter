"""Comprehensive deterministic tests for Academic Semantic Grounding & Provenance Truthfulness Remediation v1."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import pytest

from howlwriter.academic.ai_disclosure import build_ai_use_statement
from howlwriter.academic.attack import (
    AttackKnowledgeBase,
    AttackSemanticValidation,
    AttackTechniqueRecord,
    validate_attack_mapping,
)
from howlwriter.academic.consistency import (
    ConsistencyFinding,
    ConsistencyReviewResult,
    RealModelConsistencyReviewer,
)
from howlwriter.academic.detection_coverage import (
    DetectionObservabilityStatus,
    TechniqueDetectionCoverage,
    TechniqueDetectionSummary,
    evaluate_technique_detection_coverage,
)
from howlwriter.academic.telemetry import (
    TelemetryEvidence,
    find_telemetry_mismatches_in_text,
    validate_telemetry_evidence,
)
from howlwriter.academic.verifier import AcademicVerifier
from howlwriter.domain.claim import Claim, ClaimType, VerificationStatus
from howlwriter.domain.document import Document
from howlwriter.domain.generation_provenance import (
    ContributionSummary,
    GenerationProvenance,
    ModelCallRecord,
    ReviewerFallbackRecord,
    redact,
    sanitize_voice_profile_ref,
)
from howlwriter.domain.outline import (
    NodeKind,
    NodeOrigin,
    Outline,
    OutlineNode,
)
from howlwriter.domain.source import (
    DEPTH_ABSTRACT,
    DEPTH_FULL_TEXT,
    DEPTH_METADATA_ONLY,
    DEPTH_PARTIAL_TEXT,
    DEPTH_UNAVAILABLE,
    FreshnessStatus,
    Source,
    SourceFreshness,
    source_from_dict,
)
from howlwriter.facts.extraction import HeuristicClaimExtractor
from howlwriter.provenance.assemble import (
    build_contribution,
    finalize,
    write_artifacts,
)
from howlwriter.review.meaning import (
    MeaningDiff,
    RealModelMeaningReviewer,
    SemanticMeaningResult,
)
from howlwriter.voice.diagnostics import (
    compute_voice_diagnostics,
    diagnose_voice_drift,
)


# ==============================================================================
# 1. ATT&CK Semantic Grounding & Regression Cases
# ==============================================================================

def test_attack_semantic_grounding_separate_facets():
    """Validates that identifier existence alone does NOT grant semantic pass."""
    val = validate_attack_mapping(
        technique_id="T1070.004",
        context_text="The adversary engaged in network reconnaissance across subnets.",
        claimed_name="Indicator Removal: File Deletion",
        claimed_tactic="Defense Evasion",
    )
    assert val.identifier_exists is True
    assert val.name_matches is True
    assert val.tactic_matches is True
    # Reconnaissance does not match file deletion behaviors
    assert val.behavior_matches is False
    assert val.semantic_verdict == "FAIL"
    assert val.is_verified is False


def test_regression_timestomping_not_folded_into_file_deletion():
    """T1070.004 must not absorb timestomping (T1070.006) without flagging."""
    val = validate_attack_mapping(
        technique_id="T1070.004",
        context_text="The attacker executed file deletion using sdelete and timestomped file creation times.",
        all_mapped_techniques=["T1070.004"],
    )
    assert val.identifier_exists is True
    assert val.behavior_matches is False
    assert "timestomp" in val.unmapped_behaviors
    assert "T1070.006" in val.suggested_techniques
    assert val.semantic_verdict == "FAIL"

    # When T1070.006 is also mapped, T1070.004 passes its own scope
    val_fixed = validate_attack_mapping(
        technique_id="T1070.004",
        context_text="The attacker executed file deletion using sdelete and timestomped file creation times.",
        all_mapped_techniques=["T1070.004", "T1070.006"],
    )
    assert val_fixed.semantic_verdict == "PASS"


def test_regression_shadow_copy_deletion_not_folded_into_encryption():
    """T1486 (Data Encrypted) must not absorb shadow copy deletion (T1490)."""
    val = validate_attack_mapping(
        technique_id="T1486",
        context_text="The ransomware encrypted victim files and deleted volume shadow copies via vssadmin.",
        all_mapped_techniques=["T1486"],
    )
    assert val.identifier_exists is True
    assert val.behavior_matches is False
    assert any("shadow" in u for u in val.unmapped_behaviors)
    assert "T1490" in val.suggested_techniques
    assert val.semantic_verdict == "FAIL"

    val_both = validate_attack_mapping(
        technique_id="T1486",
        context_text="The ransomware encrypted victim files and deleted volume shadow copies via vssadmin.",
        all_mapped_techniques=["T1486", "T1490"],
    )
    assert val_both.semantic_verdict == "PASS"


def test_regression_code_repository_vs_text_storage():
    """T1567.001 (Code Repo) must not absorb Pastebin text storage (T1567.003)."""
    val = validate_attack_mapping(
        technique_id="T1567.001",
        context_text="Sensitive tokens were exfiltrated to GitHub and posted to Pastebin.",
        all_mapped_techniques=["T1567.001"],
    )
    assert val.identifier_exists is True
    assert val.behavior_matches is False
    assert "pastebin" in val.unmapped_behaviors
    assert "T1567.003" in val.suggested_techniques
    assert val.semantic_verdict == "FAIL"


def test_attack_authoritative_source_model():
    """Technique mapping retains official URL, version, and supported semantic facts."""
    kb = AttackKnowledgeBase()
    rec = kb.get_record("T1070.004")
    assert rec is not None
    assert rec.url == "https://attack.mitre.org/techniques/T1070/004/"
    assert rec.version == "2.1"
    assert rec.last_modified == "2024-03-28"
    assert len(rec.supported_semantic_facts) > 0


# ==============================================================================
# 2. Telemetry Semantic Validation
# ==============================================================================

def test_telemetry_pairing_validation_detects_sysmon_7045_mismatch():
    """Event ID 7045 belongs to Windows System Log (SCM), not Sysmon."""
    ev = TelemetryEvidence(
        product_or_source="Sysmon",
        channel_or_log="Microsoft-Windows-Sysmon/Operational",
        event_identifier="7045",
        described_behavior="Service Creation",
    )
    validated = validate_telemetry_evidence(ev)
    assert validated.validation_status == "MISMATCH"
    assert "Service Control Manager" in validated.notes

    # Valid pairing
    ev_correct = TelemetryEvidence(
        product_or_source="Windows System Log",
        channel_or_log="System",
        event_identifier="7045",
        described_behavior="Service Creation",
    )
    assert validate_telemetry_evidence(ev_correct).validation_status == "VALID"


def test_find_telemetry_mismatches_in_text():
    text = "The service installation was recorded as Sysmon Event ID 7045 in host telemetry."
    mismatches = find_telemetry_mismatches_in_text(text)
    assert len(mismatches) == 1
    assert "associates Windows Event ID 7045 with Sysmon" in mismatches[0]


# ==============================================================================
# 3. Technique-Specific Detection Coverage
# ==============================================================================

def test_technique_detection_coverage_statuses():
    doc_text = """# Attack Analysis

## External Reconnaissance
Active scanning under T1595.002 occurred from external hosts outside the defended boundary with 0 internal host telemetry.

## Persistence
Under T1543.003, adversaries established a malicious Windows Service. EDR sensor alerts and Windows System event ID 7045 captured the service creation.

## Command and Control
Under T1071.001, beaconing over HTTPS occurred, showing partially observable asymmetric outbound flow and high jitter.

## Execution
PowerShell scripts executed under T1059.001 to invoke downstream payloads.
"""
    doc = Document.parse(doc_text)
    techniques = ["T1595.002", "T1543.003", "T1071.001", "T1059.001"]
    summary = evaluate_technique_detection_coverage(doc, techniques)

    assert summary.technique_coverages["T1595.002"].status == DetectionObservabilityStatus.NOT_DIRECTLY_OBSERVABLE
    assert summary.technique_coverages["T1543.003"].status == DetectionObservabilityStatus.DETECTABLE_WITH_MAPPING
    assert summary.technique_coverages["T1071.001"].status == DetectionObservabilityStatus.PARTIALLY_OBSERVABLE
    assert summary.technique_coverages["T1059.001"].status == DetectionObservabilityStatus.MISSING_DETECTION
    assert summary.status == "FAIL"
    assert "T1059.001" in summary.missing_techniques


# ==============================================================================
# 4. Source Freshness & Evidence Depth
# ==============================================================================

def test_source_freshness_metadata_deserialization():
    raw = {
        "id": "S001",
        "title": "Adversary Tactics",
        "authors": ["Analyst A"],
        "retrieved_text": "Sample text",
        "evidence_depth": "FULL_TEXT",
        "freshness": {
            "retrieved_at": "2026-08-01",
            "published_at": "2024-01-01",
            "source_version": "v15",
            "freshness_status": "CURRENT",
        },
    }
    src = source_from_dict(raw)
    assert src.freshness.freshness_status == FreshnessStatus.CURRENT
    assert src.freshness.source_version == "v15"
    assert src.freshness.retrieved_at == "2026-08-01"


def test_evidence_depth_hierarchy_and_substantive_check():
    s_full = Source(id="S1", title="Full", authors=["A"], evidence_depth=DEPTH_FULL_TEXT, retrieved_text="Some text")
    s_partial = Source(id="S2", title="Partial", authors=["A"], evidence_depth=DEPTH_PARTIAL_TEXT, retrieved_text="Some text")
    s_abstract = Source(id="S3", title="Abstract", authors=["A"], evidence_depth=DEPTH_ABSTRACT, retrieved_text="Abstract text")
    s_meta = Source(id="S4", title="Meta", authors=["A"], evidence_depth=DEPTH_METADATA_ONLY, retrieved_text="Metadata")
    s_unavail = Source(id="S5", title="Unavail", authors=["A"], evidence_depth=DEPTH_UNAVAILABLE, retrieved_text="")

    assert s_full.is_substantive_evidence is True
    assert s_partial.is_substantive_evidence is True
    assert s_abstract.is_substantive_evidence is True
    assert s_meta.is_substantive_evidence is False
    assert s_unavail.is_substantive_evidence is False


def test_verifier_rejects_page_claims_from_abstract():
    verifier = AcademicVerifier()
    source = Source(
        id="S01",
        title="Token Privileges",
        authors=["Author A"],
        evidence_depth=DEPTH_ABSTRACT,
        retrieved_text="Dynamic delegated authorization reduces stale token privileges by 42%.",
    )
    doc = Document.parse("Dynamic delegated authorization reduces stale token privileges by 42% as described on page 45.")
    graph, summary = verifier.verify(doc, [source])
    # The claim mentions page 45 but source depth is only ABSTRACT
    assert summary.unsupported_claims == 1
    assert summary.supported_claims == 0


def test_verifier_rejects_direct_quotations_from_abstract():
    verifier = AcademicVerifier()
    source = Source(
        id="S01",
        title="Token Privileges",
        authors=["Author A"],
        evidence_depth=DEPTH_ABSTRACT,
        retrieved_text="Dynamic delegated authorization reduces stale token privileges by 42%.",
    )
    doc = Document.parse('As noted by Author A, "Dynamic delegated authorization reduces stale token privileges".')
    graph, summary = verifier.verify(doc, [source])
    assert len(summary.quotation_warnings) == 1
    assert "was not found verbatim in any retrieved source" in summary.quotation_warnings[0]


# ==============================================================================
# 5. Document Segmentation & References Claim Exclusion
# ==============================================================================

def test_document_segmentation_excludes_references_from_claims():
    text = """# Introduction

In 2024, approximately 65% of ransomware attacks leveraged PowerShell.

# References

Anson, S. (2020). Applied Incident Response (2nd ed., p. 142). Wiley.
Strom, B. (2018). MITRE ATT&CK: Design and philosophy (Tech. Rep. 18-0101). MITRE.

# Appendix: Generation Provenance

The model ran 4 completion steps with 98% accuracy.
"""
    doc = Document.parse(text)
    extractor = HeuristicClaimExtractor()

    body_claims = extractor.extract(doc, include_non_body=False)
    all_claims = extractor.extract(doc, include_non_body=True)

    # Body claims must only flag the introduction sentence
    assert len(body_claims) == 1
    assert "65% of ransomware" in body_claims[0].text

    # All claims would erroneously flag the references and provenance numbers
    assert len(all_claims) >= 3


# ==============================================================================
# 6. Provenance Origin Taxonomy & Contribution Summary
# ==============================================================================

def test_provenance_origin_taxonomy_and_contribution_metrics():
    outline = Outline(
        title="Test Paper",
        nodes=[
            OutlineNode(
                id="N1",
                kind=NodeKind.THESIS,
                origin=NodeOrigin.USER_AUTHORED.value,
                text="User thesis statement with eight distinct human supplied words.",
            ),
            OutlineNode(
                id="N2",
                kind=NodeKind.CLAIM,
                origin=NodeOrigin.MODEL_DERIVED_OUTLINE.value,
                text="Model derived claim asserting synthetic attack vector.",
            ),
            OutlineNode(
                id="N3",
                kind=NodeKind.EXPAND,
                origin=NodeOrigin.ASSIGNMENT_SOURCE.value,
                text="Assignment required point: analyze lateral movement.",
            ),
        ],
    )
    # Supplied words should count ONLY user authored nodes
    assert outline.supplied_words() == 9
    assert len(outline.human_claims()) == 1
    assert len(outline.model_derived_nodes()) == 1

    contrib = build_contribution(
        outline,
        coverage={"required_represented": 1, "findings": [{"node_id": "N1", "status": "PRESENT"}]},
        artifact_text="A paper with fifty total generated words in the completed draft artifact.",
    )
    assert contrib.human_authored_words == 9
    assert contrib.user_words_supplied == 9
    assert contrib.human_claims == 1
    assert contrib.assignment_derived_requirements == 1
    assert contrib.model_derived_outline_nodes == 1
    assert contrib.model_created_claims == 1
    assert contrib.model_generated_prose_words == (contrib.artifact_words - 9)


# ==============================================================================
# 7. AI-Use Disclosure Truthfulness
# ==============================================================================

def test_ai_use_disclosure_model_derived_outline_scenario():
    """Lab 01 scenario: human provided assignment, model derived outline and prose."""
    prov = GenerationProvenance(
        run_id="run-1",
        workflow="academic",
        outline_present=True,
        generation_freedom="LOW",
        calls=[ModelCallRecord(role="writer", provider="test", model="test")],
        contribution=ContributionSummary(
            artifact_words=1500,
            user_words_supplied=0,
            human_authored_words=0,
            human_claims=0,
            assignment_derived_requirements=4,
            model_derived_outline_nodes=12,
            model_created_claims=6,
        ),
    )
    stmt = build_ai_use_statement(prov)
    assert stmt.used_generative_ai is True
    # Must NOT claim author supplied thesis/claims
    assert "The author supplied the thesis, the argument structure" not in stmt.text
    assert "The assignment requirements were supplied by the user." in stmt.text
    assert "Model-backed roles derived a detailed outline and attack scenarios" in stmt.text


def test_ai_use_disclosure_human_authored_outline_scenario():
    prov = GenerationProvenance(
        run_id="run-2",
        workflow="academic",
        outline_present=True,
        generation_freedom="LOW",
        calls=[ModelCallRecord(role="writer", provider="test", model="test")],
        contribution=ContributionSummary(
            artifact_words=1000,
            user_words_supplied=250,
            human_authored_words=250,
            human_claims=5,
            required_points_supplied=5,
            required_points_represented=5,
            model_derived_outline_nodes=0,
        ),
    )
    stmt = build_ai_use_statement(prov)
    assert "HowlWriter expanded the author's outline into prose." in stmt.text
    assert "The author supplied 5 claim(s)" in stmt.text


def test_ai_use_disclosure_minimal_user_draft_scenario():
    prov = GenerationProvenance(
        run_id="run-3",
        workflow="academic",
        outline_present=True,
        generation_freedom="MINIMAL",
        calls=[ModelCallRecord(role="writer", provider="test", model="test")],
        contribution=ContributionSummary(
            artifact_words=2000,
            user_words_supplied=1900,
            human_authored_words=1900,
            human_claims=10,
        ),
    )
    stmt = build_ai_use_statement(prov)
    assert "The author supplied a near-complete draft. Model assistance was limited to editing" in stmt.text


def test_ai_use_disclosure_mixed_outline_scenario():
    prov = GenerationProvenance(
        run_id="run-4",
        workflow="academic",
        outline_present=True,
        generation_freedom="MEDIUM",
        calls=[ModelCallRecord(role="writer", provider="test", model="test")],
        contribution=ContributionSummary(
            artifact_words=1200,
            user_words_supplied=150,
            human_authored_words=150,
            human_claims=2,
            model_derived_outline_nodes=6,
        ),
    )
    stmt = build_ai_use_statement(prov)
    assert "The author supplied core requirements and initial structure/claims, and model-backed roles derived additional outline sections" in stmt.text


# ==============================================================================
# 8. Privacy Redaction
# ==============================================================================

def test_privacy_redaction_paths_and_voice_profile():
    sample_text = """Generated with /home/howlcipher/.howlwriter/voices/william/profile.json.
Also inspected /var/home/jdoe/project/data.txt and C:\\Users\\Administrator\\secret\\keys.txt.
Token: ghp_123456789012345678901234567890 and JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID."""

    redacted = redact(sample_text, mask_paths=True, username="jdoe")
    assert "/home/howlcipher" not in redacted
    assert "/var/home/jdoe" not in redacted
    assert "C:\\Users\\Administrator" not in redacted
    assert "[VOICE_PROFILE:william]" in redacted
    assert "[REDACTED_TOKEN]" in redacted
    assert "[REDACTED_JWT]" in redacted
    assert "jdoe" not in redacted


def test_sanitize_voice_profile_ref():
    ref = sanitize_voice_profile_ref("/home/user/.howlwriter/voices/william/profile.json")
    assert isinstance(ref, dict)
    assert ref["alias"] == "william"
    assert "profile_hash" in ref
    assert "/home/" not in str(ref)


# ==============================================================================
# 9. Reviewer Fallback
# ==============================================================================

def test_reviewer_fallback_record_structure():
    rec = ReviewerFallbackRecord(
        stage="consistency_review",
        requested_reviewer="codex",
        failure_reason="Rate limit / quota exceeded (429)",
        fallback_reviewer="claude-3-5-sonnet",
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        independence_status="INDEPENDENT",
    )
    prov = GenerationProvenance(run_id="run-fb", reviewer_fallbacks=[rec])
    d = prov.to_dict()
    assert len(d["reviewer_fallbacks"]) == 1
    assert d["reviewer_fallbacks"][0]["requested_reviewer"] == "codex"
    assert d["reviewer_fallbacks"][0]["independence_status"] == "INDEPENDENT"


# ==============================================================================
# 10. Voice Diagnostics Constraint
# ==============================================================================

def test_voice_diagnostics_computation_and_drift():
    formal_text = (
        "Consequently, the empirical methodology demonstrates that dynamic authorization "
        "predominantly mitigates privilege escalation. Furthermore, systematic telemetry "
        "substantiates the architectural security guarantees."
    )
    diag = compute_voice_diagnostics(formal_text)
    assert diag.sentence_length_mean > 0
    assert diag.long_word_rate > 0.1
    assert diag.formality_score > 0

    informal_text = "Yeah, things are kinda cool and super awesome, totally lots of stuff."
    drift = diagnose_voice_drift(informal_text, diag)
    assert drift["drift"]["formality_drift"] < 0
