"""The disclosure must describe the run that happened, not the feature that exists.

The failure this guards against is a statement that is true of the system in
general and false of this document: claiming generation when only linting ran,
or claiming the author supplied the argument when they supplied three bullet
points. Every branch below is decided by the provenance record, so a run that
did less produces a smaller claim without anyone remembering to soften it.

Also covered: the three-way separation APA cares about. Scholarly references
are evidence, the AI disclosure is a Method-section statement about tooling,
and the provenance appendix is workflow. Prompts and run ids belong only to the
third.
"""

from __future__ import annotations

from howlwriter.academic.ai_disclosure import (
    DISCLOSURE_SECTION,
    build_ai_use_statement,
    render_provenance_appendix,
)
from howlwriter.domain.generation_provenance import (
    ContributionSummary,
    GenerationProvenance,
    ModelCallRecord,
)


def _writer_run(freedom: str = "LOW", **contribution) -> GenerationProvenance:
    return GenerationProvenance(
        run_id="hw-1",
        workflow="howl-outline",
        outline_present=True,
        generation_freedom=freedom,
        calls=[
            ModelCallRecord(sequence=1, role="writer", provider="agy", success=True),
            ModelCallRecord(
                sequence=2, role="final_reviewer", provider="codex",
                success=True, independence_status="INDEPENDENT",
            ),
        ],
        contribution=ContributionSummary(**contribution),
    )


# --- the statement tracks what ran ---------------------------------------

def test_a_run_with_no_model_calls_does_not_claim_generation():
    statement = build_ai_use_statement(GenerationProvenance(), lint_only=True)
    assert statement.used_generative_ai is False
    assert "No generative AI model produced or altered" in statement.statement
    assert "linting reports findings and does not rewrite" in statement.statement


def test_a_humanizer_only_run_does_not_claim_text_was_generated():
    """Refinement is not generation, and the statement must not blur them."""
    provenance = GenerationProvenance(
        calls=[ModelCallRecord(sequence=1, role="humanizer", provider="agy", success=True)]
    )
    statement = build_ai_use_statement(provenance)

    assert statement.used_generative_ai is True
    assert "No text was generated from scratch" in statement.statement
    assert "expanded the author's outline" not in statement.statement


def test_a_sparse_outline_admits_the_model_wrote_most_of_the_prose():
    statement = build_ai_use_statement(
        _writer_run(freedom="HIGH", required_points_supplied=3, required_points_represented=3)
    )
    assert "most of the connective prose and sentence-level wording was "\
           "produced by a generative model" in statement.statement


def test_an_authorship_rich_outline_says_the_model_was_limited_to_development():
    statement = build_ai_use_statement(
        _writer_run(
            freedom="LOW", claims_supplied=6, preserved_supplied=3,
            required_points_supplied=9, required_points_represented=9,
        )
    )
    assert "limited to development, transitions, and connective prose" in statement.statement
    assert "most of the connective prose" not in statement.statement


def test_the_same_system_produces_different_statements_for_different_runs():
    """The property that makes the disclosure worth anything."""
    high = build_ai_use_statement(_writer_run(freedom="HIGH")).statement
    low = build_ai_use_statement(_writer_run(freedom="LOW")).statement
    none = build_ai_use_statement(GenerationProvenance()).statement
    assert len({high, low, none}) == 3


def test_added_claims_and_gaps_are_disclosed():
    provenance = _writer_run(model_added_claims=4)
    provenance.gaps = ["needs a figure only the author has"]
    statement = build_ai_use_statement(provenance)

    assert "4 factual assertion(s) added" in statement.statement
    assert "were not invented" in statement.statement


def test_the_disclosure_names_the_method_section():
    assert DISCLOSURE_SECTION == "Method"
    assert build_ai_use_statement(_writer_run()).section == "Method"


# --- the reference entry -------------------------------------------------

def test_no_reference_is_fabricated_when_the_provider_reported_no_model():
    """APA's template needs the tool and version. A CLI name is neither."""
    statement = build_ai_use_statement(_writer_run())
    reference = statement.reference

    assert reference.available is False
    assert reference.entry == ""
    assert "did not report a model name" in reference.reason
    # The provider identifier must not be smuggled into the author position.
    assert "agy" not in reference.entry
    assert "Large language model" not in reference.entry


def test_a_reported_model_produces_a_partial_entry_with_placeholders_not_guesses():
    provenance = _writer_run()
    provenance.calls[0].model = "claude-sonnet-4-6"
    provenance.calls[0].model_status = "REPORTED"
    reference = build_ai_use_statement(provenance).reference

    assert reference.available is True
    assert "claude-sonnet-4-6" in reference.entry
    assert "[Large language model]" in reference.entry
    # The organization and URL are not visible to HowlWriter, so they stay
    # placeholders rather than being invented.
    assert "[Provider organization]" in reference.entry
    assert "[URL of the tool]" in reference.entry


def test_unreported_models_are_noted_rather_than_passed_over():
    statement = build_ai_use_statement(_writer_run())
    assert any("did not report a model name" in n for n in statement.notes)


def test_reviewer_independence_is_disclosed():
    statement = build_ai_use_statement(_writer_run())
    assert any("Reviewer independence: INDEPENDENT" in n for n in statement.notes)


# --- separation of the three concepts ------------------------------------

def test_the_appendix_states_it_is_workflow_and_not_evidence():
    appendix = render_provenance_appendix(_writer_run())
    assert "not of evidence" in appendix
    assert "appear in the References list and nowhere here" in appendix


def test_the_appendix_disclaims_access_to_model_reasoning():
    appendix = render_provenance_appendix(_writer_run())
    assert "does not contain any model's internal reasoning" in appendix.lower()


def test_nothing_in_this_module_writes_to_the_scholarly_reference_list():
    """Structural guarantee, checked against the source itself."""
    import inspect

    from howlwriter.academic import ai_disclosure

    source = inspect.getsource(ai_disclosure)
    for forbidden in ("attach_references", "APA7Formatter", "reference_page"):
        assert forbidden not in source


def test_the_statement_serializes_for_the_provenance_record():
    payload = build_ai_use_statement(_writer_run()).to_dict()
    assert payload["section"] == "Method"
    assert payload["used_generative_ai"] is True
    assert payload["reference"]["available"] is False


def test_a_low_freedom_run_that_still_wrote_most_words_says_so():
    """Freedom measures constraint, not how much text the model produced.

    A densely structured academic outline can score LOW -- thesis, claims,
    headings, enforced order -- while leaving the model to write 95% of the
    sentences. Claiming the model was "limited to connective prose" because the
    label said LOW would be exactly the overstatement this module prevents.
    """
    provenance = _writer_run(
        freedom="LOW",
        claims_supplied=3,
        preserved_supplied=1,
        required_points_supplied=10,
        required_points_represented=10,
        user_words_supplied=65,
        artifact_words=1600,
    )
    statement = build_ai_use_statement(provenance).statement

    assert "most of the sentence-level wording" in statement
    assert "limited to development, transitions" not in statement
    assert "65 were supplied directly by the author" in statement
    assert "not a measure of authorship" in statement


def test_a_low_freedom_run_where_the_author_wrote_most_of_it_says_that_instead():
    provenance = _writer_run(
        freedom="LOW",
        claims_supplied=3,
        preserved_supplied=4,
        required_points_supplied=6,
        required_points_represented=6,
        user_words_supplied=500,
        artifact_words=900,
    )
    statement = build_ai_use_statement(provenance).statement

    assert "limited to development, transitions, and connective prose" in statement
    assert "most of the sentence-level wording" not in statement
