"""Unit tests for baseline fairness, prompt engineering, and execution paths."""

from __future__ import annotations

from howlwriter.evaluation.baselines import (
    BaselineRunner,
    build_raw_prompt,
    build_strong_prompt,
)
from howlwriter.evaluation.models import BenchmarkCase


def test_build_raw_prompt():
    case = BenchmarkCase(
        id="raw_test_1",
        task="Explain Raft consensus.",
        input_text="Draft outline.",
        source_corpus=[{"title": "Raft Paper", "snippet": "In search of an understandable consensus algorithm."}],
    )
    raw = build_raw_prompt(case)
    assert "Explain Raft consensus." in raw
    assert "Original text:" in raw
    assert "Raft Paper" in raw


def test_build_strong_prompt_fairness():
    case = BenchmarkCase(
        id="strong_test_1",
        task="Compare privacy laws.",
        requirements={
            "min_words": 200,
            "max_words": 400,
            "required_sections": ["Background", "Analysis"],
            "required_points": ["Article 83 fines", "Territorial scope"],
            "citations": "required",
            "forbidden_words": ["delve", "tapestry"],
        },
        source_corpus=[
            {
                "title": "GDPR Official Text",
                "authors": ["EU Council"],
                "year": 2016,
                "url": "https://eur-lex.europa.eu",
                "doi": "10.1000/182",
                "snippet": "Article 83 outlines administrative fines up to 20M EUR.",
            }
        ],
    )
    strong = build_strong_prompt(case)
    # Check that strong prompt does not handicap the baseline: receives all requirements and sources
    assert "Between 200 and 400 words" in strong or "between 200 and 400" in strong
    assert "Background" in strong and "Analysis" in strong
    assert "Article 83 fines" in strong
    assert "Citations: Required" in strong
    assert "delve" in strong and "tapestry" in strong
    assert "GDPR Official Text" in strong
    assert "10.1000/182" in strong


def test_baseline_runner_mock_execution():
    case = BenchmarkCase(
        id="runner_test_1",
        task="Write technical documentation.",
        requirements={"min_words": 50, "max_words": 150},
    )

    runner = BaselineRunner(mock_generator=lambda sys, p: f"Mock output from {sys} with 60 words for the test.")
    raw_out = runner.run_raw_model(case)
    assert raw_out.system_id == "raw_model"
    assert raw_out.success is True
    assert "Mock output from raw_model" in raw_out.text

    strong_out = runner.run_strong_prompt(case)
    assert strong_out.system_id == "strong_prompt"
    assert strong_out.success is True
    assert "Mock output from strong_prompt" in strong_out.text

    min_out = runner.run_howlwriter_minimal(case)
    assert min_out.system_id == "howlwriter_minimal"
    assert min_out.success is True

    full_out = runner.run_howlwriter_full(case)
    assert full_out.system_id == "howlwriter_full"
    assert full_out.success is True
