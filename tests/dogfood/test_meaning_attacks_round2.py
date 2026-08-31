"""Adversarial Round 2 tests for compound meaning mutations."""

import pytest

from howlwriter.domain.document import Document
from howlwriter.review.meaning import (
    MeaningPreservationReviewer,
    RealModelMeaningReviewer,
)
from src.control_plane.agent_execution import FakeAgentBackend


@pytest.mark.parametrize(
    "orig,mutated,expected_kind",
    [
        (
            "Latency improved by 25ms under load.",
            "Latency improved by 250ms under load.",
            "number_removed",
        ),
        (
            "Pricing increased from $10 to $20 per month.",
            "Pricing increased from $10 to $50 per month.",
            "number_removed",
        ),
        (
            "The cluster uses 192.168.1.1 on port 8080.",
            "The cluster uses 10.0.0.1 on port 9090.",
            "number_removed",
        ),
        (
            "The team deployed v1.4.2 to staging.",
            "The team deployed v2.0.0 to staging.",
            "number_removed",
        ),
    ],
)
def test_deterministic_catches_compound_numerical_mutations(
    orig: str, mutated: str, expected_kind: str
):
    doc_orig = Document.parse(orig)
    doc_mut = Document.parse(mutated)

    res = MeaningPreservationReviewer().compare(doc_orig, doc_mut)
    assert res.status == "FLAGGED"


def test_semantic_review_catches_compound_hedges_dates_numbers():
    orig = Document.parse(
        "About 45 services may have experienced roughly 2% higher latency in Q3."
    )
    mut = Document.parse(
        "45 services experienced 2% higher latency in Q4."
    )

    fake_reviewer = FakeAgentBackend(
        agent_id="semantic_reviewer",
        default_stdout="""```yaml
verdict: "FAIL"
differences:
  - kind: "compound_mutation"
    description: "Dropped approximation, removed uncertainty, and altered date ('Q3' to 'Q4')."
    severity: "blocker"
rationale: "Multiple compound factual and certainty mutations."
```""",
    )

    reviewer = RealModelMeaningReviewer()
    res = reviewer.compare(orig, mut, humanizer_provider="test_h", custom_backend=fake_reviewer)

    assert res.verdict == "FAIL"
    assert len(res.differences) == 1
    assert "dropped approximation" in res.differences[0].description.lower()
