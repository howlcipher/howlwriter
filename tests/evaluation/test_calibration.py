"""Tests for evaluator calibration and self-validation suite."""

from __future__ import annotations

from howlwriter.evaluation.calibration import (
    EvaluatorHealthChecker,
    get_factuality_calibration_case,
)
from howlwriter.evaluation.entailment import (
    DeterministicEntailmentEvaluator,
    EntailmentVerdict,
)
from howlwriter.evaluation.models import EvaluatorHealth


def test_factuality_entailment_calibration_controls():
    checker = EvaluatorHealthChecker()
    case = get_factuality_calibration_case()
    result = checker.check_metric_health("factuality")

    assert result.health == EvaluatorHealth.CALIBRATED
    assert result.positive_controls_passed == result.positive_controls_total
    assert result.negative_controls_passed == result.negative_controls_total
    assert result.sensitivity_gap >= 0.40


def test_entailment_evaluator_paraphrase():
    evaluator = DeterministicEntailmentEvaluator()
    evidence = "The framework was published in February 2024."
    claim = "The framework came out in February of 2024."
    res = evaluator.evaluate(claim, evidence)
    assert res.verdict == EntailmentVerdict.ENTAILED


def test_entailment_evaluator_numeric_contradiction():
    evaluator = DeterministicEntailmentEvaluator()
    evidence = "The sample contained 240 participants."
    claim = "The study included 420 participants."
    res = evaluator.evaluate(claim, evidence)
    assert res.verdict == EntailmentVerdict.CONTRADICTED


def test_entailment_evaluator_unsupported_inference():
    evaluator = DeterministicEntailmentEvaluator()
    evidence = "The framework provides voluntary guidance."
    claim = "The framework reduced breaches by 35%."
    res = evaluator.evaluate(claim, evidence)
    assert res.verdict == EntailmentVerdict.NOT_ENTAILED


def test_entailment_evaluator_modal_overstatement():
    evaluator = DeterministicEntailmentEvaluator()
    evidence = "The intervention may reduce risk in some environments."
    claim = "The intervention eliminates risk."
    res = evaluator.evaluate(claim, evidence)
    assert res.verdict == EntailmentVerdict.CONTRADICTED


def test_voice_fidelity_calibration_controls():
    checker = EvaluatorHealthChecker()
    result = checker.check_metric_health("voice_fidelity")
    assert result.health == EvaluatorHealth.CALIBRATED
    assert result.sensitivity_gap >= 0.30


def test_meaning_preservation_calibration_controls():
    checker = EvaluatorHealthChecker()
    result = checker.check_metric_health("meaning_preservation")
    assert result.health == EvaluatorHealth.CALIBRATED
    assert result.positive_controls_passed == result.positive_controls_total
    assert result.negative_controls_passed == result.negative_controls_total
    assert result.sensitivity_gap >= 0.40


def test_citation_integrity_calibration_controls():
    checker = EvaluatorHealthChecker()
    result = checker.check_metric_health("citation_integrity")
    assert result.health == EvaluatorHealth.CALIBRATED
    assert result.sensitivity_gap >= 0.40


def test_validate_all_evaluators():
    checker = EvaluatorHealthChecker()
    results = checker.validate_all_evaluators()
    assert len(results) >= 5
    for metric_name, result in results.items():
        assert result.health in (EvaluatorHealth.CALIBRATED, EvaluatorHealth.PARTIALLY_CALIBRATED)


def test_calibration_includes_polarity_inversion_controls():
    case = get_factuality_calibration_case()
    texts = [c.description for c in case.negative_controls]
    assert sum("Polarity inversion" in t for t in texts) >= 2
    evaluator = DeterministicEntailmentEvaluator()
    for control in case.negative_controls:
        if "Polarity inversion" in control.description:
            res = evaluator.evaluate(control.input_text, control.reference)
            assert res.verdict == EntailmentVerdict.CONTRADICTED
            assert "Polarity inversion" in res.rationale


def test_negated_evidence_contradicts_positive_claim():
    res = DeterministicEntailmentEvaluator().evaluate(
        "The drug reduces risk in adults", "The drug does not reduce risk in adults."
    )
    assert res.verdict == EntailmentVerdict.CONTRADICTED
    assert res.confidence == 0.85


def test_both_negated_is_not_a_contradiction():
    res = DeterministicEntailmentEvaluator().evaluate(
        "The drug does not reduce risk for adults", "The drug doesn't reduce risk in adults."
    )
    assert res.verdict != EntailmentVerdict.CONTRADICTED


def test_unrelated_not_in_another_clause_is_not_a_contradiction():
    res = DeterministicEntailmentEvaluator().evaluate(
        "The drug reduces risk for adults",
        "The drug reduces risk in adults. It is not approved for children.",
    )
    assert res.verdict != EntailmentVerdict.CONTRADICTED
