"""The check that catches a profile turning into a costume.

The failure mode this exists for is subtle and would otherwise ship. Apply a
personal voice hard enough and every output starts arriving in the same
shape: the same kind of opening, the same paragraph count, the same closing
move, the same three-beat rhythm. Each individual piece reads fine. Together
they read as an impression of a person rather than as that person, who in
real life writes a 90-word note and a 4000-word paper and does not sound
identical in both.

So generated output is measured against the corpus it came from. Real writing
varies by a certain amount across documents; generated writing should vary by
a comparable amount. Substantially less variation means the profile is being
applied as a template, and the fix belongs in the application layer -- not in
compensating with more literal detail, which would make the cloning worse.

This is a heuristic guard, not a metric. It is calibrated to catch obvious
convergence and to stay quiet otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import statistics

from howlwriter.voice.corpus.features import DocumentFeatures, extract_features

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
NOT_EVALUATED = "NOT_EVALUATED"

#: Generated variation below this share of the corpus's own variation on a
#: dimension counts as convergence on that dimension.
CONVERGENCE_RATIO = 0.45

#: A dimension where the corpus itself barely varies cannot show convergence,
#: so it is skipped rather than counted as a false positive.
MIN_CORPUS_VARIATION = 0.08

#: How many dimensions must converge before the verdict moves.
WARNING_DIMENSIONS = 2
FAIL_DIMENSIONS = 4

#: Share of outputs that may share a two-word opening before it is a tic.
MAX_SHARED_OPENING_SHARE = 0.35
MAX_SHARED_CLOSING_SHARE = 0.35

#: Minimum outputs needed to say anything about variation at all.
MIN_SAMPLES = 4

_DIMENSIONS = (
    "sentence_length_mean",
    "sentence_length_stdev",
    "paragraph_words_mean",
    "paragraph_sentences_mean",
    "lexical_diversity",
    "transition_rate",
    "contraction_rate",
    "first_person_rate",
    "question_rate",
    "long_word_rate",
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class DimensionComparison:
    name: str
    corpus_variation: float = 0.0
    generated_variation: float = 0.0
    ratio: float = 1.0
    converged: bool = False


@dataclass
class DiversityResult:
    verdict: str = NOT_EVALUATED
    dimensions: list[DimensionComparison] = field(default_factory=list)
    repeated_openings: dict[str, int] = field(default_factory=dict)
    repeated_closings: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    samples: int = 0

    @property
    def converged_dimensions(self) -> list[str]:
        return [d.name for d in self.dimensions if d.converged]


def _coefficient_of_variation(values: list[float]) -> float:
    """Spread relative to size, so dimensions on different scales compare."""
    usable = [v for v in values if v is not None]
    if len(usable) < 2:
        return 0.0
    mean = statistics.mean(usable)
    if abs(mean) < 1e-9:
        return 0.0
    return statistics.pstdev(usable) / abs(mean)


def _opening_key(text: str) -> str:
    words = _WORD.findall(text.strip())
    return " ".join(w.lower() for w in words[:2]) if len(words) >= 2 else ""


def _closing_key(text: str) -> str:
    sentences = [s for s in _SENTENCE.split(text.strip()) if s.strip()]
    if not sentences:
        return ""
    words = _WORD.findall(sentences[-1])
    return " ".join(w.lower() for w in words[:3]) if len(words) >= 3 else ""


def _repeats(keys: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in keys:
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {key: count for key, count in counts.items() if count > 1}


def compare(
    corpus_features: list[DocumentFeatures],
    generated_texts: list[str],
) -> DiversityResult:
    """Compare generated variation against the corpus's own variation.

    `corpus_features` should be the TRAINING documents only. Feature vectors
    for documents that produced no measurable text are dropped here rather
    than trusted: a zero vector is not a document that happens to have short
    sentences, and during dogfood a single one of them inflated the baseline
    coefficient of variation elevenfold, which would have reported a false
    convergence failure.
    """
    result = DiversityResult(samples=len(generated_texts))

    usable_corpus = [f for f in corpus_features if f.words > 0 and f.sentences > 0]
    dropped = len(corpus_features) - len(usable_corpus)
    if dropped:
        result.notes.append(
            f"ignored {dropped} corpus feature vector(s) with no measurable text"
        )

    if len(generated_texts) < MIN_SAMPLES or len(usable_corpus) < 2:
        result.verdict = NOT_EVALUATED
        result.notes.append(
            f"needs at least {MIN_SAMPLES} generated outputs and 2 corpus documents; "
            f"got {len(generated_texts)} and {len(usable_corpus)}"
        )
        return result

    generated_features = [
        f for f in (extract_features(text) for text in generated_texts)
        if f.words > 0 and f.sentences > 0
    ]
    if len(generated_features) < MIN_SAMPLES:
        result.verdict = NOT_EVALUATED
        result.notes.append(
            f"only {len(generated_features)} generated outputs held measurable text"
        )
        return result

    # Comparing a corpus of long documents against a handful of very short
    # outputs measures length, not voice. Say so rather than reporting a
    # convergence failure that the sample sizes guaranteed.
    corpus_median = statistics.median(f.words for f in usable_corpus)
    generated_median = statistics.median(f.words for f in generated_features)
    if generated_median * 4 < corpus_median:
        result.notes.append(
            f"generated outputs are much shorter than the corpus "
            f"(median {generated_median:.0f} vs {corpus_median:.0f} words); "
            "structural comparisons below are weakened by that difference"
        )

    corpus_features = usable_corpus

    for name in _DIMENSIONS:
        corpus_variation = _coefficient_of_variation(
            [float(getattr(f, name, 0.0) or 0.0) for f in corpus_features]
        )
        generated_variation = _coefficient_of_variation(
            [float(getattr(f, name, 0.0) or 0.0) for f in generated_features]
        )
        if corpus_variation < MIN_CORPUS_VARIATION:
            # The corpus does not vary here either, so there is nothing to
            # converge away from.
            result.dimensions.append(DimensionComparison(
                name=name, corpus_variation=round(corpus_variation, 3),
                generated_variation=round(generated_variation, 3), ratio=1.0,
            ))
            continue
        ratio = generated_variation / corpus_variation
        result.dimensions.append(DimensionComparison(
            name=name,
            corpus_variation=round(corpus_variation, 3),
            generated_variation=round(generated_variation, 3),
            ratio=round(ratio, 3),
            converged=ratio < CONVERGENCE_RATIO,
        ))

    result.repeated_openings = _repeats([_opening_key(t) for t in generated_texts])
    result.repeated_closings = _repeats([_closing_key(t) for t in generated_texts])

    converged = result.converged_dimensions
    total = len(generated_texts)
    worst_opening = max(result.repeated_openings.values(), default=0)
    worst_closing = max(result.repeated_closings.values(), default=0)
    opening_share = worst_opening / total
    closing_share = worst_closing / total

    if converged:
        result.notes.append(
            "generated output varies much less than the corpus on: " + ", ".join(converged)
        )
    if opening_share > MAX_SHARED_OPENING_SHARE:
        result.notes.append(
            f"{worst_opening} of {total} outputs share the same two-word opening"
        )
    if closing_share > MAX_SHARED_CLOSING_SHARE:
        result.notes.append(
            f"{worst_closing} of {total} outputs end the same way"
        )

    tic_failure = opening_share > MAX_SHARED_OPENING_SHARE or closing_share > MAX_SHARED_CLOSING_SHARE

    if len(converged) >= FAIL_DIMENSIONS or (len(converged) >= WARNING_DIMENSIONS and tic_failure):
        result.verdict = FAIL
    elif len(converged) >= WARNING_DIMENSIONS or tic_failure:
        result.verdict = WARNING
    else:
        result.verdict = PASS
        result.notes.append(
            "generated output varies comparably to the corpus across every dimension checked"
        )
    return result
