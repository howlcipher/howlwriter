"""Rigorous statistical inference engine for empirical benchmark results.

Provides:
- Descriptive statistics (mean, median, standard deviation, IQR)
- Win / loss / tie counts
- Wilson score confidence interval for proportions
- Exact two-sided binomial sign test
- Non-parametric bootstrap 95% confidence intervals
- Effect sizes (Cohen's d, Cliff's delta)
- Statistical guard: INSUFFICIENT EVIDENCE when sample size is too small
- Outcome verdicts: HOWLWRITER WINS, BASELINE WINS, TIE, INCONCLUSIVE
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any, Sequence

MIN_SAMPLES_FOR_INFERENCE = 5


def compute_descriptive_stats(values: Sequence[float]) -> dict[str, float | None]:
    """Calculates standard descriptive statistics."""
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "stdev": None,
            "min": None,
            "max": None,
        }

    n = len(values)
    mean_val = statistics.mean(values)
    median_val = statistics.median(values)
    stdev_val = statistics.stdev(values) if n > 1 else 0.0

    return {
        "n": n,
        "mean": round(mean_val, 4),
        "median": round(median_val, 4),
        "stdev": round(stdev_val, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def wilson_score_interval(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """Computes the Wilson score confidence interval for a binomial proportion."""
    if trials <= 0:
        return (0.0, 0.0)

    # Standard normal z-value (approx 1.96 for 95%)
    z = 1.95996 if abs(confidence - 0.95) < 0.01 else 1.64485
    p_hat = successes / trials
    denom = 1.0 + (z**2 / trials)
    center = (p_hat + (z**2 / (2 * trials))) / denom
    spread = (z / denom) * math.sqrt((p_hat * (1 - p_hat) / trials) + (z**2 / (4 * trials**2)))

    ci_lower = max(0.0, center - spread)
    ci_upper = min(1.0, center + spread)
    return (round(ci_lower, 4), round(ci_upper, 4))


def exact_binomial_sign_test(wins_a: int, wins_b: int) -> float:
    """Computes the two-sided exact binomial p-value under null hypothesis p = 0.5."""
    n = wins_a + wins_b
    if n == 0:
        return 1.0

    k = min(wins_a, wins_b)
    # Cumulative probability of k or fewer successes in n trials with p=0.5
    cum_prob = 0.0
    for i in range(k + 1):
        combinations = math.comb(n, i)
        cum_prob += combinations * (0.5**n)

    # Two-sided test
    p_value = min(1.0, 2.0 * cum_prob)
    return round(p_value, 4)


def bootstrap_mean_diff_ci(
    group_a: Sequence[float],
    group_b: Sequence[float],
    iterations: int = 1000,
    seed: int = 42,
) -> tuple[float, float]:
    """Computes 95% bootstrap confidence interval for the difference (A - B) in means."""
    if len(group_a) != len(group_b) or len(group_a) < 2:
        return (0.0, 0.0)

    rng = random.Random(seed)
    n = len(group_a)
    diffs = [a - b for a, b in zip(group_a, group_b)]
    bootstrap_means = []

    for _ in range(iterations):
        sample = [rng.choice(diffs) for _ in range(n)]
        bootstrap_means.append(statistics.mean(sample))

    bootstrap_means.sort()
    low_idx = int(0.025 * iterations)
    high_idx = int(0.975 * iterations)

    return (round(bootstrap_means[low_idx], 4), round(bootstrap_means[high_idx], 4))


def cohens_d(group_a: Sequence[float], group_b: Sequence[float]) -> float | None:
    """Calculates Cohen's d effect size between two groups using pooled standard deviation."""
    if not group_a or not group_b or (len(group_a) + len(group_b) <= 2):
        return None

    mean_a = statistics.mean(group_a)
    mean_b = statistics.mean(group_b)
    var_a = statistics.variance(group_a) if len(group_a) > 1 else 0.0
    var_b = statistics.variance(group_b) if len(group_b) > 1 else 0.0
    n_a = len(group_a)
    n_b = len(group_b)

    denom = n_a + n_b - 2
    if denom <= 0:
        return 0.0

    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / denom
    if pooled_var <= 0.0:
        return 0.0
    pooled_sd = math.sqrt(pooled_var)
    return round((mean_a - mean_b) / pooled_sd, 4)


