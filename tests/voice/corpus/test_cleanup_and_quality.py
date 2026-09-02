"""Academic-apparatus cleanup, corpus-quality classification, and context."""

from __future__ import annotations

from pathlib import Path

from howlwriter.voice.corpus.cleanup import clean_document
from howlwriter.voice.corpus.context import (
    ACADEMIC,
    MIXED,
    PROFESSIONAL,
    UNKNOWN,
    classify_context,
    path_prior,
)
from howlwriter.voice.corpus.features import extract_features
from howlwriter.voice.corpus.quality import (
    EXCLUDE,
    HOLD_FOR_REVIEW,
    INCLUDE,
    LIKELY_AUTHORED,
    LIKELY_AUTHORED_WITH_REFERENCES,
    NON_PROSE,
    RESUME,
    SENSITIVE_CONTENT,
    TEMPLATE_OR_PROMPT,
    classify_document,
    looks_sensitive,
)
from tests.voice.corpus.conftest import synthetic_prose

AUTHORED = (
    "The rollback took eleven minutes, which was longer than the incident that "
    "caused it. I had assumed the runbook was current. It was not, and nobody "
    "had touched it since the migration.\n\n"
    "What surprised me was how confidently the dashboard reported success while "
    "the queue was still draining. The metric was measuring the wrong boundary, "
    "and it had been measuring the wrong boundary for months.\n\n"
    "Fixing the metric took an afternoon. Working out which other metrics had the "
    "same flaw took considerably longer, and I am still not certain we found all "
    "of them.\n\n"
    "The part I keep returning to is that every person who looked at that "
    "dashboard believed it. It was green. Green is a very persuasive colour when "
    "you are tired and it is the middle of the night.\n\n"
    "There is a version of this story where the lesson is about better alerting. "
    "That version is tidier than what actually happened, and I do not think it is "
    "true. The alert was fine. What failed was the assumption underneath it, "
    "which nobody had written down anywhere and which therefore nobody could "
    "review.\n\n"
    "So the change we made was small and unglamorous. We wrote down what each "
    "dashboard was actually measuring, in one sentence, next to the dashboard. It "
    "has caught three more of these since, which is a better return than any of "
    "the tooling we considered buying."
)


def _assess(text: str, filename: str = "essay.docx"):
    cleaned = clean_document(text)
    features = extract_features(cleaned.text, headings=len(cleaned.headings))
    return cleaned, features, classify_document(
        filename=filename, raw_text=text, cleanup=cleaned, features=features
    )


# --- cleanup -----------------------------------------------------------

def test_reference_section_is_removed_entirely():
    document = (
        f"# Analysis\n\n{AUTHORED}\n\n"
        "## References\n\n"
        "Smith, J. A. (2024). Something about controls. Journal of Things, 12(3), 45-67.\n\n"
        "Jones, B., & Patel, R. (2023). Another paper entirely. Academic Press.\n"
    )
    result = clean_document(document)
    assert "Smith, J. A. (2024)" not in result.text
    assert "Academic Press" not in result.text
    assert "rollback took eleven minutes" in result.text
    assert result.removed_kinds.get("references_section", 0) >= 2


def test_bibliography_and_works_cited_headings_also_terminate():
    for heading in ("Bibliography", "Works Cited", "Reference List"):
        document = f"{AUTHORED}\n\n## {heading}\n\nDoe, A. (2020). A title. Press.\n"
        result = clean_document(document)
        assert "Doe, A. (2020)" not in result.text, heading


def test_a_citation_inside_a_sentence_does_not_destroy_the_sentence():
    """The rule this module most needs to get right."""
    document = (
        "The results from Smith (2024) suggest that the control is useful, but the "
        "small sample makes that conclusion difficult to generalize.\n\n"
        "Later work by Jones et al. (2023) found the opposite, which is the part "
        "nobody quotes."
    )
    result = clean_document(document)
    assert "difficult to generalize" in result.text
    assert "which is the part nobody quotes" in result.text
    assert result.removed_words == 0


def test_assignment_prompt_is_removed_and_does_not_become_voice():
    document = (
        "In this assignment you will analyze three attack chains. Your paper should "
        "be double-spaced and follow APA format. You are required to cite at least "
        "three scholarly sources, and you must submit it before the due date.\n\n"
        f"{AUTHORED}"
    )
    result = clean_document(document)
    assert "you will analyze" not in result.text
    assert "double-spaced" not in result.text
    assert "rollback took eleven minutes" in result.text
    assert result.removed_kinds.get("rubric_or_prompt", 0) == 1


def test_title_page_fields_are_removed():
    document = (
        "Name: A Student\nCourse: INFA 601\nInstructor: Dr Someone\nDate: March 2026\n\n"
        f"# Introduction\n\n{AUTHORED}"
    )
    result = clean_document(document)
    assert "Instructor: Dr Someone" not in result.text
    assert result.removed_kinds.get("title_page", 0) == 1


