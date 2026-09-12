"""Unit tests for blinded pairwise judging and provider independence."""

from __future__ import annotations

from howlwriter.evaluation.judges import (
    DeterministicJudge,
    ScriptedJudge,
)
from howlwriter.evaluation.models import (
    BenchmarkCase,
    CandidateOutput,
    IndependenceStatus,
)


def test_deterministic_judge_rubric():
    case = BenchmarkCase(
        id="j_case_1",
        requirements={"min_words": 10, "max_words": 50, "required_sections": ["Overview"]},
    )
    # Cand 1 satisfies section and length
    cand_1 = CandidateOutput(
        candidate_id="c1",
        system_id="hw_full",
        text="## Overview\nThis text satisfies the required section and length bounds nicely.",
    )
    # Cand 2 has no section and is too short
    cand_2 = CandidateOutput(
        candidate_id="c2",
        system_id="raw_model",
        text="Too short.",
    )

    judge = DeterministicJudge()
    comp = judge.judge(case, cand_1, cand_2, seed=42)

    assert comp.winning_system == "hw_full"
    assert comp.judge_provider == "deterministic_local"
    assert comp.independence_status == IndependenceStatus.INDEPENDENT.value


def test_candidate_blinding_and_position_randomization():
    case = BenchmarkCase(id="j_case_2")
    cand_1 = CandidateOutput(candidate_id="c1", system_id="sys_1", text="Text 1.")
    cand_2 = CandidateOutput(candidate_id="c2", system_id="sys_2", text="Text 2.")

    judge = DeterministicJudge()

    # Over 20 calls with varied seeds, both sys_1 and sys_2 should appear in position A
    positions_for_sys_1 = []
    for s in range(20):
        comp = judge.judge(case, cand_1, cand_2, seed=s)
        positions_for_sys_1.append(comp.position_order[0] == "sys_1")

    assert any(positions_for_sys_1), "sys_1 must appear in position A sometimes"
    assert not all(positions_for_sys_1), "sys_2 must appear in position A sometimes"


def test_scripted_judge():
    case = BenchmarkCase(id="j_case_3")
    c1 = CandidateOutput(candidate_id="c1", system_id="sys_a", text="A")
    c2 = CandidateOutput(candidate_id="c2", system_id="sys_b", text="B")

    judge_a = ScriptedJudge(winner_choice="A")
    comp_a = judge_a.judge(case, c1, c2)
    assert comp_a.winning_system == "sys_a"

    judge_tie = ScriptedJudge(winner_choice="TIE")
    comp_tie = judge_tie.judge(case, c1, c2)
    assert comp_tie.winning_system == "TIE"


def test_judge_calibration_checker_deterministic():
    from howlwriter.evaluation.judges import JudgeCalibrationChecker

    checker = JudgeCalibrationChecker()
    res = checker.calibrate(DeterministicJudge())

    assert res.is_healthy() is True
    assert res.position_bias_detected is False
    assert res.identical_tie_rate == 1.0
    assert res.symmetry_rate == 1.0
    assert res.control_accuracy == 1.0


def test_judge_calibration_checker_detects_position_bias():
    from howlwriter.evaluation.judges import JudgeCalibrationChecker

    class BiasedJudge:
        """Flawed judge that always picks Candidate A regardless of quality."""

        def judge(self, case, cand_1, cand_2, seed=None):
            from howlwriter.evaluation.models import PairwiseComparison
            return PairwiseComparison(
                case_id=case.id,
                candidate_a_system=cand_1.system_id,
                candidate_b_system=cand_2.system_id,
                winner="A",
                winning_system=cand_1.system_id,
                dimension_scores={},
                rationale="Biased towards candidate A.",
            )

    checker = JudgeCalibrationChecker()
    res = checker.calibrate(BiasedJudge())

    assert res.position_bias_detected is True
    assert res.is_healthy() is False

