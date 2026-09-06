import pytest

from howlwriter.domain.document import Document
from howlwriter.integration.model_role import ModelRoleNotConfiguredError
from howlwriter.review.meaning import MeaningPreservationReviewer, NotConfiguredMeaningReviewer

reviewer = MeaningPreservationReviewer()


def test_identical_documents_pass_with_no_diffs():
    original = Document.parse("Sales grew by 12 percent. This may continue.", title="t")
    revised = Document.parse("Sales grew by 12 percent. This may continue.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "PASS"
    assert result.diffs == []


def test_changed_number_is_flagged():
    original = Document.parse("Sales grew by 12 percent this year.", title="t")
    revised = Document.parse("Sales grew by 40 percent this year.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "FLAGGED"
    kinds = {d.kind for d in result.diffs}
    assert "number_removed" in kinds
    assert "number_added" in kinds


def test_removed_hedge_word_is_flagged():
    original = Document.parse("This may be the best approach available today.", title="t")
    revised = Document.parse("This is the best approach available today.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "FLAGGED"
    hedge_diffs = [d for d in result.diffs if d.kind == "hedge_removed"]
    assert len(hedge_diffs) == 1
    assert "may" in hedge_diffs[0].description


def test_dropped_attribution_is_flagged():
    original = Document.parse("According to the report, sales grew this quarter.", title="t")
    revised = Document.parse("Sales grew this quarter.", title="t")
    result = reviewer.compare(original, revised)
    assert any(d.kind == "attribution_removed" for d in result.diffs)


def test_filler_removal_is_a_benign_style_change():
    original = Document.parse(
        "Furthermore, the service failed repeatedly.", title="t"
    )
    revised = Document.parse("The service failed repeatedly.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "PASS"
    assert any(d.kind == "filler_or_transition_removed" for d in result.style_diffs)


def test_conclusion_removal_is_a_benign_style_change():
    original = Document.parse(
        "In conclusion, these controls reduce the attack surface.", title="t"
    )
    revised = Document.parse("These controls reduce the attack surface.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "PASS"
    assert any(d.kind == "filler_or_transition_removed" for d in result.style_diffs)


def test_sentence_split_is_a_benign_style_change():
    original = Document.parse(
        "The service failed repeatedly and the queue filled completely.",
        title="t",
    )
    revised = Document.parse(
        "The service failed repeatedly. The queue filled completely.",
        title="t",
    )
    result = reviewer.compare(original, revised)
    assert result.status == "PASS"
    assert any(d.kind == "sentence_split" for d in result.style_diffs)


def test_qualifier_change_is_flagged():
    original = Document.parse("This may reduce latency.", title="t")
    revised = Document.parse("This reduces latency.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "FLAGGED"
    assert any(d.kind == "hedge_removed" for d in result.diffs)


def test_causal_escalation_is_flagged():
    original = Document.parse("X is associated with Y.", title="t")
    revised = Document.parse("X causes Y.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "FLAGGED"
    assert any(d.kind == "causal_escalation" for d in result.diffs)


def test_number_change_is_flagged():
    original = Document.parse("The error rate was 12%.", title="t")
    revised = Document.parse("The error rate was 21%.", title="t")
    result = reviewer.compare(original, revised)
    assert result.status == "FLAGGED"
    assert any(d.kind == "number_removed" for d in result.diffs)


def test_not_configured_meaning_reviewer_raises():
    original = Document.parse("Text.", title="t")
    revised = Document.parse("Text.", title="t")
    with pytest.raises(ModelRoleNotConfiguredError):
        NotConfiguredMeaningReviewer().compare(original, revised)


def test_dropped_negation_is_flagged_as_meaning_change():
    """A rewrite that deletes a negation inverts the claim and must not pass."""
    original = Document.parse(
        "The vulnerability allows unauthorized read access to session tokens. "
        "It does not permit arbitrary code execution, nor does it allow write "
        "access to database records."
    )
    revised = Document.parse(
        "The vulnerability allows unauthorized read access to session tokens. "
        "It permits arbitrary code execution, and it allows write access to "
        "database records."
    )

    result = MeaningPreservationReviewer().compare(original, revised)

    assert result.status == "FLAGGED"
    kinds = {d.kind for d in result.diffs}
    assert "negation_removed" in kinds


def test_added_negation_is_flagged_as_meaning_change():
    original = Document.parse("The service retries failed requests.")
    revised = Document.parse("The service does not retry failed requests.")

    result = MeaningPreservationReviewer().compare(original, revised)

    assert result.status == "FLAGGED"
    assert "negation_added" in {d.kind for d in result.diffs}


def test_negated_hedge_is_treated_as_a_hedge():
    """"unlikely" is a distinct token from "likely" and was previously missed."""
    original = Document.parse("The race condition permits token disclosure.")
    revised = Document.parse(
        "The race condition is unlikely to permit token disclosure."
    )

    result = MeaningPreservationReviewer().compare(original, revised)

    assert result.status == "FLAGGED"
    assert "hedge_added" in {d.kind for d in result.diffs}


def test_contracted_and_uncontracted_negation_are_equivalent():
    """Rewriting "does not" as "doesn't" is style, not a polarity change."""
    original = Document.parse("The parser does not accept trailing commas.")
    revised = Document.parse("The parser doesn't accept trailing commas.")

    result = MeaningPreservationReviewer().compare(original, revised)

    assert [d for d in result.diffs if d.kind.startswith("negation_")] == []


def test_identical_text_reports_no_polarity_change():
    text = Document.parse(
        "It does not permit arbitrary code execution, nor does it allow writes."
    )

    result = MeaningPreservationReviewer().compare(text, text)

    assert result.status == "PASS"


def test_moving_a_negation_between_sentences_is_not_cancelled_out():
    """Total negation counts cancel; what each negation governs does not."""
    original = Document.parse(
        "The firewall does not block SSH. The firewall permits HTTP traffic."
    )
    revised = Document.parse(
        "The firewall permits SSH. The firewall does not block HTTP traffic."
    )

    result = MeaningPreservationReviewer().compare(original, revised)

    assert result.status == "FLAGGED"
    kinds = {d.kind for d in result.diffs}
    assert "negation_removed" in kinds
    assert "negation_added" in kinds


def test_curly_apostrophe_negation_is_still_tracked():
    original = Document.parse("The service doesn’t allow anonymous execution.")
    revised = Document.parse("The service allows anonymous execution.")

    result = MeaningPreservationReviewer().compare(original, revised)

    assert result.status == "FLAGGED"
    assert "negation_removed" in {d.kind for d in result.diffs}


def test_apostrophe_style_change_alone_is_not_a_meaning_change():
    original = Document.parse("The service doesn't allow execution.")
    revised = Document.parse("The service doesn’t allow execution.")

    result = MeaningPreservationReviewer().compare(original, revised)

    assert [d for d in result.diffs if d.kind.startswith("negation_")] == []


def test_rewording_a_negation_is_reported_as_a_rephrase_not_an_inversion():
    """"not considered a valid source" and "not treated as a valid source"
    negate the same proposition and must not read as a polarity flip."""
    original = Document.parse("Model memory is never considered a valid source.")
    revised = Document.parse("Model memory is never treated as a valid source.")

    result = MeaningPreservationReviewer().compare(original, revised)

    kinds = {d.kind for d in result.diffs}
    assert "negation_removed" not in kinds
    assert "negation_added" not in kinds
    assert "negation_rephrased" in kinds
