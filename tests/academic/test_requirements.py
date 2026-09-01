"""Tests for requirement classification and the identifier-specificity
coverage override (academic/requirements.py)."""

from howlwriter.academic.coverage import check_requirements_coverage
from howlwriter.academic.requirements import (
    apply_identifier_specificity_overrides,
    classify_requirement,
    classify_requirements,
    is_identifier_fabrication_prohibition,
)
from howlwriter.domain.document import Document

# The actual CYBR-601 dogfood requirements list (dogfood/papers/
# paper_11_cybr601_attack_chains.yaml) -- the live scenario this milestone
# fixes: prohibition/style items no longer scored by word overlap.
_CYBR601_REQUIREMENTS = [
    "Include exactly three plausible attack chains, each in its own subsection.",
    "For each attack chain, map the relevant steps to MITRE ATT&CK tactics and techniques.",
    "For each attack chain, name representative tools an attacker or defender might use.",
    "For each attack chain, describe defensive telemetry and detection opportunities.",
    "Do not invent exact technical identifiers (e.g. specific CVE numbers, ATT&CK technique "
    "IDs, Windows Event IDs, or cloud provider finding names) unless grounded in the retrieved "
    "source evidence; generalize instead when precise identifiers are not available.",
    "Each attack chain must be logically consistent: a stage may not use a capability or "
    "access level before the earlier stage that is supposed to grant it.",
    "Keep the paper concise: approximately three-quarters of a page per attack chain is "
    "sufficient; avoid unnecessary elaboration, repeated explanations, and padding.",
]


def test_classify_requirement_buckets():
    assert classify_requirement("Support factual claims with citations") == "positive"
    assert (
        classify_requirement(
            "For each attack chain, map the relevant steps to MITRE ATT&CK tactics "
            "and techniques."
        )
        == "positive"
    )
    assert classify_requirement(_CYBR601_REQUIREMENTS[4]) == "prohibition"
    assert classify_requirement("Maximum 10 pages") == "length"
    assert classify_requirement(_CYBR601_REQUIREMENTS[6]) == "style"


def test_classify_requirements_matches_cybr601_dogfood_split():
    # 4 positive content items, 1 prohibition, 0 length, 1 style; the
    # consistency-sequencing item has no prohibition/length/style keyword
    # and stays positive (still validated separately by consistency.py --
    # this classification only controls coverage.py routing).
    result = classify_requirements(_CYBR601_REQUIREMENTS)
    assert len(result.positive) == 5
    assert len(result.prohibition) == 1
    assert len(result.length) == 0
    assert len(result.style) == 1
    assert _CYBR601_REQUIREMENTS[4] in result.prohibition
    assert _CYBR601_REQUIREMENTS[6] in result.style


def test_is_identifier_fabrication_prohibition_detects_known_subtype():
    assert is_identifier_fabrication_prohibition(_CYBR601_REQUIREMENTS[4])
    assert not is_identifier_fabrication_prohibition("Do not use first-person language.")


def test_apply_identifier_specificity_override_downgrades_when_ids_available_but_unused():
    doc_text = (
        "# Attack Chain Analysis\n\n"
        "## Chain One\n\n"
        "Each step of the attack maps to a MITRE tactic and technique category, "
        "though the paper does not cite a specific technique identifier."
    )
    doc = Document.parse(doc_text)
    requirement = "Map each step to MITRE ATT&CK technique IDs."

    coverage = check_requirements_coverage(doc, [requirement])
    assert coverage.requirement_results[0].status == "PASS"  # word overlap alone passes

    grounding_texts = ["Source excerpt discussing T1003.001 in detail."]
    overridden = apply_identifier_specificity_overrides(coverage, doc, grounding_texts)

    assert overridden.requirement_results[0].status == "FAIL"
    assert overridden.requirement_results[0].kind == "identifier_specificity"
    assert overridden.status == "FAIL"


def test_apply_identifier_specificity_override_noop_when_no_grounded_ids_available():
    doc_text = (
        "# Attack Chain Analysis\n\n"
        "## Chain One\n\n"
        "Each step of the attack maps to a MITRE tactic and technique category, "
        "though the paper does not cite a specific technique identifier."
    )
    doc = Document.parse(doc_text)
    requirement = "Map each step to MITRE ATT&CK technique IDs."

    coverage = check_requirements_coverage(doc, [requirement])
    assert coverage.requirement_results[0].status == "PASS"

    grounding_texts = ["Generic security monitoring guidance with no exact identifiers."]
    overridden = apply_identifier_specificity_overrides(coverage, doc, grounding_texts)

    assert overridden.requirement_results[0].status == "PASS"
    assert overridden.status == "PASS"