def test_a_field_shaped_line_inside_prose_is_not_treated_as_a_cover_field():
    document = (
        f"{AUTHORED}\n\n"
        "Date: the only thing that mattered was that the incident began before the "
        "on-call rotation changed hands, which is why nobody escalated it.\n"
    )
    result = clean_document(document)
    assert "on-call rotation changed hands" in result.text


def test_block_quotes_and_code_blocks_are_removed():
    document = (
        f"{AUTHORED}\n\n"
        "> A long quotation from an entirely different author that should not be "
        "counted toward anybody's writing voice whatsoever.\n\n"
        "```python\ndef helper():\n    return 42\n```\n"
    )
    result = clean_document(document)
    assert "entirely different author" not in result.text
    assert "def helper" not in result.text
    assert result.removed_kinds.get("block_quote", 0) == 1
    assert result.removed_kinds.get("code_block", 0) >= 1


def test_table_of_contents_is_removed():
    document = (
        "## Table of Contents\n\nIntroduction .......... 1\n\nMethodology .......... 4\n\n"
        f"# Introduction\n\n{AUTHORED}"
    )
    result = clean_document(document)
    assert "Methodology .........." not in result.text
    assert "rollback took eleven minutes" in result.text


def test_lab_tool_boilerplate_is_removed():
    document = (
        "Report Generated: Sunday, March 29, 2026 at 2:49 PM\n\n"
        "Time on Task: 0 hours, 48 minutes\n\n"
        f"{AUTHORED}"
    )
    result = clean_document(document)
    assert "Report Generated" not in result.text
    assert result.removed_kinds.get("generated_boilerplate", 0) == 2


def test_headings_are_kept_but_reported():
    result = clean_document(f"# One\n\n{AUTHORED}\n\n## Two\n\n{AUTHORED}")
    assert result.headings == ["One", "Two"]
    assert "# One" in result.text


def test_apparatus_ratio_reflects_how_much_was_stripped():
    mostly_apparatus = (
        "Name: A Student\nCourse: X\n\n"
        "In this assignment you will do the thing. Your paper should be long. You "
        "are required to submit it.\n\n"
        "## References\n\nSmith, J. (2020). Title. Press.\n\nJones, B. (2021). Title. Press.\n\n"
        "One short authored sentence survives here.\n"
    )
    result = clean_document(mostly_apparatus)
    assert result.apparatus_ratio > 0.7


# --- quality -----------------------------------------------------------

def test_sustained_authored_prose_is_included():
    _cleanup, _features, assessment = _assess(AUTHORED * 3)
    assert assessment.classification == LIKELY_AUTHORED
    assert assessment.inclusion == INCLUDE
    assert assessment.weight == 1.0
    assert assessment.reason


def test_authored_prose_that_cites_sources_is_still_included():
    document = (
        (AUTHORED + "\n\nAs Smith (2024) notes, the boundary problem is not new, and "
         "Jones (2023) reaches a similar conclusion by a different route.\n\n") * 2
        + "## References\n\nSmith, J. (2024). A title. Press.\n\n"
          "Jones, B. (2023). Another. Press.\n\nPatel, R. (2022). A third. Press.\n"
    )
    _cleanup, _features, assessment = _assess(document)
    assert assessment.classification == LIKELY_AUTHORED_WITH_REFERENCES
    assert assessment.inclusion == INCLUDE


def test_syllabus_is_excluded():
    document = (
        "Course Syllabus\n\nOffice hours are Tuesday afternoons. The attendance "
        "policy requires participation in every module. Academic integrity "
        "violations are reported. The required textbook is listed below. The "
        "grading scale follows the university standard.\n\n"
    ) + synthetic_prose(1, paragraphs=8)
    _cleanup, _features, assessment = _assess(document, filename="INFA721 Syllabus.docx")
    assert assessment.classification == TEMPLATE_OR_PROMPT
    assert assessment.inclusion == EXCLUDE


def test_resume_is_excluded():
    document = (
        "Professional Summary\n\nSecurity engineer with a decade of experience.\n\n"
        "Technical Skills\n\nPython, Go, Kubernetes, incident response.\n\n"
        "Professional Experience\n\nLed the migration of a monitoring platform.\n\n"
        "Education\n\nMaster of Science.\n\nCertifications\n\nSeveral.\n\n"
    ) + synthetic_prose(2, paragraphs=6)
    _cleanup, _features, assessment = _assess(document, filename="Resume_Person.docx")
    assert assessment.classification == RESUME
    assert assessment.inclusion == EXCLUDE


def test_source_code_is_never_treated_as_writing_voice():
    document = "\n".join(
        f"def handler_{i}(request):\n    return process(request)\n"
        f"import module_{i}\n"
        f"class Thing{i}:\n    pass\n"
        for i in range(20)
    )
    _cleanup, _features, assessment = _assess(document, filename="app.md")
    assert assessment.classification == NON_PROSE
    assert assessment.inclusion == EXCLUDE


def test_too_little_prose_is_excluded_with_the_count_in_the_reason():
    _cleanup, _features, assessment = _assess("A short note. Nothing more to say here.")
    assert assessment.classification == NON_PROSE
    assert "words of authored prose" in assessment.reason


