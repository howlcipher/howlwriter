"""Small, deterministic statistics for calibrated personal scores.

Both personal scores (Naturalness and Voice Match) are defined as empirical
percentiles against a reference set, and both are validated by asking how
well they separate the reference set from controls. That needs four things
and nothing more exotic: a percentile with sensible tie handling, a robust
location and scale, the Mann-Whitney AUC, and a standard error for it.

No random number generator is used anywhere. Confidence intervals come from
the Hanley-McNeil approximation rather than a bootstrap, so two runs over the
same data report identical numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable, Sequence


def midrank_percentile(value: float, reference: Sequence[float]) -> float:
    """Share of `reference` below `value`, counting ties as half.

    Returns a fraction in [0, 1]. Ties count half so that a reference full of
    identical values (zero formulaic phrases in every document, say) does not
    put every matching document at the 100th percentile.
    """
    if not reference:
        return 0.5
    below = sum(1 for item in reference if item < value)
    equal = sum(1 for item in reference if item == value)
    return (below + 0.5 * equal) / len(reference)


def survival(value: float, reference: Sequence[float]) -> float:
    """Share of `reference` at or above `value`, ties counted half."""
    return 1.0 - midrank_percentile(value, reference)


def quantile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated quantile; 0.0 for an empty sequence."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


@dataclass(frozen=True)
class RobustCentre:
    """Median and a floored robust scale for one feature."""

    median: float
    scale: float

    def z(self, value: float, *, clip: float = 4.0) -> float:
        if self.scale <= 0:
            return 0.0
        return max(-clip, min(clip, (value - self.median) / self.scale))


def robust_centre(values: Sequence[float], *, floor: float) -> RobustCentre:
    """Median, and the larger of the scaled MAD, the scaled IQR, and `floor`.

    The floor matters for small corpora and for near-zero rates: five
    documents that all happen to use no semicolons have a MAD of zero, and an
    unfloored scale would make one semicolon look like an enormous deviation.
    """
    if not values:
        return RobustCentre(0.0, max(floor, 1e-9))
    median = float(statistics.median(values))
    mad = statistics.median(abs(v - median) for v in values) * 1.4826
    iqr = (quantile(values, 0.75) - quantile(values, 0.25)) / 1.349
    return RobustCentre(median, max(mad, iqr, floor, 1e-9))


@dataclass(frozen=True)
class SeparationResult:
    """How well a measure separates a reference set from a control set."""

    auc: float | None
    standard_error: float | None
    reference_n: int
    control_n: int

    @property
    def interval(self) -> tuple[float, float] | None:
        if self.auc is None or self.standard_error is None:
            return None
        low = max(0.0, self.auc - 1.96 * self.standard_error)
        high = min(1.0, self.auc + 1.96 * self.standard_error)
        return (round(low, 3), round(high, 3))

    def to_dict(self) -> dict:
        return {
            "auc": None if self.auc is None else round(self.auc, 3),
            "standard_error": (
                None if self.standard_error is None else round(self.standard_error, 3)
            ),
            "interval_95": self.interval,
            "reference_n": self.reference_n,
            "control_n": self.control_n,
            "method": "Mann-Whitney AUC, Hanley-McNeil standard error",
        }


def separation(
    reference_scores: Iterable[float], control_scores: Iterable[float]
) -> SeparationResult:
    """AUC that a reference item scores HIGHER than a control item.

    0.5 is chance. Ties count half. Returns `auc=None` when either side is
    empty, rather than pretending an untested measure separates anything.
    """
    reference = list(reference_scores)
    control = list(control_scores)
    if not reference or not control:
        return SeparationResult(None, None, len(reference), len(control))
    wins = 0.0
    for r in reference:
        for c in control:
            if r > c:
                wins += 1.0
            elif r == c:
                wins += 0.5
    auc = wins / (len(reference) * len(control))
    # Hanley & McNeil (1982).
    q1 = auc / (2 - auc)
    q2 = 2 * auc * auc / (1 + auc)
    n_r, n_c = len(reference), len(control)
    variance = (auc * (1 - auc) + (n_r - 1) * (q1 - auc * auc) + (n_c - 1) * (q2 - auc * auc)) / (
        n_r * n_c
    )
    return SeparationResult(auc, math.sqrt(max(variance, 0.0)), n_r, n_c)


def describe(values: Sequence[float]) -> dict:
    """Compact distribution summary used in calibration reports."""
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": round(min(values), 4),
        "p10": round(quantile(values, 0.10), 4),
        "p25": round(quantile(values, 0.25), 4),
        "median": round(quantile(values, 0.50), 4),
        "p75": round(quantile(values, 0.75), 4),
        "p90": round(quantile(values, 0.90), 4),
        "max": round(max(values), 4),
    }
