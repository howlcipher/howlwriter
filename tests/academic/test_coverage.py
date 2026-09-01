"""Tests for minimum-sufficient-coverage checking of explicit requirements."""

from howlwriter.academic.coverage import check_requirements_coverage
from howlwriter.domain.document import Document


def test_requirement_detected_when_content_present():
    doc_text = """# Attack Chain Analysis

## Chain One: Leaked Cloud Credentials

The actor discovered long-lived AWS access keys committed to a public
repository. Tools such as Pacu and the AWS CLI were used for discovery.
Defensive telemetry includes CloudTrail logging and GuardDuty anomaly
detection for unusual API calls tied to the compromised credentials.
"""
    doc = Document.parse(doc_text)
    requirements = ["Include tools and defensive telemetry"]
    result = check_requirements_coverage(doc, requirements)

    assert result.status == "PASS"
    assert result.required_count == 1
    assert result.present_count == 1
    assert result.requirement_results[0].status == "PASS"


def test_requirement_flagged_when_absent():
    doc_text = """# Attack Chain Analysis

## Chain One: Leaked Cloud Credentials

The actor discovered long-lived AWS access keys committed to a public
repository and used them to authenticate to the AWS console.
"""
    doc = Document.parse(doc_text)
    requirements = ["Describe defensive telemetry and detection opportunities for each stage"]
    result = check_requirements_coverage(doc, requirements)

    assert result.status == "FAIL"
    assert result.required_count == 1
    assert result.present_count == 0
    assert result.requirement_results[0].status == "FAIL"


def test_empty_requirements_pass_trivially():
    doc = Document.parse("# Title\n\nSome body text.")
    result = check_requirements_coverage(doc, [])
    assert result.status == "PASS"
    assert result.required_count == 0
    assert result.present_count == 0
