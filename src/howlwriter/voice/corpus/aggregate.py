"""Stage 10: combine per-document evidence into a profile, honestly.

Aggregation is where a profile earns or loses the right to be trusted. Two
documents agreeing about someone's formality is not the same claim as
seventeen documents agreeing, and neither is the same as seventeen documents
disagreeing. All three would produce a value; only the evidence attached
tells them apart, so every trait carries its document count, word count, and
cross-document agreement alongside the label.

Confidence here is an explicitly documented heuristic, not a probability. It
rises with how much writing supports a trait and how consistently that
writing agrees, and it is reported in bands rather than decimals wherever a
user sees it. It is not a statistical guarantee and nothing downstream treats
it as one.

The counterweight is sufficiency. A three-document corpus can still produce a
confident-looking mean, so size, balance, and single-document dominance are
checked separately and can hold the whole profile down regardless of how
tidily its individual traits agreed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import statistics

from howlwriter.domain.voice import (
    CorpusSummary,
    RateDistribution,
    TraitValue,
    VoiceContext,
    VoiceDistributions,
)
from howlwriter.voice.corpus.features import (
    COMPARABLE_FEATURES,
    DocumentFeatures,
    percentile as _percentile,
)

#: Evidence targets. Reaching them means "as much evidence as this measure
#: can usefully absorb", not "enough to be certain".
FULL_EVIDENCE_DOCUMENTS = 12
FULL_EVIDENCE_WORDS = 15_000

#: A single document contributing more than this share of the words means the
#: profile is largely describing that one document.
DOMINANCE_THRESHOLD = 0.40

#: Sufficiency floors for the corpus as a whole.
MIN_DOCUMENTS = 5
MIN_WORDS = 3_000

#: A context needs its own evidence before it earns a context block; below
#: this it would just be repeating the global profile with more noise.
MIN_CONTEXT_DOCUMENTS = 3
MIN_CONTEXT_WORDS = 1_200

#: Behaviours a corpus-wide mean actively misdescribes.
#:
#: These are the measures where a large share of documents sit at exactly zero,
#: so the mean lands in a gap between "does not do this" and "does this
#: routinely" and describes neither group. On the corpus this was developed
#: against, every one of them was absent from at least 23% of documents:
#: contractions from 63%, em dashes from 82%, questions from 77%, first person
#: from 42%. The mean first-person rate was 1.01 while the median among
#: documents that use it was 1.36.
#:
#: The list is deliberately fixed rather than derived per corpus. A rule that
#: promoted a measure into this map only when the current corpus happened to be
#: zero-inflated would make the profile schema depend on the data, so two
#: profiles could not be compared field for field. Measures that are not
#: zero-inflated -- sentence length, paragraph spread, lexical diversity -- are
#: deliberately absent: for those a mean and a percentile pair are honest, and
#: adding presence rates would be noise dressed as rigour.
ZERO_INFLATED_DIMENSIONS = (
    "first_person_rate",
    "second_person_rate",
    "parenthetical_rate",
    "question_rate",
    "sentence_initial_conjunction_rate",
    "fragment_rate",
    "contraction_rate",
    "list_rate",
    "heading_rate",
    "transition_rate",
    "exclamation_rate",
    "semicolon_rate",
    "em_dash_rate",
)

#: Documents that must actually contain a behaviour before its when-present
#: spread is reported. Below this a p10/p90 pair is two or three numbers
#: wearing the costume of a distribution.
MIN_PRESENT_FOR_PERCENTILES = 4

#: Agreement gap at or under which a plurality winner is really a tie. The
#: tie-break in `_label_agreement` is lexicographic, so below this margin the
#: winning label is decided by alphabetical order rather than by evidence.
TIE_EPSILON = 0.02

#: Feature names that are order statistics rather than means. Averaging them
#: across documents is a category error -- see `_aggregate_distributions`.
_ORDER_STATISTIC_SUFFIXES = ("_p10", "_p50", "_p90", "_median")

SUFFICIENCY_STRONG = "strong"
SUFFICIENCY_ADEQUATE = "adequate"
SUFFICIENCY_LIMITED = "limited"
SUFFICIENCY_INSUFFICIENT = "insufficient"


@dataclass
class DocumentEvidence:
    """Everything aggregation needs from one training document."""

    key: str
    features: DocumentFeatures
    context: str = "unknown"
    weight: float = 1.0
    model_traits: dict[str, str] = field(default_factory=dict)

    @property
    def words(self) -> int:
        return self.features.words


@dataclass
class AggregateResult:
    traits: dict[str, TraitValue] = field(default_factory=dict)
    distributions: VoiceDistributions | None = None
    rate_distributions: dict[str, RateDistribution] = field(default_factory=dict)
    contexts: dict[str, VoiceContext] = field(default_factory=dict)
    sufficiency: str = SUFFICIENCY_INSUFFICIENT
    sufficiency_warnings: list[str] = field(default_factory=list)
    skipped_contexts: dict[str, str] = field(default_factory=dict)


# --- deterministic trait derivation ------------------------------------
#
# Each entry maps a measured feature onto a labelled tendency. The bands are
# chosen so the middle band is the common case: a writer only gets called
# "high" on something when they are actually unusual on it.

def _band(value: float, thresholds: tuple[float, ...], labels: tuple[str, ...]) -> str:
    for threshold, label in zip(thresholds, labels):
        if value < threshold:
            return label
    return labels[-1]


_DETERMINISTIC_TRAITS: dict[str, tuple[str, tuple[float, ...], tuple[str, ...]]] = {
    # name: (feature, thresholds, labels)
    "sentence_length": (
        "sentence_length_mean", (12.0, 17.0, 22.0, 28.0),
        ("very_short", "short", "medium", "long", "very_long"),
    ),
    "sentence_variation": (
        "_variation_ratio", (0.30, 0.42, 0.55),
        ("low", "medium", "medium_high", "high"),
    ),
    "paragraph_length": (
        "paragraph_words_mean", (35.0, 65.0, 110.0),
        ("short", "medium", "long", "very_long"),
    ),
    "paragraph_variation": (
        "_paragraph_variation_ratio", (0.30, 0.50, 0.70),
        ("low", "medium", "medium_high", "high"),
    ),
    "contractions": (
        "contraction_rate", (0.10, 0.60, 1.50),
        ("rare", "occasional", "common", "frequent"),
    ),
    "first_person_presence": (
        "first_person_rate", (0.20, 1.00, 2.50),
        ("absent", "light", "moderate", "prominent"),
    ),
    "second_person_address": (
        "second_person_rate", (0.10, 0.80, 2.00),
        ("absent", "light", "moderate", "prominent"),
    ),
    "passive_construction": (
        "passive_rate", (0.15, 0.30, 0.50),
        ("low", "medium", "medium_high", "high"),
    ),
    "vocabulary_complexity": (
        "long_word_rate", (0.14, 0.20, 0.26),
        ("plain", "medium", "elevated", "dense"),
    ),
    "lexical_variety": (
        "lexical_diversity", (0.42, 0.50, 0.58),
        ("low", "medium", "medium_high", "high"),
    ),
    "transition_signposting": (
        "transition_rate", (0.08, 0.18, 0.32),
        ("minimal", "light", "signposted", "heavy"),
    ),
    "sentence_initial_conjunctions": (
        "sentence_initial_conjunction_rate", (0.02, 0.07, 0.15),
        ("rare", "occasional", "common", "frequent"),
    ),
    "rhetorical_questions": (
        "question_rate", (0.01, 0.05, 0.12),
        ("none", "rare", "occasional", "frequent"),
    ),
    "em_dash_use": (
        "em_dash_rate", (0.05, 0.30, 0.80),
        ("rare", "occasional", "common", "frequent"),
    ),
    "semicolon_use": (
        "semicolon_rate", (0.03, 0.20, 0.50),
        ("rare", "occasional", "common", "frequent"),
    ),
    "parenthetical_asides": (
        "parenthetical_rate", (0.15, 0.60, 1.40),
        ("rare", "occasional", "common", "frequent"),
    ),
    "structural_headings": (
        "heading_rate", (0.05, 0.20, 0.45),
        ("none", "light", "structured", "heavily_structured"),
    ),
    "natural_roughness": (
        "fragment_rate", (0.04, 0.10, 0.20),
        ("polished", "light", "moderate", "pronounced"),
    ),
    "readability": (
        "readability_grade", (9.0, 12.0, 15.0, 18.0),
        ("accessible", "general", "advanced", "specialist", "dense_specialist"),
    ),
}


def _derived(features: DocumentFeatures, name: str) -> float:
    """Resolve a feature name, including the two ratio-based pseudo-features.

    Variation is expressed as a coefficient of variation rather than a raw
    standard deviation so that "varies a lot" means the same thing for a
    writer of 12-word sentences and a writer of 30-word sentences.
    """
    if name == "_variation_ratio":
        mean = features.sentence_length_mean
        return (features.sentence_length_stdev / mean) if mean else 0.0
    if name == "_paragraph_variation_ratio":
        mean = features.paragraph_words_mean
        return (features.paragraph_words_stdev / mean) if mean else 0.0
    return float(getattr(features, name, 0.0) or 0.0)


def _weighted_mean(pairs: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _value, weight in pairs)
    if not total_weight:
        return 0.0
    return sum(value * weight for value, weight in pairs) / total_weight


def _evidence_score(documents: int, words: int) -> float:
    """How much evidence there is, on a 0-1 scale. A documented heuristic."""
    by_documents = min(1.0, documents / FULL_EVIDENCE_DOCUMENTS)
    by_words = min(1.0, words / FULL_EVIDENCE_WORDS)
    return 0.5 * by_documents + 0.5 * by_words


def _confidence(documents: int, words: int, agreement: float) -> float:
    """Combine evidence volume with cross-document agreement.

    Disagreement is the harsher term on purpose: a trait twelve documents
    disagree about should not read as well-supported merely because there
    were twelve of them.
    """
    evidence = _evidence_score(documents, words)
    return round(max(0.0, min(1.0, evidence * (0.35 + 0.65 * agreement))), 3)


def _label_agreement(
    labels: list[tuple[str, float]],
) -> tuple[str, float, str, float, bool]:
    """Weighted plurality label, its share, the runner-up with its share, and
    whether the two are tied.

    The winner alone is not enough to describe a corpus. A writer who uses the
    first person in half their documents and none of it in the other half
    produces a winning label of "absent" backed by less than half the weight,
    which is a real finding about variation, not a licence to state "absent"
    as though it were uniform. The runner-up is returned so callers can tell
    those two situations apart.

    The tie flag closes the remaining gap. The tie-break below is lexicographic
    so that rebuilding an unchanged corpus reproduces the same profile, but
    that stability is presentational, not evidential: when two labels carry the
    same weight, the winner is chosen by alphabetical order. Observed live, a
    professional slice split 0.417/0.417 between "short" and "very_short" and
    reported "short" as the author's sentence length. Returning the flag lets
    the application layer decline to name a winner it does not have.
    """
    if not labels:
        return "", 0.0, "", 0.0, False
    totals: dict[str, float] = {}
    for label, weight in labels:
        totals[label] = totals.get(label, 0.0) + weight
    total = sum(totals.values())
    if not total:
        return "", 0.0, "", 0.0, False
    # Equal weight resolves on the label, so a rebuild of the same corpus keeps
    # producing the same profile.
    ranked = sorted(totals.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    winner, winner_weight = ranked[0]
    runner, runner_weight = ranked[1] if len(ranked) > 1 else ("", 0.0)
    winner_share = winner_weight / total
    runner_share = runner_weight / total
    tied = bool(runner) and (winner_share - runner_share) <= TIE_EPSILON
    return winner, winner_share, runner, runner_share, tied


def _is_order_statistic(name: str) -> bool:
    return name.endswith(_ORDER_STATISTIC_SUFFIXES)


def _aggregate_distributions(documents: list[DocumentEvidence]) -> DocumentFeatures:
    """Combine every comparable feature across documents.

    Means, rates and standard deviations are word-weighted averages. Weighting
    by words as well as by inclusion weight stops a 200-word note from counting
    as much as a 4000-word paper, while the inclusion weight still lets a
    low-confidence document count for less.

    Percentiles and medians are NOT averaged. They are order statistics, and
    the weighted mean of a set of order statistics is not an order statistic of
    anything: it is pulled toward the centre by construction and toward the
    longest documents by the weighting. Treating them as just more names in
    `COMPARABLE_FEATURES` -- which is what happened before -- meant the corpus
    "10th percentile paragraph length" was the average of each document's own
    10th percentile, a number that systematically understates how short this
    author's short paragraphs actually get. Understating spread is precisely
    the failure the percentile fields were added to prevent.

    The honest cross-document summary of a per-document order statistic is its
    median across documents: "in a typical piece, paragraphs run from p10 to
    p90 words". That is also what the rendered guidance claims it is showing.
    """
    combined = DocumentFeatures()
    for name in COMPARABLE_FEATURES:
        values = [_derived(doc.features, name) for doc in documents]
        if _is_order_statistic(name):
            combined_value = statistics.median(values) if values else 0.0
        else:
            pairs = [
                (value, doc.weight * max(1, doc.words))
                for value, doc in zip(values, documents)
            ]
            combined_value = _weighted_mean(pairs)
        setattr(combined, name, round(combined_value, 4))
    combined.words = sum(doc.words for doc in documents)
    combined.sentences = sum(doc.features.sentences for doc in documents)
    combined.paragraphs = sum(doc.features.paragraphs for doc in documents)
    return combined


def _rate_distributions(
    documents: list[DocumentEvidence],
) -> dict[str, RateDistribution]:
    """Measure zero-inflated behaviours as presence plus when-present intensity.

    Two questions, kept apart because a single average answers neither: how
    often does this author reach for the behaviour at all, and how heavily do
    they use it when they do. Collapsing them produces guidance like "use first
    person 1.0 times per hundred words" for an author who writes 42% of their
    pieces without any first person and the rest with roughly 1.4.

    The percentiles are taken over present documents only. Including the zeros
    would drag p10 to zero for every behaviour in this map and reduce the
    spread to "somewhere between none and some", which is the flattening this
    function exists to undo.
    """
    distributions: dict[str, RateDistribution] = {}
    measured = len(documents)
    if not measured:
        return distributions

    for name in ZERO_INFLATED_DIMENSIONS:
        values = [_derived(doc.features, name) for doc in documents]
        present = sorted(value for value in values if value > 0)
        pairs = [
            (value, doc.weight * max(1, doc.words))
            for value, doc in zip(values, documents)
        ]
        # Enough present documents to describe a spread, or none reported. A
        # p10/p90 pair drawn from two documents is not a distribution.
        if len(present) >= MIN_PRESENT_FOR_PERCENTILES:
            p10 = round(_percentile(present, 0.10), 4)
            p50 = round(_percentile(present, 0.50), 4)
            p90 = round(_percentile(present, 0.90), 4)
        else:
            p10 = p50 = p90 = None
        distributions[name] = RateDistribution(
            document_presence_rate=round(len(present) / measured, 4),
            documents_measured=measured,
            documents_present=len(present),
            when_present_p10=p10,
            when_present_p50=p50,
            when_present_p90=p90,
            corpus_mean=round(_weighted_mean(pairs), 4),
        )
    return distributions


def _deterministic_traits(documents: list[DocumentEvidence]) -> dict[str, TraitValue]:
    """Label each measured tendency, with per-document agreement."""
    traits: dict[str, TraitValue] = {}
    words = sum(doc.words for doc in documents)

    for trait, (feature, thresholds, labels) in _DETERMINISTIC_TRAITS.items():
        per_document = [
            (_band(_derived(doc.features, feature), thresholds, labels), doc.weight)
            for doc in documents
        ]
        label, agreement, runner, runner_share, tied = _label_agreement(per_document)
        if not label:
            continue
        traits[trait] = TraitValue(
            value=label,
            confidence=_confidence(len(documents), words, agreement),
            supporting_documents=len(documents),
            supporting_words=words,
            agreement=round(agreement, 3),
            secondary=runner,
            secondary_agreement=round(runner_share, 3),
            tied=tied,
            source="deterministic",
        )
    return traits


def _model_traits(documents: list[DocumentEvidence]) -> dict[str, TraitValue]:
    """Majority-vote the abstract traits, keeping only what was returned."""
    traits: dict[str, TraitValue] = {}
    names: set[str] = set()
    for doc in documents:
        names |= set(doc.model_traits)

    for name in sorted(names):
        contributors = [doc for doc in documents if doc.model_traits.get(name)]
        if not contributors:
            continue
        label, agreement, runner, runner_share, tied = _label_agreement(
            [(doc.model_traits[name], doc.weight) for doc in contributors]
        )
        if not label:
            continue
        supporting_words = sum(doc.words for doc in contributors)
        traits[name] = TraitValue(
            value=label,
            confidence=_confidence(len(contributors), supporting_words, agreement),
            supporting_documents=len(contributors),
            supporting_words=supporting_words,
            agreement=round(agreement, 3),
            secondary=runner,
            secondary_agreement=round(runner_share, 3),
            tied=tied,
            source="model",
            note=(
                ""
                if len(contributors) == len(documents)
                else f"analyzed for {len(contributors)} of {len(documents)} documents"
            ),
        )
    return traits


def _to_distributions(features: DocumentFeatures) -> VoiceDistributions:
    from howlwriter.voice.corpus.features import to_distributions
    return to_distributions(features)


def assess_sufficiency(documents: list[DocumentEvidence]) -> tuple[str, list[str]]:
    """Judge whether the corpus can support a profile at all.

    Deliberately separate from per-trait confidence: a tiny corpus can still
    produce internally consistent traits, and this is what stops that
    consistency from being mistaken for evidence.
    """
    warnings: list[str] = []
    count = len(documents)
    words = sum(doc.words for doc in documents)

    if count == 0:
        return SUFFICIENCY_INSUFFICIENT, ["no documents were included in the profile"]

    if count < MIN_DOCUMENTS:
        warnings.append(
            f"only {count} training document(s); {MIN_DOCUMENTS} is the minimum for a "
            "profile that describes tendencies rather than one piece of writing"
        )
    if words < MIN_WORDS:
        warnings.append(
            f"only {words:,} training words; below {MIN_WORDS:,} the distributions are "
            "dominated by individual documents"
        )

    if words:
        largest = max(documents, key=lambda d: d.words)
        share = largest.words / words
        if share > DOMINANCE_THRESHOLD and count > 1:
            warnings.append(
                f"one document supplies {share:.0%} of the training words; the profile "
                "largely describes that document"
            )

    if count >= 2:
        means = [doc.features.sentence_length_mean for doc in documents if doc.words]
        if means and statistics.mean(means):
            spread = statistics.pstdev(means) / statistics.mean(means)
            if spread > 0.55:
                warnings.append(
                    f"cadence varies widely between documents (coefficient of variation "
                    f"{spread:.2f}); the corpus may mix several kinds of writing"
                )

    if count < MIN_DOCUMENTS or words < MIN_WORDS:
        level = SUFFICIENCY_INSUFFICIENT if count < 3 or words < 1200 else SUFFICIENCY_LIMITED
    elif count >= FULL_EVIDENCE_DOCUMENTS and words >= FULL_EVIDENCE_WORDS and not warnings:
        level = SUFFICIENCY_STRONG
    elif warnings:
        level = SUFFICIENCY_LIMITED
    else:
        level = SUFFICIENCY_ADEQUATE
    return level, warnings


def aggregate(documents: list[DocumentEvidence]) -> AggregateResult:
    """Build global traits, distributions, and context blocks from training data.

    Only documents passed in here influence the profile. The holdout is
    filtered out by the caller before this point and must never appear in
    this list.
    """
    result = AggregateResult()
    usable = [doc for doc in documents if doc.weight > 0 and doc.words > 0]
    if not usable:
        result.sufficiency_warnings = ["no usable training documents"]
        return result

    combined = _aggregate_distributions(usable)
    result.distributions = _to_distributions(combined)
    result.rate_distributions = _rate_distributions(usable)
    result.traits = _deterministic_traits(usable)
    result.traits.update(_model_traits(usable))
    result.sufficiency, result.sufficiency_warnings = assess_sufficiency(usable)

    # --- context blocks ---
    by_context: dict[str, list[DocumentEvidence]] = {}
    for doc in usable:
        if doc.context in ("unknown", "mixed", ""):
            continue          # counted globally, never as its own context
        by_context.setdefault(doc.context, []).append(doc)

    for context, members in sorted(by_context.items()):
        words = sum(doc.words for doc in members)
        if len(members) < MIN_CONTEXT_DOCUMENTS or words < MIN_CONTEXT_WORDS:
            result.skipped_contexts[context] = (
                f"insufficient evidence: {len(members)} document(s), {words:,} words "
                f"(needs {MIN_CONTEXT_DOCUMENTS} documents and {MIN_CONTEXT_WORDS:,} words)"
            )
            continue

        context_features = _aggregate_distributions(members)
        traits = _deterministic_traits(members)
        traits.update(_model_traits(members))

        # A context block records only what it says DIFFERENTLY from the
        # global profile. Repeating an identical trait would make the context
        # look like independent evidence when it is the same observation.
        distinct = {
            name: value for name, value in traits.items()
            if name not in result.traits or result.traits[name].value != value.value
        }
        sufficiency, _ = assess_sufficiency(members)
        result.contexts[context] = VoiceContext(
            name=context,
            traits=distinct,
            # A context slice is smaller than the corpus by construction, so
            # its when-present percentiles are suppressed by the same floor
            # that guards the global map rather than by a separate rule.
            rate_distributions=_rate_distributions(members),
            distributions={
                "sentence_length_mean": context_features.sentence_length_mean,
                "sentence_length_median": context_features.sentence_length_median,
                "sentence_length_stdev": context_features.sentence_length_stdev,
                "sentence_length_p10": context_features.sentence_length_p10,
                "sentence_length_p90": context_features.sentence_length_p90,
                "paragraph_sentences_mean": context_features.paragraph_sentences_mean,
                "paragraph_sentences_stdev": context_features.paragraph_sentences_stdev,
                "paragraph_sentences_p10": context_features.paragraph_sentences_p10,
                "paragraph_sentences_p50": context_features.paragraph_sentences_p50,
                "paragraph_sentences_p90": context_features.paragraph_sentences_p90,
                "paragraph_words_mean": context_features.paragraph_words_mean,
                "paragraph_words_stdev": context_features.paragraph_words_stdev,
                "paragraph_words_p10": context_features.paragraph_words_p10,
                "paragraph_words_p50": context_features.paragraph_words_p50,
                "paragraph_words_p90": context_features.paragraph_words_p90,
                "single_sentence_paragraph_rate": context_features.single_sentence_paragraph_rate,
                "short_sentence_rate": context_features.short_sentence_rate,
                "long_sentence_rate": context_features.long_sentence_rate,
                "contraction_rate": context_features.contraction_rate,
                "first_person_rate": context_features.first_person_rate,
                "second_person_rate": context_features.second_person_rate,
                "transition_rate": context_features.transition_rate,
                "sentence_initial_conjunction_rate": context_features.sentence_initial_conjunction_rate,
                "fragment_rate": context_features.fragment_rate,
                "parenthetical_rate": context_features.parenthetical_rate,
                "question_rate": context_features.question_rate,
                "long_word_rate": context_features.long_word_rate,
                "readability_grade": context_features.readability_grade,
            },
            document_count=len(members),
            word_count=words,
            confidence=round(_evidence_score(len(members), words), 3),
            sufficiency=sufficiency,
        )

    return result


def build_corpus_summary(
    *,
    train: list[DocumentEvidence],
    holdout: list[DocumentEvidence],
    aggregated: AggregateResult,
) -> CorpusSummary:
    """Counts describing the corpus. No filenames, no paths, no excerpts."""
    summary = CorpusSummary(
        included_documents=len(train),
        holdout_documents=len(holdout),
        training_words=sum(doc.words for doc in train),
        holdout_words=sum(doc.words for doc in holdout),
        sufficiency=aggregated.sufficiency,
        sufficiency_warnings=list(aggregated.sufficiency_warnings),
    )
    for doc in train + holdout:
        summary.words_by_context[doc.context] = (
            summary.words_by_context.get(doc.context, 0) + doc.words
        )
        summary.documents_by_context[doc.context] = (
            summary.documents_by_context.get(doc.context, 0) + 1
        )
    return summary
