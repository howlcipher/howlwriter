"""Tests for unsupported-specificity / technical-identifier grounding checks."""

from howlwriter.academic.identifiers import find_ungrounded_identifiers, identifier_kinds_present


def test_ungrounded_cve_flagged():
    document_text = (
        "The vulnerability was later cataloged as CVE-2024-31337 and patched "
        "in the following release."
    )
    findings = find_ungrounded_identifiers(document_text, grounding_texts=[])

    assert any(f.identifier == "CVE-2024-31337" for f in findings)


def test_grounded_identifier_not_flagged():
    document_text = "Researchers tracked the flaw as CVE-2024-31337 in their disclosure."
    grounding_texts = [
        "A detailed writeup of CVE-2024-31337 was published by the vendor's security team."
    ]
    findings = find_ungrounded_identifiers(document_text, grounding_texts)

    assert not any(f.identifier == "CVE-2024-31337" for f in findings)


def test_ungrounded_precise_percentage_flagged():
    document_text = "Beacon traffic exhibited 34.72% jitter to evade detection."
    findings = find_ungrounded_identifiers(document_text, grounding_texts=[])

    assert any(f.kind == "precise_percentage" for f in findings)


def test_round_percentage_not_flagged():
    document_text = "Roughly 50% of observed samples exhibited randomized beacon intervals."
    findings = find_ungrounded_identifiers(document_text, grounding_texts=[])

    assert not any(f.kind == "precise_percentage" for f in findings)


def test_identifier_grounded_via_requirements_text():
    # An identifier explicitly named in the assignment's own requirements/topic
    # text should never be flagged -- the assignment itself grounds it.
    document_text = "The lab specifically analyzes CVE-2024-31337 as a case study."
    findings = find_ungrounded_identifiers(
        document_text, grounding_texts=["Analyze CVE-2024-31337 as the primary case study."]
    )

    assert not any(f.identifier == "CVE-2024-31337" for f in findings)


def test_grounded_attck_technique_id_not_flagged():
    # A source-grounded ATT&CK technique ID must be preserved, not treated
    # as fabricated just because it's an exact, precise-looking identifier.
    document_text = "Adversaries used OS Credential Dumping: LSASS Memory (T1003.001)."
    grounding_texts = [
        "Source discusses OS Credential Dumping: LSASS Memory (T1003.001) in depth."
    ]
    findings = find_ungrounded_identifiers(document_text, grounding_texts)

    assert not any(f.identifier == "T1003.001" for f in findings)


def test_ungrounded_attck_technique_id_flagged():
    document_text = "Adversaries used OS Credential Dumping: LSASS Memory (T1003.001)."
    findings = find_ungrounded_identifiers(document_text, grounding_texts=[])

    assert any(f.identifier == "T1003.001" and f.kind == "mitre_attack_technique" for f in findings)


def test_ungrounded_cloud_finding_name_flagged():
    # The source only describes AWS monitoring generically; no exact
    # GuardDuty finding name was ever supplied, so a specific-looking
    # finding name in the document must be flagged as ungrounded.
    document_text = (
        "GuardDuty flagged UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration."
    )
    findings = find_ungrounded_identifiers(
        document_text,
        grounding_texts=["AWS monitoring may identify suspicious credential use."],
    )

    assert any(f.kind == "cloud_finding_name" for f in findings)


def test_identifier_kinds_present_reports_matching_kinds():
    assert identifier_kinds_present("Mapped to T1003.001") == {"mitre_attack_technique"}
    assert identifier_kinds_present("no identifiers here") == set()
    assert identifier_kinds_present("CVE-2024-31337 and T1003.001") == {
        "cve",
        "mitre_attack_technique",
    }
