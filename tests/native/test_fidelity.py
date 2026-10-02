"""Numbers must stay bound to what they count; scope must not silently grow."""

import pytest

from howlwriter.native.fidelity import compare, extract_quantities, worst_status

CICD = (
    "Executed and validated builds across all 28 repositories (27 passed, with the "
    "remaining failure diagnosed and logged); dry-run validated representative "
    "deployment paths for 25 of 28, with the remaining checks blocked by "
    "upstream/environment or tooling conditions."
)


def status(source, proposal, evidence=()):
    return compare(source, proposal, evidence=evidence).status


def codes(source, proposal, evidence=()):
    return [f.code for f in compare(source, proposal, evidence=evidence).findings]


def test_same_number_same_unit_is_preserved():
    assert status("Validated 25 of 28 repositories.", "Validated 25 of 28 repositories.") \
        == "FACTUALLY_PRESERVED"


def test_same_number_different_unit_is_unit_drift():
    # The Run 5 failure: both numbers survive, the noun they count does not.
    result = compare("Validated 25 of 28 repositories.", "Validated 25 of 28 deployment paths.")
    assert result.status == "FACTUAL_UNIT_DRIFT"
    assert [f.code for f in result.findings] == ["FACTUAL_UNIT_DRIFT"]


def test_run5_slash_form_drift_is_caught():
    assert status("Validated 25 of 28 repositories.", "Validated 25/28 deployment paths.") in {
        "FACTUAL_UNIT_DRIFT", "FACTUAL_CONFLICT"}
    found = codes("Validated 25 of 28 repositories.", "Validated 25/28 deployment paths.")
    assert "FACTUAL_UNIT_DRIFT" in found


def test_trailing_ratio_takes_unit_from_preceding_phrase():
    ratio = [q for q in extract_quantities(CICD) if q.kind == "ratio"][0]
    assert (ratio.value, ratio.unit) == ("25/28", "path")


def test_changed_denominator_is_conflict():
    assert "denominator_changed" in codes(CICD, "Dry-run validated 25 of 30 representative deployment paths.")


def test_derived_percentage_requires_review():
    assert status(CICD, "Dry-run validated 89% of representative deployment paths.") \
        == "FACTUAL_REVIEW_REQUIRED"


def test_unsupported_percentage_is_conflict():
    assert status(CICD, "Dry-run validated 95% of representative deployment paths.") \
        == "FACTUAL_CONFLICT"


def test_derived_ratio_from_two_counts_requires_review():
    source = "Executed and validated builds across all 28 repositories (27 passed)."
    assert codes(source, "27/28 builds validated") == ["derived_ratio"]


def test_ranges_must_match():
    assert status("Supported 3-5 teams.", "Supported 3-5 teams.") == "FACTUALLY_PRESERVED"
    assert status("Supported 3-5 teams.", "Supported 3-6 teams.") == "FACTUAL_CONFLICT"


def test_dates_must_match():
    assert status("Joined in 2021.", "Joined in 2021.") == "FACTUALLY_PRESERVED"
    assert "date_unsupported" in codes("Joined in 2021.", "Joined in 2019.")


def test_thousands_separator_counts_are_normalized():
    assert status(
        "A measured scan processed 2,832 files and identified 67 distinct exposed secrets "
        "in approximately 25 seconds.",
        "Scanned 2,832 files and found 67 exposed secrets in about 25 seconds.",
    ) == "FACTUALLY_PRESERVED"


@pytest.mark.parametrize("source,proposal,expected", [
    ("Built an internal .NET 8 Blazor app.", "Built an internal .NET 8 Blazor application.",
     "FACTUALLY_PRESERVED"),
    ("Built an internal .NET 8 Blazor app.", "Built an internal .NET 9 Blazor application.",
     "FACTUAL_CONFLICT"),
    ("Tooling in Python 3.12.", "Tooling in Python 3.12.", "FACTUALLY_PRESERVED"),
])
def test_versions_are_not_metrics(source, proposal, expected):
    assert status(source, proposal) == expected
    assert all(q.kind == "version" for q in extract_quantities(source))


def test_qualifier_drop_requires_review():
    assert codes(CICD, "Validated 25 of 28 deployment paths.") == [
        "qualifier_removed", "qualifier_removed"]


@pytest.mark.parametrize("source,proposal", [
    ("Dry-run validated 25 of 28 paths.", "Deployed 25 of 28 paths to production."),
    ("Built a proof of concept for config diffing.", "Built config diffing, shipped to production."),
    ("Investigated migrating builds to YAML.", "Migrated builds to YAML."),
    ("Shared team effort to build the CLI.", "Single-handedly built the CLI."),
])
def test_scope_upgrades_are_conflicts(source, proposal):
    assert status(source, proposal) == "FACTUAL_CONFLICT"


def test_azure_devops_does_not_become_azure_cloud():
    assert "azure_devops_to_azure_cloud" in codes(
        "56 Azure DevOps build/release definitions", "56 Azure build/release definitions")
    assert status("56 Azure DevOps build/release definitions",
                  "56 Azure DevOps build/release definitions") == "FACTUALLY_PRESERVED"


@pytest.mark.parametrize("proposal,code", [
    ("Built Python tooling on Kubernetes.", "technology_kubernetes"),
    ("Built Python tooling with Terraform.", "technology_terraform"),
    ("Built Python tooling used by 40 engineers.", "adoption_claim"),
    ("Built Python tooling that saved $40k.", "financial_claim"),
])
def test_unsupported_expansion_is_flagged(proposal, code):
    assert code in codes("Built Python tooling.", proposal)


def test_evidence_licenses_terms_absent_from_current_copy():
    assert status("Built the deployment CLI.", "Built the Go deployment CLI used in production.",
                  evidence=["Go-based self-service deployment CLI for production releases"]) \
        != "FACTUAL_CONFLICT"


def test_unsupported_number_is_conflict():
    assert "number_unsupported" in codes("Built the CLI.", "Built the CLI in 3 weeks.")


def test_omitted_numbers_are_reported_not_failed():
    result = compare(CICD, "Dry-run validated representative deployment paths for 25 of 28.")
    assert result.status == "FACTUALLY_PRESERVED"
    assert {q.value for q in result.omitted_quantities} >= {"28", "27"}


def test_worst_status_orders_severity():
    assert worst_status(["FACTUALLY_PRESERVED", "FACTUAL_UNIT_DRIFT", "FACTUAL_REVIEW_REQUIRED"]) \
        == "FACTUAL_UNIT_DRIFT"
    assert worst_status([]) == "FACTUALLY_PRESERVED"


def test_meaning_reviewer_catches_run5_unit_drift():
    # Regression for Run 5 DF-W3: the finalize path passed this rewrite.
    from howlwriter.domain.document import Document
    from howlwriter.review.meaning import MeaningPreservationReviewer

    result = MeaningPreservationReviewer().compare(
        Document.parse("Validated 25 of 28 standardized repositories."),
        Document.parse("Validated 25 of 28 deployment paths."),
    )
    assert result.status == "FLAGGED"
    assert [d.kind for d in result.diffs] == ["number_unit_changed"]


def test_meaning_reviewer_catches_dropped_dry_run():
    from howlwriter.domain.document import Document
    from howlwriter.review.meaning import MeaningPreservationReviewer

    result = MeaningPreservationReviewer().compare(
        Document.parse("Dry-run validated 25 of 28 deployment paths."),
        Document.parse("Validated 25 of 28 deployment paths."),
    )
    assert "scope_qualifier_removed" in [d.kind for d in result.diffs]
