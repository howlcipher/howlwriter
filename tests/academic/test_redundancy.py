"""Tests for redundancy-aware compression detection."""

from howlwriter.academic.redundancy import detect_redundancy
from howlwriter.domain.document import Document


def test_near_duplicate_paragraphs_detected():
    doc_text = """# Attack Chain Report

## Chain One

The attacker obtained long-lived AWS access keys committed to a public
GitHub repository, then authenticated to the AWS API and enumerated IAM
permissions across the development account. The attacker subsequently used
the AWS command line interface to list accessible storage buckets and
identify overly permissive resource policies attached to the compromised
identity.

## Chain One Discussion

The attacker obtained long-lived AWS access keys committed to a public
GitHub repository, then authenticated to the AWS API and enumerated IAM
permissions across the development environment. The attacker subsequently
used the AWS command line interface to list accessible storage buckets and
identify overly permissive resource policies attached to the compromised
account.
"""
    doc = Document.parse(doc_text)
    result = detect_redundancy(doc)

    kinds = {f.kind for f in result.findings}
    assert "near_duplicate_paragraph" in kinds


def test_distinct_paragraphs_not_flagged():
    doc_text = """# Attack Chain Report

## Chain One

The attacker obtained long-lived AWS access keys committed to a public
repository and pivoted into the development account using the AWS CLI.

## Chain Two

A separate actor exploited a misconfigured Kubernetes RBAC policy to escalate
privileges within a production namespace and exfiltrate secrets from a
mounted service account token.
"""
    doc = Document.parse(doc_text)
    result = detect_redundancy(doc)

    kinds = {f.kind for f in result.findings}
    assert "near_duplicate_paragraph" not in kinds


def test_table_restatement_detected():
    doc_text = """# Attack Chains

| Stage | Tool | Telemetry |
| --- | --- | --- |
| Initial Access | Leaked AWS keys | CloudTrail anomalous API calls |
| Discovery | AWS CLI enumeration | GuardDuty IAM anomaly findings |

The actor used leaked AWS keys for initial access and then used the AWS CLI
for discovery. CloudTrail anomalous API calls and GuardDuty IAM anomaly
findings provide telemetry for both stages.
"""
    doc = Document.parse(doc_text)
    result = detect_redundancy(doc, table_restatement_threshold=0.5)

    kinds = {f.kind for f in result.findings}
    assert "table_restatement" in kinds


def test_table_followed_by_unrelated_prose_not_flagged():
    doc_text = """# Attack Chains

| Stage | Tool |
| --- | --- |
| Initial Access | Leaked AWS keys |

Meanwhile, defenders should prioritize rotating credentials and enabling
multi-factor authentication across all administrative accounts to reduce
blast radius from any single leaked secret.
"""
    doc = Document.parse(doc_text)
    result = detect_redundancy(doc)

    kinds = {f.kind for f in result.findings}
    assert "table_restatement" not in kinds