def cliffs_delta(group_a: Sequence[float], group_b: Sequence[float]) -> float | None:
    """Calculates Cliff's delta non-parametric effect size."""
    if not group_a or not group_b:
        return None

    more = 0
    less = 0
    for a in group_a:
        for b in group_b:
            if a > b:
                more += 1
            elif a < b:
                less += 1

    total = len(group_a) * len(group_b)
    if total == 0:
        return 0.0
    return round((more - less) / total, 4)


def determine_verdict(
    wins_hw: int,
    wins_baseline: int,
    ties: int,
    ci_diff: tuple[float, float] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Produces the definitive evaluation verdict according to empirical rigor."""
    total_trials = wins_hw + wins_baseline + ties
    decisive_trials = wins_hw + wins_baseline

    if total_trials < MIN_SAMPLES_FOR_INFERENCE:
        return {
            "verdict": "INCONCLUSIVE",
            "reason": f"INSUFFICIENT EVIDENCE: Sample size ({total_trials}) is below minimum threshold ({MIN_SAMPLES_FOR_INFERENCE}).",
            "p_value": None,
            "win_rate_hw": (wins_hw / total_trials) if total_trials else 0.0,
            "win_rate_baseline": (wins_baseline / total_trials) if total_trials else 0.0,
            "tie_rate": (ties / total_trials) if total_trials else 0.0,
        }

    p_value = exact_binomial_sign_test(wins_hw, wins_baseline)
    hw_win_rate = wins_hw / total_trials
    baseline_win_rate = wins_baseline / total_trials
    tie_rate = ties / total_trials

    # If confidence interval for mean difference is available
    if ci_diff is not None:
        ci_lower, ci_upper = ci_diff
        if ci_lower > 0.0 and p_value < alpha:
            verdict = "HOWLWRITER WINS"
            reason = f"Statistically significant advantage (p={p_value:.4f} < {alpha}, 95% CI [{ci_lower}, {ci_upper}])."
        elif ci_upper < 0.0 and p_value < alpha:
            verdict = "BASELINE WINS"
            reason = f"Statistically significant baseline advantage (p={p_value:.4f} < {alpha}, 95% CI [{ci_lower}, {ci_upper}])."
        elif abs(ci_lower) < 0.05 and abs(ci_upper) < 0.05 and tie_rate > 0.4:
            verdict = "TIE"
            reason = "No meaningful effect size observed between systems; differences within margin of equivalence."
        else:
            verdict = "INCONCLUSIVE"
            reason = f"Confidence intervals overlap zero [{ci_lower}, {ci_upper}]; p={p_value:.4f} does not clear threshold."
    else:
        if p_value < alpha and wins_hw > wins_baseline:
            verdict = "HOWLWRITER WINS"
            reason = f"Sign test p={p_value:.4f} indicates significant HowlWriter advantage."
        elif p_value < alpha and wins_baseline > wins_hw:
            verdict = "BASELINE WINS"
            reason = f"Sign test p={p_value:.4f} indicates significant Baseline advantage."
        elif decisive_trials > 0 and abs(wins_hw - wins_baseline) <= 1:
            verdict = "TIE"
            reason = "Win counts are evenly matched."
        else:
            verdict = "INCONCLUSIVE"
            reason = f"Sign test p={p_value:.4f} does not reach statistical significance at alpha={alpha}."

    return {
        "verdict": verdict,
        "reason": reason,
        "p_value": p_value,
        "win_rate_hw": round(hw_win_rate, 4),
        "win_rate_baseline": round(baseline_win_rate, 4),
        "tie_rate": round(tie_rate, 4),
    }
