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


def test_not_configured_meaning_reviewer_raises():
    original = Document.parse("Text.", title="t")
    revised = Document.parse("Text.", title="t")
    with pytest.raises(ModelRoleNotConfiguredError):
        NotConfiguredMeaningReviewer().compare(original, revised)
