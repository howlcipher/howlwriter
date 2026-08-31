"""Large input safety tests ensuring oversized documents fail cleanly with actionable guidance."""

import pytest

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.humanize.rewriter import (
    MAX_SINGLE_PASS_CHARS,
    ModelHumanizerRewriter,
)
from howlwriter.review.meaning import RealModelMeaningReviewer
from src.control_plane.agent_execution import FakeAgentBackend


def test_oversized_document_fails_cleanly_without_silent_truncation():
    # Construct 120,000 character document
    large_text = "# Large System Analysis\n\n" + ("This is paragraph text. " * 5500)
    assert len(large_text) > MAX_SINGLE_PASS_CHARS

    doc = Document.parse(large_text)
    rewriter = ModelHumanizerRewriter()

    with pytest.raises(ValueError) as exc_info:
        rewriter.rewrite(doc, default_config(), custom_backend=FakeAgentBackend("mock"))

    assert "exceeds safe single-pass limit" in str(exc_info.value)
    assert "sections or chapters" in str(exc_info.value)


def test_oversized_document_in_meaning_review_fails_cleanly():
    large_text = "# Large System Analysis\n\n" + ("This is paragraph text. " * 5500)
    doc_orig = Document.parse(large_text)
    doc_rev = Document.parse(large_text)

    reviewer = RealModelMeaningReviewer()
    with pytest.raises(ValueError) as exc_info:
        reviewer.compare(
            doc_orig, doc_rev, humanizer_provider="mock", custom_backend=FakeAgentBackend("mock")
        )

    assert "exceeds safe single-pass limit" in str(exc_info.value)
