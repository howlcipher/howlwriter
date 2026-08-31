"""Tests for academic outline conformance checking."""

from howlwriter.academic.outline import check_outline_conformance
from howlwriter.domain.document import Document


def test_outline_conformance_full_pass():
    doc_text = """# Zero Trust and Autonomous AI Agents

## Introduction
Autonomous AI agents represent an emerging paradigm in automated systems.

## Identity Challenges for Autonomous Agents
Agents lack traditional interactive authentication credentials.

## Delegated Authorization
OAuth on-behalf-of workflows introduce token management challenges.

## Excessive and Stale Permissions
Agents accumulate broad capabilities over time.

## Security Controls and Remediation
Least-privilege scoping mitigates ambient authority risks.

## Conclusion
Comprehensive telemetry and bounded lifetimes ensure verifiable posture.
"""
    outline = [
        "Introduction",
        "Identity Challenges for Autonomous Agents",
        "Delegated Authorization",
        "Excessive and Stale Permissions",
        "Security Controls and Remediation",
        "Conclusion",
    ]

    doc = Document.parse(doc_text)
    result = check_outline_conformance(doc, outline)

    assert result.status == "PASS"
    assert result.required_topics_count == 6
    assert result.present_topics_count == 6
    for tr in result.topic_results:
        assert tr.status == "PASS"


def test_outline_conformance_missing_topic_fails():
    doc_text = """# Paper Title

## Introduction
Overview text.

## Identity Challenges
Identity discussion.

## Conclusion
Final remarks.
"""
    outline = [
        "Introduction",
        "Identity Challenges",
        "Delegated Authorization Mechanisms",  # Missing in text
        "Security Controls",                   # Missing in text
        "Conclusion",
    ]

    doc = Document.parse(doc_text)
    result = check_outline_conformance(doc, outline)

    assert result.status == "FAIL"
    assert result.required_topics_count == 5
    assert result.present_topics_count == 3

    missing_topics = [tr.topic for tr in result.topic_results if tr.status == "FAIL"]
    assert "Delegated Authorization Mechanisms" in missing_topics
    assert "Security Controls" in missing_topics