def test_second_person_only_document_is_held_rather_than_included():
    document = (
        "You should check the logs before you escalate. You will find that your "
        "alert routing is wrong. You need to verify your channel membership, and "
        "you must confirm your on-call schedule is current. You can then close "
        "your ticket once you have confirmed your fix works as you expect.\n\n"
    ) * 4
    _cleanup, _features, assessment = _assess(document)
    assert assessment.inclusion == HOLD_FOR_REVIEW
    assert "authorship is unclear" in assessment.reason


# --- the credential guard ---------------------------------------------

def test_credential_files_are_detected_by_name_and_by_content():
    # Generic stand-ins. The shapes are the ones that actually turn up beside
    # documents in a drive, written here without naming anyone's real files.
    assert looks_sensitive("saved-passwords.csv", "")
    assert looks_sensitive("api_key.txt", "")
    assert looks_sensitive("id_rsa", "")
    assert looks_sensitive("account_credentials.csv", "")
    assert looks_sensitive("mail_2fa_recovery_codes.txt", "")
    assert looks_sensitive("notes.txt", "recovery codes: 8471 2039 5566")
    assert looks_sensitive("cfg.txt", "api_key = sk-abcdefghijklmnop")
    assert looks_sensitive("k.txt", "-----BEGIN RSA PRIVATE KEY-----")
    assert not looks_sensitive("essay.docx", AUTHORED)
    # Ordinary words that happen to appear in project names must not cost a
    # document its place in the corpus; the content scan still covers them.
    assert not looks_sensitive("secret_project_notes.md", AUTHORED)
    assert not looks_sensitive("token bucket rate limiting.md", AUTHORED)


def test_a_credential_file_is_excluded_before_anything_is_derived():
    document = "password: hunter2\npassword: correct-horse\n\n" + synthetic_prose(3, 8)
    _cleanup, _features, assessment = _assess(document, filename="notes.txt")
    assert assessment.classification == SENSITIVE_CONTENT
    assert assessment.inclusion == EXCLUDE
    assert "before any derived data was computed" in assessment.reason


# --- context -----------------------------------------------------------

def test_academic_content_classifies_as_academic():
    document = (
        "This paper examines the boundary problem in distributed telemetry. Prior "
        "research by Smith (2024) suggests that sampling error dominates, and the "
        "findings of Jones (2023) support that reading. The literature generally "
        "treats the question as settled, which the evidence suggests is premature.\n\n"
        + AUTHORED.replace("I had", "the analysis had").replace("I am", "the author is")
        + "\n\n## References\n\nSmith, J. (2024). Title. Press.\n\n"
          "Jones, B. (2023). Title. Press.\n\nPatel, R. (2022). Title. Press.\n"
    )
    cleaned = clean_document(document)
    features = extract_features(cleaned.text, headings=len(cleaned.headings))
    result = classify_context(
        path=Path("/data/somewhere/file.docx"), text=cleaned.text,
        cleanup=cleaned, features=features,
    )
    assert result.context == ACADEMIC
    assert result.confidence > 0


def test_a_folder_name_alone_cannot_decide_the_context():
    """`school docs/` must not make a workplace document academic."""
    workplace = (
        "The team missed the rollout window again. Our client escalated to "
        "leadership before the on-call engineer saw the incident.\n\n"
        "I pulled the runbook and it was stale. Next steps: rewrite the handoff "
        "doc and get the deployment checklist into the sprint.\n\n"
        "Lessons learned are cheap. Acting on them is the part nobody budgets for, "
        "and the stakeholder conversation never quite happens.\n\n"
        "The vendor escalation path is still undocumented, which is a change "
        "request nobody has filed.\n"
    )
    cleaned = clean_document(workplace)
    features = extract_features(cleaned.text)
    result = classify_context(
        path=Path("/drive/stuffs/school docs/assignment/notes.docx"),
        text=cleaned.text, cleanup=cleaned, features=features,
    )
    assert result.context == PROFESSIONAL


def test_path_prior_is_capped_and_reported():
    scores, matched = path_prior("/drive/school/course/assignment/paper/essay.docx")
    assert scores[ACADEMIC] <= 0.8
    assert "school" in matched


def test_thin_evidence_yields_unknown_not_a_guess():
    text = synthetic_prose(4, paragraphs=5)
    cleaned = clean_document(text)
    features = extract_features(cleaned.text)
    result = classify_context(
        path=Path("/data/file.md"), text=cleaned.text, cleanup=cleaned, features=features,
    )
    assert result.context in (UNKNOWN, MIXED)
    assert result.confidence == 0.0
    assert result.reason


def test_context_that_only_leads_because_of_the_path_is_rejected():
    """Content must carry the classification on its own."""
    neutral = synthetic_prose(5, paragraphs=6)
    cleaned = clean_document(neutral)
    features = extract_features(cleaned.text)
    result = classify_context(
        path=Path("/drive/school/course/assignment/paper/thesis/essay.docx"),
        text=cleaned.text, cleanup=cleaned, features=features,
    )
    assert result.context != ACADEMIC
