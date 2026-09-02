"""Stage 11: check the profile against writing it never saw.

The holdout documents were set aside before aggregation ran and have had no
influence on any trait value. Now they get used once, to answer a narrow
question: does this profile describe writing from the same corpus that it was
not fitted to?

What this is NOT is the important part. It is not authorship detection. It
cannot say "87% chance this person wrote this", and there is deliberately no
code path here that could produce such a number, because the measurement does
not support the claim: it compares one set of documents against a profile
built from another set of documents by the same author, which says nothing
about what a third party's writing would score.

So results are reported as alignment bands per dimension. A dimension that
lands STRONG means the profile predicted unseen writing well on that axis. A
WEAK dimension means the corpus is inconsistent on it, which is useful
information about the corpus rather than a verdict on anyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.domain.voice import ValidationSummary
from howlwriter.voice.corpus.aggregate import (
    SUFFICIENCY_ADEQUATE,
    SUFFICIENCY_LIMITED,
    SUFFICIENCY_STRONG,
    DocumentEvidence,
    _aggregate_distributions,
)

STRONG = "STRONG"
MODERATE = "MODERATE"
WEAK = "WEAK"
NOT_EVALUATED = "NOT_EVALUATED"

#: Relative-difference thresholds for the alignment bands. Generous on
#: purpose: the same author varies between documents, and a profile that
#: only scored STRONG on near-identical writing would be measuring
#: repetition rather than voice.
STRONG_THRESHOLD = 0.18
MODERATE_THRESHOLD = 0.42

#: Rates that sit near zero need an absolute floor -- going from 0.01 to 0.02
#: is a 100% relative change and means nothing.
_ABSOLUTE_FLOOR = {
    "question_rate": 0.05, "exclamation_rate": 0.05, "semicolon_rate": 0.15,
    "em_dash_rate": 0.20, "contraction_rate": 0.25, "first_person_rate": 0.35,
    "second_person_rate": 0.35, "parenthetical_rate": 0.30, "list_rate": 0.10,
    "heading_rate": 0.10, "fragment_rate": 0.04, "repetition_rate": 0.05,
    "sentence_initial_conjunction_rate": 0.03, "transition_rate": 0.06,
    "passive_rate": 0.08, "colon_rate": 0.20, "comma_rate": 1.0,
    "quote_rate": 0.30, "long_word_rate": 0.03, "lexical_diversity": 0.04,
}

#: The dimensions reported to the user, and the features behind each.
DIMENSIONS: dict[str, tuple[str, ...]] = {
    "sentence_cadence": ("sentence_length_mean", "sentence_length_stdev"),
    "sentence_length_distribution": (
        "sentence_length_median", "sentence_length_p10", "sentence_length_p90",
    ),
    "paragraph_structure": ("paragraph_words_mean", "paragraph_sentences_mean"),
    "lexical_complexity": ("long_word_rate", "mean_word_length", "readability_grade"),
    "lexical_diversity": ("lexical_diversity",),
    "punctuation": (
        "comma_rate", "semicolon_rate", "colon_rate", "em_dash_rate", "parenthetical_rate",
    ),
    "contractions": ("contraction_rate",),
    "first_person_use": ("first_person_rate",),
    "transitions": ("transition_rate", "sentence_initial_conjunction_rate"),
    "formality": ("contraction_rate", "long_word_rate", "passive_rate"),
    "directness": ("sentence_length_mean", "transition_rate", "passive_rate"),
    "structural_rhythm": ("heading_rate", "list_rate", "repetition_rate"),
}


@dataclass
class DimensionResult:
    name: str
    band: str = NOT_EVALUATED
    deviation: float = 0.0
    detail: dict[str, float] = field(default_factory=dict)


@dataclass
class ValidationResult:
    dimensions: list[DimensionResult] = field(default_factory=list)
    overall_confidence: str = "UNKNOWN"
    holdout_documents: int = 0
    holdout_words: int = 0
    performed: bool = False
    warnings: list[str] = field(default_factory=list)

    def alignment(self) -> dict[str, str]:
        return {d.name: d.band for d in self.dimensions}


def _relative_difference(feature: str, expected: float, actual: float) -> float:
    """Scale-aware difference between a profile value and a holdout value."""
    floor = _ABSOLUTE_FLOOR.get(feature, 0.0)
    denominator = max(abs(expected), floor)
    if denominator <= 0:
        return 0.0 if abs(actual) <= floor else 1.0
    return abs(actual - expected) / denominator


def _band(deviation: float) -> str:
    if deviation <= STRONG_THRESHOLD:
        return STRONG
    if deviation <= MODERATE_THRESHOLD:
        return MODERATE
    return WEAK


def validate(
    *,
    train: list[DocumentEvidence],
    holdout: list[DocumentEvidence],
    corpus_sufficiency: str,
) -> ValidationResult:
    """Compare holdout writing against the profile built without it."""
    result = ValidationResult(
        holdout_documents=len(holdout),
        holdout_words=sum(doc.words for doc in holdout),
    )

    if not holdout:
        result.warnings.append(
            "no holdout documents; the corpus was too small to hold any back, so the "
            "profile was not validated against unseen writing"
        )
        result.overall_confidence = _overall(corpus_sufficiency, [], performed=False)
        return result
    if not train:
        result.warnings.append("no training documents to validate against")
        return result

    expected = _aggregate_distributions(train)
    actual = _aggregate_distributions(holdout)
    result.performed = True

    for name, features in DIMENSIONS.items():
        deviations: list[float] = []
        detail: dict[str, float] = {}
        for feature in features:
            expected_value = float(getattr(expected, feature, 0.0) or 0.0)
            actual_value = float(getattr(actual, feature, 0.0) or 0.0)
            deviation = _relative_difference(feature, expected_value, actual_value)
            deviations.append(deviation)
            detail[feature] = round(deviation, 3)
        combined = sum(deviations) / len(deviations) if deviations else 0.0
        result.dimensions.append(DimensionResult(
            name=name, band=_band(combined), deviation=round(combined, 3), detail=detail,
        ))

    if len(holdout) < 3:
        result.warnings.append(
            f"only {len(holdout)} holdout document(s); alignment bands are indicative "
            "rather than reliable"
        )

    result.overall_confidence = _overall(
        corpus_sufficiency, [d.band for d in result.dimensions], performed=True
    )
    return result


def _overall(corpus_sufficiency: str, bands: list[str], *, performed: bool) -> str:
    """Fold sufficiency and alignment into one honest band.

    Corpus sufficiency caps the result: a profile from a thin corpus cannot
    report HIGH confidence no matter how neatly its few documents agreed.
    """
    if not performed or not bands:
        return {
            SUFFICIENCY_STRONG: "MEDIUM",
            SUFFICIENCY_ADEQUATE: "MEDIUM_LOW",
        }.get(corpus_sufficiency, "LOW")

    strong = sum(1 for band in bands if band == STRONG)
    weak = sum(1 for band in bands if band == WEAK)
    share_strong = strong / len(bands)

    if share_strong >= 0.6 and weak <= 1:
        level = "HIGH"
    elif share_strong >= 0.4 and weak <= 3:
        level = "MEDIUM"
    elif weak >= len(bands) / 2:
        level = "LOW"
    else:
        level = "MEDIUM_LOW"

    cap = {
        SUFFICIENCY_STRONG: "HIGH",
        SUFFICIENCY_ADEQUATE: "MEDIUM",
        SUFFICIENCY_LIMITED: "MEDIUM_LOW",
    }.get(corpus_sufficiency, "LOW")
    order = ["LOW", "MEDIUM_LOW", "MEDIUM", "HIGH"]
    return order[min(order.index(level), order.index(cap))]


def to_summary(result: ValidationResult, diversity: str = NOT_EVALUATED) -> ValidationSummary:
    return ValidationSummary(
        alignment=result.alignment(),
        overall_confidence=result.overall_confidence,
        holdout_documents=result.holdout_documents,
        holdout_words=result.holdout_words,
        diversity_preservation=diversity,
        warnings=list(result.warnings),
    )
