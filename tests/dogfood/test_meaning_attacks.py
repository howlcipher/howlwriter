"""Adversarial meaning-preservation tests attacking the verification gate."""

import pytest

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.pipeline.howl import run_howl_pipeline
from howlwriter.review.meaning import (
    MeaningPreservationReviewer,
    RealModelMeaningReviewer,
)
from src.control_plane.agent_execution import FakeAgentBackend


@pytest.mark.parametrize(
    "original_text,mutated_text,expected_diff_kind",
    [
        (
            "Our team of 12 engineers migrated 45 microservices.",
            "Our team of 20 engineers migrated 45 microservices.",
            "number_removed",
        ),
        (
            "Our team of 12 engineers migrated 45 microservices.",
            "Our team of 12 engineers migrated 54 microservices.",
            "number_removed",
        ),
        (
            "The service achieved 99.9% uptime with 42.5% latency reduction.",
            "The service achieved 99.99% uptime with 42.5% latency reduction.",
            "number_removed",
        ),
        (
            "According to a study by MIT, lock contention degrades throughput.",
            "Lock contention degrades throughput in all systems.",
            "attribution_removed",
        ),
        (
            "This metric may indicate network congestion.",
            "This metric demonstrates network congestion.",
            "hedge_removed",
        ),
    ],
)
def test_deterministic_reviewer_catches_factual_mutations(
    original_text: str, mutated_text: str, expected_diff_kind: str
):
    orig = Document.parse(original_text)
    mut = Document.parse(mutated_text)

    result = MeaningPreservationReviewer().compare(orig, mut)

    assert result.status == "FLAGGED"
    assert any(d.kind == expected_diff_kind for d in result.diffs)


def test_semantic_review_catches_subtle_causality_escalation():
    orig = Document.parse(
        "Higher memory pressure was associated with increased garbage collection pauses."
    )
    rev = Document.parse(
        "Higher memory pressure directly causes garbage collection pauses."
    )

    fake_reviewer = FakeAgentBackend(
        agent_id="adversarial_reviewer",
        default_stdout="""```yaml
verdict: "FAIL"
differences:
  - kind: "stronger_claim"
    description: "Escalated correlation ('associated with') to causality ('directly causes')."
    severity: "blocker"
rationale: "Claim strength escalated beyond original justification."
```""",
    )

    reviewer = RealModelMeaningReviewer()
    result = reviewer.compare(
        orig, rev, humanizer_provider="test_humanizer", custom_backend=fake_reviewer
    )

    assert result.verdict == "FAIL"
    assert len(result.differences) == 1
    assert result.differences[0].kind == "stronger_claim"


def test_semantic_review_catches_polarity_reversal():
    orig = Document.parse(
        "The security audit failed to show any evidence of token leakage."
    )
    rev = Document.parse(
        "The security audit confirmed evidence of token leakage."
    )

    fake_reviewer = FakeAgentBackend(
        agent_id="adversarial_reviewer",
        default_stdout="""```yaml
verdict: "FAIL"
differences:
  - kind: "polarity_reversal"
    description: "Inverted finding from negative ('failed to show') to positive ('confirmed')."
    severity: "blocker"
rationale: "Complete factual inversion."
```""",
    )

    reviewer = RealModelMeaningReviewer()
    result = reviewer.compare(
        orig, rev, humanizer_provider="test_humanizer", custom_backend=fake_reviewer
    )

    assert result.verdict == "FAIL"


def test_meaning_failure_prevents_ready_status(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text("The system handled 100 requests in Q3.")

    # Simulated Humanizer that hallucinates numbers, paired with strict reviewer
    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout="""```yaml
resulting_text: |
  The system handled 500 requests in Q4.
verdict: "FAIL"
differences:
  - kind: "altered_numbers"
    description: "Changed 100 to 500 and Q3 to Q4."
rationale: "Factual drift."
```""",
    )

    res = run_howl_pipeline(draft, default_config(), custom_backend=fake_backend)

    # Status must be gated to NEEDS_REVIEW
    assert res.report.status == "NEEDS_REVIEW"
    assert res.report.semantic_meaning_status == "FAIL"
