"""Unit tests for benchmark case loading, validation, and category coverage."""

from __future__ import annotations

from howlwriter.evaluation.fixtures import get_benchmark_suite, load_all_cases

REQUIRED_CATEGORIES = {
    "academic/research",
    "technical explanation",
    "technical documentation",
    "argumentative analysis",
    "professional writing",
    "LinkedIn/social professional writing",
    "editing/rewrite",
    "voice-preserving rewrite",
    "source-grounded synthesis",
    "fact-sensitive writing",
    "outline-constrained authorship",
}


def test_load_all_cases():
    cases = load_all_cases()
    assert len(cases) >= 30, f"Expected at least 30 benchmark cases, found {len(cases)}"

    # Verify unique IDs
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "Duplicate benchmark case IDs found!"

    # Verify all 11 required categories are covered
    found_categories = {c.category for c in cases}
    missing = REQUIRED_CATEGORIES - found_categories
    assert not missing, f"Missing required benchmark categories: {missing}"


def test_case_validation():
    cases = load_all_cases()
    for case in cases:
        assert case.id, "Case ID cannot be empty"
        assert case.task, f"Task cannot be empty for case {case.id}"
        assert case.mode, f"Mode cannot be empty for case {case.id}"
        assert case.category, f"Category cannot be empty for case {case.id}"
        assert case.metrics, f"Case {case.id} must declare evaluated metrics"


def test_suite_definitions():
    core_suite = get_benchmark_suite("core")
    assert len(core_suite.cases) >= 10
    assert core_suite.name == "core"

    academic_suite = get_benchmark_suite("academic")
    assert len(academic_suite.cases) >= 3

    tech_suite = get_benchmark_suite("technical")
    assert len(tech_suite.cases) >= 3

    rewrite_suite = get_benchmark_suite("rewrite")
    assert len(rewrite_suite.cases) >= 3

    all_suite = get_benchmark_suite("all")
    assert len(all_suite.cases) >= 30
