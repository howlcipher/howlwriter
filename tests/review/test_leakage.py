"""Workflow-commentary leakage: catches process notes, keeps real qualifications."""

from __future__ import annotations

import pytest

from howlwriter.review.leakage import (
    LEAK_EDITORIAL_INSTRUCTION,
    LEAK_MODEL_SELF_REFERENCE,
    LEAK_PLACEHOLDER,
    LEAK_PROVENANCE_NOTE,
    LEAK_SOURCE_PROCESS,
    LEAK_VERIFICATION_STATUS,
    detect_leakage,
    has_blocking_leakage,
)


def _codes(text, **kw):
    return {f.code for f in detect_leakage(text, **kw)}


@pytest.mark.parametrize("text,code", [
    # The sentence that prompted this module.
    ("I recommend AI for log analysis. This is my recommendation, not a cited result.", LEAK_PROVENANCE_NOTE),
    ("That is my own interpretation, not a sourced claim.", LEAK_PROVENANCE_NOTE),
    ("This is an unverified recommendation.", LEAK_PROVENANCE_NOTE),
    ("According to the supplied sources, vendors change models.", LEAK_SOURCE_PROCESS),
    ("The retrieved sources do not discuss subprocessors.", LEAK_SOURCE_PROCESS),
    ("The claim check returned NEEDS_REVIEW for this paragraph.", LEAK_VERIFICATION_STATUS),
    ("Value chains are opaque [S003].", LEAK_VERIFICATION_STATUS),
    ("Citation verification passed for all four references.", LEAK_VERIFICATION_STATUS),
    ("Here is the revised draft of the post.", LEAK_EDITORIAL_INSTRUCTION),
    ("As requested, I kept it under the limit.", LEAK_EDITORIAL_INSTRUCTION),
    ("Word count: 271", LEAK_EDITORIAL_INSTRUCTION),
    ("As an AI language model, I cannot verify this.", LEAK_MODEL_SELF_REFERENCE),
    ("HowlWriter rewrote this paragraph.", LEAK_MODEL_SELF_REFERENCE),
    ("Controls matter [citation needed].", LEAK_PLACEHOLDER),
    ("TODO tighten the second paragraph.", LEAK_PLACEHOLDER),
])
def test_workflow_commentary_is_flagged(text, code):
    assert code in _codes(text)


@pytest.mark.parametrize("text", [
    # Real qualifications about the subject or the evidence base.
    "The guidance does not say whether prompt injection can be fully prevented.",
    "It is unclear whether fool-proof prevention exists.",
    "The study's sample was small, so the effect may not generalize.",
    "This is my recommendation: require notice of model changes.",
    "In my view, least privilege is the stronger control.",
    "Their data covers only 2022 deployments, which limits the conclusion.",
    "I would treat vendor documents as untrusted input.",
    # Subject matter that merely mentions models or verification.
    "Large language models can follow instructions embedded in a document.",
    "Verified boot protects the firmware chain.",
    "An assistant that summarizes tickets still needs a human approver.",
    "Retrieval-augmented generation pulls documents into the prompt.",
])
def test_legitimate_content_is_kept(text):
    assert detect_leakage(text) == []


def test_references_section_is_not_scanned():
    text = "Controls matter.\n\n# References\n\nOWASP. (2025). Verified supply chain notes. TODO"
    assert detect_leakage(text) == []


def test_research_paper_may_describe_source_collection():
    sentence = "The retrieved sources were screened against the inclusion criteria."
    assert LEAK_SOURCE_PROCESS not in _codes(sentence, genre="academic_research_paper")


def test_hard_markers_still_flagged_in_research_papers():
    assert LEAK_VERIFICATION_STATUS in _codes("Status: NEEDS_REVIEW.", genre="academic_research_paper")


def test_blocking_distinguishes_errors_from_warnings():
    soft = detect_leakage("This is my recommendation, not a cited result.")
    hard = detect_leakage("As an AI language model I agree.")
    assert not has_blocking_leakage(soft) and has_blocking_leakage(hard)


def test_finding_explains_itself():
    (f,) = detect_leakage("This is my recommendation, not a cited result.")
    assert f.matched_text and "provenance" in f.message.lower() and f.sentence_index == 0


def test_detector_never_modifies_input():
    text = "This is my recommendation, not a cited result."
    detect_leakage(text)
    assert text == "This is my recommendation, not a cited result."


def test_lint_cli_reports_leakage_only_when_asked(tmp_path, capsys):
    import json
    from howlwriter.cli.main import main

    post = tmp_path / "post.md"
    post.write_text("Least privilege limits the damage. This is my recommendation, not a cited result.\n")
    assert main(["lint", str(post), "--json"]) == 0
    assert all(not m["rule_code"].startswith("LEAK_") for m in json.loads(capsys.readouterr().out))
    assert main(["lint", str(post), "--json", "--workflow-leakage"]) == 0
    codes = [m["rule_code"] for m in json.loads(capsys.readouterr().out)]
    assert LEAK_PROVENANCE_NOTE in codes
