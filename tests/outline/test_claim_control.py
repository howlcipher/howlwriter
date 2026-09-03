"""Model additions: which ones are new commitments, and what follows.

The distinction that matters is not length or confidence but what a sentence
ASSERTS. Restating the author's own claim commits them to nothing new. A
sentence with a statistic in it commits them to something they may not agree
with, and in a research-backed mode it cannot ship unsupported.

The classifier is deliberately asymmetric: where it cannot tell, it reports a
new assertion rather than clearing the sentence. A false alarm costs a glance;
a false clear is the failure it exists to prevent.
"""

from __future__ import annotations

from howlwriter.domain.outline import load_outline
from howlwriter.outline.claims import (
    CONNECTIVE_PROSE,
    LOGICAL_EXPANSION,
    NEW_FACTUAL,
    classify_addition,
    review_additions,
)

_OUTLINE = load_outline({
    "topic": "moats",
    "nodes": [
        {"kind": "claim", "text": "Implementation cost historically creates competitive friction."},
        {"kind": "claim", "text": "AI collapses that friction for everyone at once."},
    ],
})


def test_restating_the_authors_own_claim_is_logical_expansion():
    finding = classify_addition(
        "Implementation cost created friction that protected incumbents.", _OUTLINE
    )
    assert finding.classification == LOGICAL_EXPANSION
    assert finding.grounded_in


def test_inflection_does_not_turn_a_restatement_into_a_new_assertion():
    """"Creates friction" and "created friction" are the same commitment."""
    finding = classify_addition(
        "Implementation costs created competitive frictions.", _OUTLINE
    )
    assert finding.classification == LOGICAL_EXPANSION


def test_a_statistic_the_author_never_supplied_is_a_new_factual_assertion():
    for text in (
        "Most enterprises replaced their data teams in 2024.",
        "Roughly 70 percent of migrations fail.",
        "Studies show that adoption doubled.",
    ):
        assert classify_addition(text, _OUTLINE).classification == NEW_FACTUAL, text


def test_a_transition_asserts_nothing_and_is_classified_as_connective():
    finding = classify_addition("But that is only half the story.", _OUTLINE)
    assert finding.classification == CONNECTIVE_PROSE


def test_an_untraceable_sentence_is_reported_rather_than_cleared():
    finding = classify_addition(
        "Procurement teams rarely understand vendor lock-in.", _OUTLINE
    )
    assert finding.classification == NEW_FACTUAL
    assert "rather than cleared" in finding.detail


def test_classification_is_identical_across_modes_only_the_consequence_differs():
    """The same sentence is the same kind of addition everywhere."""
    added = [{"claim": "Most enterprises replaced their data teams in 2024."}]
    academic = review_additions(added, _OUTLINE, research_backed=True)
    social = review_additions(added, _OUTLINE, research_backed=False)

    assert academic.to_dict()["counts"] == social.to_dict()["counts"]
    assert academic.blocks_readiness is True
    assert social.blocks_readiness is False


def test_a_social_run_still_surfaces_the_addition_rather_than_swallowing_it():
    review = review_additions(
        [{"claim": "Adoption grew 40% last year."}], _OUTLINE, research_backed=False
    )
    assert review.new_factual
    assert any("should not arrive sounding like evidence" in n for n in review.notes)


def test_evidence_makes_an_addition_safe_without_erasing_its_origin():
    """Support changes readiness, not whether the model introduced the fact."""
    added = [{"claim": "Most enterprises replaced their data teams in 2024."}]
    review = review_additions(
        added,
        _OUTLINE,
        research_backed=True,
        supported_claims={"Most enterprises replaced their data teams in 2024."},
    )
    assert review.blocks_readiness is False
    assert review.findings[0].classification == NEW_FACTUAL
    assert "matched to retrieved evidence" in review.findings[0].detail


def test_no_additions_produces_no_findings_and_no_block():
    review = review_additions([], _OUTLINE, research_backed=True)
    assert review.findings == []
    assert review.blocks_readiness is False


def test_the_review_reports_counts_and_never_a_share_of_authorship():
    payload = review_additions(
        [{"claim": "Adoption grew 40% last year."}, {"claim": "But there is more."}],
        _OUTLINE,
        research_backed=False,
    ).to_dict()

    assert set(payload["counts"]) == {LOGICAL_EXPANSION, CONNECTIVE_PROSE, NEW_FACTUAL}
    assert all(isinstance(v, int) for v in payload["counts"].values())
    assert "percent_human" not in payload
    assert "authorship" not in str(payload)
