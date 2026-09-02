"""Cross-document rate distributions: presence and intensity, kept apart.

The failure these guard against is a corpus mean that describes no document in
the corpus. An author who writes 42% of their pieces with no first person at
all and the rest with roughly 1.4 uses per hundred words has a mean of 1.0, and
1.0 is what every generated piece then reaches for -- neither impersonal like
the 42% nor personal like the rest. Every test here fails if presence and
intensity are ever collapsed back into one number.
"""

from __future__ import annotations

import itertools
import statistics

import pytest

from howlwriter.domain.voice import (
    MIN_CORPUS_BUILT_VERSION,
    RateDistribution,
    VOICE_PROFILE_VERSION,
    VoiceProfile,
)
from howlwriter.voice.corpus.aggregate import (
    MIN_PRESENT_FOR_PERCENTILES,
    TIE_EPSILON,
    ZERO_INFLATED_DIMENSIONS,
    DocumentEvidence,
    _label_agreement,
    _rate_distributions,
    aggregate,
)
from howlwriter.voice.corpus.features import DocumentFeatures


_COUNTER = itertools.count()


def _doc(context: str = "general", words: int = 500, **features: float) -> DocumentEvidence:
    """One piece of evidence carrying only the features a test cares about.

    `words` reaches aggregation through the feature vector, since
    DocumentEvidence derives it rather than storing it.
    """
    vector = DocumentFeatures(words=words, sentences=max(1, words // 20), paragraphs=5)
    for name, value in features.items():
        setattr(vector, name, value)
    return DocumentEvidence(
        key=f"doc-{next(_COUNTER)}",
        features=vector,
        context=context,
        weight=1.0,
    )


# --- presence is measured separately from intensity ---------------------

def test_a_behaviour_absent_from_half_the_corpus_reports_that_absence():
    documents = [_doc(first_person_rate=0.0) for _ in range(10)]
    documents += [_doc(first_person_rate=rate) for rate in (1.0, 1.2, 1.4, 1.6, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0)]

    rates = _rate_distributions(documents)
    first_person = rates["first_person_rate"]

    assert first_person.documents_measured == 20
    assert first_person.documents_present == 10
    assert first_person.document_presence_rate == pytest.approx(0.5)


def test_when_present_percentiles_exclude_the_absent_documents():
    """Including the zeros would drag every percentile toward zero.

    That is the flattening this whole structure exists to undo, so it is worth
    a test that computes the honest answer independently.
    """
    present_rates = [1.0, 1.2, 1.4, 1.6, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]
    documents = [_doc(first_person_rate=0.0) for _ in range(10)]
    documents += [_doc(first_person_rate=rate) for rate in present_rates]

    first_person = _rate_distributions(documents)["first_person_rate"]

    assert first_person.when_present_p50 == pytest.approx(statistics.median(present_rates))
    # The median across ALL documents, zeros included, would be 0.5 -- far below
    # anything a document that uses first person actually does.
    assert first_person.when_present_p50 > 1.0
    assert first_person.when_present_p10 >= min(present_rates)


def test_the_corpus_mean_can_describe_no_document_and_is_still_recorded():
    """Kept for continuity and diagnostics, never rendered on its own."""
    documents = [_doc(contraction_rate=0.0) for _ in range(6)]
    documents += [_doc(contraction_rate=1.0) for _ in range(4)]

    contractions = _rate_distributions(documents)["contraction_rate"]

    assert contractions.corpus_mean == pytest.approx(0.4)
    # No document sits anywhere near the mean: six are at 0.0 and four at 1.0.
    assert contractions.document_presence_rate == pytest.approx(0.4)
    assert contractions.when_present_p50 == pytest.approx(1.0)


def test_too_few_present_documents_report_no_spread_rather_than_a_fake_one():
    documents = [_doc(em_dash_rate=0.0) for _ in range(20)]
    documents += [_doc(em_dash_rate=rate) for rate in (0.5, 0.9)]

    em_dash = _rate_distributions(documents)["em_dash_rate"]

    assert em_dash.documents_present == 2 < MIN_PRESENT_FOR_PERCENTILES
    assert em_dash.when_present_p10 is None
    assert em_dash.when_present_p50 is None
    assert em_dash.when_present_p90 is None
    # Presence is still known and still reported -- only the spread is withheld.
    assert em_dash.document_presence_rate == pytest.approx(2 / 22, abs=1e-4)
    assert em_dash.has_spread is False


def test_a_universal_behaviour_is_marked_universal():
    documents = [_doc(transition_rate=rate) for rate in (0.05, 0.1, 0.15, 0.2, 0.25)]
    transitions = _rate_distributions(documents)["transition_rate"]
    assert transitions.document_presence_rate == pytest.approx(1.0)
    assert transitions.is_universal is True


def test_only_zero_inflated_dimensions_get_this_treatment():
    """Applying it to every measure would be noise dressed as rigour."""
    documents = [_doc(first_person_rate=1.0, sentence_length_mean=18.0) for _ in range(6)]
    rates = _rate_distributions(documents)

    assert set(rates) == set(ZERO_INFLATED_DIMENSIONS)
    assert "sentence_length_mean" not in rates
    assert "paragraph_words_p10" not in rates
    assert "lexical_diversity" not in rates


def test_an_empty_corpus_produces_no_distributions_rather_than_zeros():
    assert _rate_distributions([]) == {}


# --- ties are not winners ------------------------------------------------

def test_an_exact_split_is_reported_as_tied():
    """A dead heat resolved alphabetically is not a finding about the author."""
    label, agreement, runner, runner_share, tied = _label_agreement(
        [("short", 1.0)] * 5 + [("very_short", 1.0)] * 5
    )
    assert tied is True
    assert agreement == pytest.approx(runner_share)
    # A winner is still returned so rebuilds stay deterministic; the flag is
    # what stops it being presented as the author's tendency.
    assert label in ("short", "very_short")
    assert runner in ("short", "very_short")
    assert label != runner


def test_a_clear_majority_is_not_tied():
    _, _, _, _, tied = _label_agreement([("absent", 1.0)] * 18 + [("prominent", 1.0)] * 2)
    assert tied is False


def test_the_tie_margin_is_narrow_enough_to_leave_real_leads_alone():
    """A lead wider than the epsilon must survive as a lead."""
    total = 100
    lead = int(total * (TIE_EPSILON + 0.05) / 2)
    labels = [("a", 1.0)] * (total // 2 + lead) + [("b", 1.0)] * (total // 2 - lead)
    _, _, _, _, tied = _label_agreement(labels)
    assert tied is False


def test_a_tied_trait_survives_aggregation_into_the_profile():
    documents = [_doc(context="general", contraction_rate=0.0) for _ in range(5)]
    documents += [_doc(context="general", contraction_rate=4.0) for _ in range(5)]

    result = aggregate(documents)
    contractions = result.traits["contractions"]

    assert contractions.tied is True
    assert contractions.secondary
    assert contractions.secondary != contractions.value


# --- percentiles are order statistics, not averages ----------------------

def test_corpus_percentiles_are_not_the_weighted_mean_of_document_percentiles():
    """A mean of order statistics is not an order statistic.

    The regression this locks down: the aggregate applied one word-weighted
    mean to every comparable feature, percentile fields included, so a long
    document's own p10 dominated the corpus p10 and the reported spread came
    out narrower than the corpus actually is.
    """
    documents = [
        _doc(words=4000, paragraph_words_p10=90.0, paragraph_words_p90=140.0),
        _doc(words=200, paragraph_words_p10=10.0, paragraph_words_p90=30.0),
        _doc(words=200, paragraph_words_p10=12.0, paragraph_words_p90=34.0),
    ]

    result = aggregate(documents)
    p10 = result.distributions.paragraph_words_p10

    # Word-weighted mean would land at ~85, dragged there by the 4000-word
    # document. The median of the three per-document p10s is 12.
    assert p10 == pytest.approx(12.0)
    assert p10 < 50.0


def test_means_are_still_word_weighted():
    """Only order statistics changed; a mean is still a mean."""
    documents = [
        _doc(words=3000, sentence_length_mean=30.0),
        _doc(words=1000, sentence_length_mean=10.0),
    ]
    result = aggregate(documents)
    assert result.distributions.sentence_length_mean == pytest.approx(25.0)


# --- schema and compatibility -------------------------------------------

def test_a_v1_profile_loads_without_rate_distributions_and_stays_corpus_built():
    """The live profile on disk predates this field and must keep working."""
    profile = VoiceProfile.from_dict(
        {"author_name": "", "version": 1, "generated_from": "corpus_build"}
    )
    assert MIN_CORPUS_BUILT_VERSION <= 1 < VOICE_PROFILE_VERSION
    assert profile.is_corpus_built is True
    assert profile.rate_distributions == {}


def test_rate_distributions_round_trip_through_serialization():
    original = RateDistribution(
        document_presence_rate=0.58,
        documents_measured=65,
        documents_present=38,
        when_present_p10=0.8,
        when_present_p50=1.36,
        when_present_p90=3.1,
        corpus_mean=1.01,
    )
    profile = VoiceProfile(
        author_name="",
        version=VOICE_PROFILE_VERSION,
        generated_from="corpus_build",
        rate_distributions={"first_person_rate": original},
    )
    restored = VoiceProfile.from_dict(profile.to_dict())
    rebuilt = restored.rate_distributions["first_person_rate"]

    assert isinstance(rebuilt, RateDistribution)
    assert rebuilt == original


def test_the_profile_holds_no_prose_in_the_new_field():
    """The no-raw-text guarantee covers every field, including this one."""
    documents = [_doc(first_person_rate=float(i)) for i in range(8)]
    for name, dist in _rate_distributions(documents).items():
        for value in dist.to_dict().values():
            assert isinstance(value, (int, float, type(None))), name
