"""Unit tests for structural diversity and template convergence detection."""

from __future__ import annotations

from howlwriter.evaluation.metrics import StructuralDiversityEvaluator
from howlwriter.evaluation.models import CandidateOutput
from howlwriter.voice.corpus.diversity import FAIL, PASS


def test_structural_diversity_high_variation():
    # Varied outputs: short sentences, long sentences, different paragraph structures
    diverse_outputs = [
        CandidateOutput(candidate_id="c1", system_id="sys", text="Very brief note here. Simple and fast. Done."),
        CandidateOutput(
            candidate_id="c2",
            system_id="sys",
            text=(
                "In evaluating the distributed consensus mechanism, one must account for the rigorous mathematical "
                "formulation of safety invariants under arbitrary asynchronous network partitions where message loss "
                "and replication delays predominate over local memory serialization limits.\n\n"
                "Furthermore, empirical benchmarking across fifty geo-distributed nodes demonstrates acceptable latencies."
            ),
        ),
        CandidateOutput(
            candidate_id="c3",
            system_id="sys",
            text="I debugged the system. It took three hours! Everything is working now.",
        ),
        CandidateOutput(
            candidate_id="c4",
            system_id="sys",
            text="Technical specification.\n\n## Section 1\n\nRule A applies.\n\n## Section 2\n\nRule B applies.",
        ),
    ]

    evaluator = StructuralDiversityEvaluator()
    res = evaluator.evaluate_batch(diverse_outputs)

    assert res.details["verdict"] in (PASS, "WARNING")
    assert res.score > 0.4


def test_structural_diversity_catches_convergence_and_hw_losing():
    # Rigid templated outputs: identical sentence length and paragraph structure every time
    template = (
        "In evaluating the operational framework, systematic verification guarantees reliability across all operational boundaries. "
        "Modern engineering practices demonstrate consistent performance across distributed clusters."
    )
    converged_outputs = [
        CandidateOutput(candidate_id=f"c{i}", system_id="howlwriter_full", text=template)
        for i in range(5)
    ]

    evaluator = StructuralDiversityEvaluator()
    res = evaluator.evaluate_batch(converged_outputs)

    # Must detect convergence and assign FAIL or low score
    assert res.details["verdict"] == FAIL
    assert len(res.details["converged_dimensions"]) >= 4
    assert res.score < 0.2, "Rigid templated outputs must receive a low diversity score"
