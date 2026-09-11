"""Unit tests for the meaning preservation evaluation metric."""

from __future__ import annotations

from howlwriter.evaluation.metrics import MeaningPreservationEvaluator
from howlwriter.evaluation.models import BenchmarkCase, CandidateOutput


def test_meaning_preservation_faithful_rewrite():
    original = "The contract requires forty-five thousand dollars ($45,000) and 90 days."
    rewrite = "The agreement costs $45,000 and requires 90 days."
    case = BenchmarkCase(id="mp_case_1", input_text=original)
    cand = CandidateOutput(candidate_id="c1", system_id="hw", text=rewrite)

    evaluator = MeaningPreservationEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score >= 0.8
    assert score.details["severe_diff_count"] == 0


def test_meaning_preservation_flags_number_and_polarity_changes():
    original = "The system does not allow anonymous writes and costs $5,000."
    # Changed does not allow -> allows (polarity flip), and changed 5000 -> 9000
    corrupted = "The system allows anonymous writes and costs $9,000."
    case = BenchmarkCase(id="mp_case_2", input_text=original)
    cand = CandidateOutput(candidate_id="c2", system_id="bad_system", text=corrupted)

    evaluator = MeaningPreservationEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score < 0.7
    assert score.details["status"] == "FLAGGED"
    assert score.details["severe_diff_count"] > 0
