"""Unit tests for multidimensional voice fidelity evaluation."""

from __future__ import annotations

from howlwriter.evaluation.metrics import VoiceFidelityEvaluator
from howlwriter.evaluation.models import BenchmarkCase, CandidateOutput
from howlwriter.voice.corpus.features import DocumentFeatures


def test_voice_fidelity_multidimensional_no_fake_percentage():
    case = BenchmarkCase(id="v_case_1")
    text = (
        "I woke up early. The servers were unresponsive and deadlocked. "
        "We restarted the cluster, but the memory pressure remained high."
    )
    cand = CandidateOutput(candidate_id="c1", system_id="hw", text=text)

    evaluator = VoiceFidelityEvaluator()
    score = evaluator.evaluate(case, cand)

    # Must provide multidimensional profile
    details = score.details
    assert "multidimensional_profile" in details
    profile = details["multidimensional_profile"]
    assert "sentence_length_mean" in profile
    assert "first_person_rate" in profile
    assert profile["first_person_rate"] > 0.0


def test_voice_fidelity_comparison_against_reference():
    case = BenchmarkCase(id="v_case_2")
    text = "Short sentences. Very punchy. I write like this."
    cand = CandidateOutput(candidate_id="c1", system_id="hw", text=text)

    reference = DocumentFeatures(
        sentence_length_mean=4.0,
        sentence_length_stdev=1.0,
        paragraph_words_mean=10.0,
        first_person_rate=0.25,
        lexical_diversity=0.8,
    )

    evaluator = VoiceFidelityEvaluator()
    score = evaluator.evaluate(case, cand, reference_features=reference)

    assert score.score > 0.7
    assert "multidimensional_dimensions" in score.details
    assert "sentence_length_mean" in score.details["multidimensional_dimensions"]
