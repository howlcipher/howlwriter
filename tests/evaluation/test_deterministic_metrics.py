"""Unit tests for deterministic metric evaluation."""

from __future__ import annotations

from howlwriter.evaluation.metrics import (
    RequirementSatisfactionEvaluator,
    WritingQualitySignalsEvaluator,
)
from howlwriter.evaluation.models import BenchmarkCase, CandidateOutput


def test_requirement_satisfaction_full_pass():
    case = BenchmarkCase(
        id="case_req_1",
        requirements={
            "min_words": 10,
            "max_words": 50,
            "required_sections": ["Overview", "Details"],
            "required_points": ["quantum resistance", "key encapsulation"],
            "verbatim_phrases": ["FIPS 203"],
            "forbidden_words": ["delve"],
        },
    )
    text = (
        "## Overview\n"
        "This standard specifies quantum resistance mechanisms.\n\n"
        "## Details\n"
        "The standard defines FIPS 203 key encapsulation procedures."
    )
    cand = CandidateOutput(candidate_id="c1", system_id="hw", text=text)
    evaluator = RequirementSatisfactionEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score == 1.0
    assert score.details["required_sections"]["passed"] is True
    assert score.details["required_points"]["passed"] is True
    assert score.details["verbatim_retention"]["passed"] is True
    assert score.details["forbidden_words"]["passed"] is True


def test_requirement_satisfaction_penalizes_violations():
    case = BenchmarkCase(
        id="case_req_2",
        requirements={
            "min_words": 50,
            "max_words": 100,
            "required_sections": ["Mandatory Section A", "Mandatory Section B"],
            "verbatim_phrases": ["Exact Preserved Phrase"],
            "forbidden_words": ["delve"],
        },
    )
    # Too short, missing section B, missing verbatim, contains forbidden word
    text = "## Mandatory Section A\nWe will delve into the problem."
    cand = CandidateOutput(candidate_id="c2", system_id="hw", text=text)
    evaluator = RequirementSatisfactionEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score < 0.6
    assert score.details["length_compliance"]["passed"] is False
    assert "Mandatory Section B" in score.details["required_sections"]["missing"]
    assert "delve" in score.details["forbidden_words"]["found"]


def test_writing_quality_signals():
    case = BenchmarkCase(id="q_case_1")
    clean_text = (
        "Distributed systems require formal invariants for leader election and state synchronization. "
        "Consensus algorithms like Raft guarantee safety under network partitions."
    )
    cand = CandidateOutput(candidate_id="c1", system_id="hw", text=clean_text)
    evaluator = WritingQualitySignalsEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score >= 0.95
    assert score.details["lint_violations_count"] == 0
