"""Unit tests for evaluation data models and serialization."""

from __future__ import annotations

import json
from howlwriter.evaluation.models import (
    BaselineType,
    BenchmarkCase,
    BenchmarkRun,
    BenchmarkSuite,
    CandidateOutput,
    CaseEvaluationResult,
    IndependenceStatus,
    MetricScore,
    PairwiseComparison,
)


def test_benchmark_case_serialization():
    case = BenchmarkCase(
        id="test_case_001",
        mode="academic",
        category="academic/research",
        task="Test task description.",
        requirements={"min_words": 100, "max_words": 200},
        metrics=["requirement_satisfaction", "factuality"],
    )

    data = case.to_dict()
    assert data["id"] == "test_case_001"
    assert data["mode"] == "academic"
    assert data["requirements"]["min_words"] == 100

    reconstructed = BenchmarkCase.from_dict(data)
    assert reconstructed.id == case.id
    assert reconstructed.requirements == case.requirements


def test_candidate_output_serialization():
    cand = CandidateOutput(
        candidate_id="cand_a",
        system_id="strong_prompt",
        text="Sample output text.",
        latency_seconds=2.45,
        token_usage={"total_tokens": 150},
        model_calls=1,
        success=True,
    )
    d = cand.to_dict()
    assert d["latency_seconds"] == 2.45
    assert d["success"] is True

    restored = CandidateOutput.from_dict(d)
    assert restored.system_id == "strong_prompt"
    assert restored.latency_seconds == 2.45


def test_pairwise_comparison_serialization():
    comp = PairwiseComparison(
        case_id="case_1",
        candidate_a_system="howlwriter_full",
        candidate_b_system="strong_prompt",
        winner="A",
        winning_system="howlwriter_full",
        dimension_scores={"clarity": "A", "conciseness": "TIE"},
        independence_status=IndependenceStatus.INDEPENDENT.value,
        position_order=["howlwriter_full", "strong_prompt"],
    )
    d = comp.to_dict()
    assert d["winner"] == "A"
    assert d["winning_system"] == "howlwriter_full"
    assert d["independence_status"] == "INDEPENDENT"


def test_benchmark_run_serialization():
    run = BenchmarkRun(
        run_id="bench-123",
        suite_name="core",
        timestamp="2026-09-11T12:00:00Z",
        baselines=["raw_model", "strong_prompt", "howlwriter_full"],
        repeat=1,
        summary={"total_cases": 1},
    )
    json_str = run.to_json()
    assert "bench-123" in json_str
    parsed = json.loads(json_str)
    assert parsed["suite_name"] == "core"
