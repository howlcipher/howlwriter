"""Unit tests for statistical inference and significance guards."""

from __future__ import annotations

from howlwriter.evaluation.statistics import (
    bootstrap_mean_diff_ci,
    cliffs_delta,
    cohens_d,
    compute_descriptive_stats,
    determine_verdict,
    exact_binomial_sign_test,
    wilson_score_interval,
)


def test_descriptive_statistics():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = compute_descriptive_stats(vals)
    assert stats["n"] == 5
    assert stats["mean"] == 30.0
    assert stats["median"] == 30.0
    assert stats["min"] == 10.0
    assert stats["max"] == 50.0


def test_wilson_score_interval():
    ci_low, ci_high = wilson_score_interval(successes=9, trials=10)
    assert 0.5 < ci_low < 0.9
    assert ci_high <= 1.0


def test_exact_binomial_sign_test():
    # 10 wins vs 0 losses has very small p-value
    p_val_clear = exact_binomial_sign_test(10, 0)
    assert p_val_clear < 0.01

    # 5 wins vs 5 losses has p-value 1.0
    p_val_even = exact_binomial_sign_test(5, 5)
    assert p_val_even == 1.0


def test_bootstrap_mean_diff_ci():
    a = [0.75, 0.82, 0.91, 0.98, 0.88]
    b = [0.40, 0.52, 0.48, 0.58, 0.45]
    ci_low, ci_high = bootstrap_mean_diff_ci(a, b, iterations=500)
    assert ci_low > 0.2
    assert ci_high >= ci_low


def test_effect_sizes():
    a = [10, 11, 12, 13, 14]
    b = [2, 3, 4, 5, 6]
    d = cohens_d(a, b)
    assert d is not None and d > 2.0

    delta = cliffs_delta(a, b)
    assert delta == 1.0


def test_insufficient_evidence_guard():
    # Only 3 samples total: below minimum threshold
    verdict = determine_verdict(wins_hw=2, wins_baseline=1, ties=0)
    assert verdict["verdict"] == "INCONCLUSIVE"
    assert "INSUFFICIENT EVIDENCE" in verdict["reason"]


def test_decisive_verdicts():
    # 20 wins vs 2 losses: statistically significant
    v_hw = determine_verdict(wins_hw=20, wins_baseline=2, ties=3)
    assert v_hw["verdict"] == "HOWLWRITER WINS"
    assert v_hw["p_value"] < 0.05

    # 2 wins vs 20 losses
    v_base = determine_verdict(wins_hw=2, wins_baseline=20, ties=3)
    assert v_base["verdict"] == "BASELINE WINS"
