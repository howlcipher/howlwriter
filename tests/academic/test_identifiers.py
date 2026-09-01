"""Tests for unsupported-specificity / technical-identifier grounding checks."""

from howlwriter.academic.identifiers import find_ungrounded_identifiers


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
