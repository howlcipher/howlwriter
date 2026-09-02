"""Train/holdout split, aggregation confidence, sufficiency, and validation."""

from __future__ import annotations

from howlwriter.voice.corpus.aggregate import (
    SUFFICIENCY_INSUFFICIENT,
    SUFFICIENCY_LIMITED,
    DocumentEvidence,
    aggregate,
    assess_sufficiency,
)
from howlwriter.voice.corpus.diversity import FAIL, NOT_EVALUATED, PASS, WARNING, compare
from howlwriter.voice.corpus.features import extract_features
from howlwriter.voice.corpus.split import (
    MIN_CORPUS_TO_SPLIT,
    TRAIN,
    assign_split,
    split_score,
)
from howlwriter.voice.corpus.validation import STRONG, validate
from tests.voice.corpus.conftest import synthetic_prose


def _documents(count: int, context: str = "academic", start: int = 0):
    return [
        (f"key{index}", f"fingerprint-{index}", context)
        for index in range(start, start + count)
    ]


def _evidence(count: int, context: str = "academic", *, seed: int = 0, paragraphs: int = 6):
    return [
        DocumentEvidence(
            key=f"doc{index}",
            features=extract_features(synthetic_prose(seed + index, paragraphs)),
            context=context,
            weight=1.0,
        )
        for index in range(count)
    ]


# --- split -------------------------------------------------------------

def test_split_holds_back_roughly_a_fifth():
    result = assign_split(_documents(60))
    assert result.performed
    assert 6 <= len(result.holdout_keys) <= 20
    assert len(result.train_keys) + len(result.holdout_keys) == 60


def test_split_is_stable_when_documents_are_added():
    """The property that makes rebuilds comparable."""
    first = assign_split(_documents(40))
    second = assign_split(_documents(40) + _documents(10, start=40))
    moved = [k for k in first.assignments if first.side_of(k) != second.side_of(k)]
    assert moved == []


def test_split_is_stable_when_documents_are_removed():
    full = assign_split(_documents(40))
    reduced = assign_split(_documents(30))
    moved = [k for k in reduced.assignments if full.side_of(k) != reduced.side_of(k)]
    assert moved == []


def test_split_depends_only_on_the_fingerprint():
    assert split_score("abc") == split_score("abc")
    assert split_score("abc") != split_score("abd")
    assert 0.0 <= split_score("anything") < 1.0


def test_split_is_stratified_across_contexts():
    documents = _documents(30, "academic") + _documents(30, "professional", start=30)
    result = assign_split(documents)
    holdout_contexts = {
        result.assignments[key].context for key in result.holdout_keys
    }
    assert holdout_contexts == {"academic", "professional"}


def test_a_tiny_corpus_is_not_split_and_says_so():
    result = assign_split(_documents(MIN_CORPUS_TO_SPLIT - 1))
    assert not result.performed
    assert result.holdout_keys == []
    assert "usable documents" in result.reason
    assert "no holdout validation was performed" in result.reason
    assert all(side == TRAIN for side in (result.side_of(k) for k in result.assignments))


def test_a_small_context_contributes_everything_to_training():
    documents = _documents(20, "academic") + _documents(2, "social", start=20)
    result = assign_split(documents)
    assert "social" in result.unsplit_contexts
    social = [k for k, a in result.assignments.items() if a.context == "social"]
    assert all(result.side_of(key) == TRAIN for key in social)


def test_every_assignment_carries_a_reason():
    result = assign_split(_documents(30))
    assert all(assignment.reason for assignment in result.assignments.values())


def test_empty_input_is_handled():
    result = assign_split([])
    assert not result.performed
    assert result.reason


# --- aggregation -------------------------------------------------------

def test_aggregation_produces_traits_with_evidence():
    result = aggregate(_evidence(12))
    assert result.traits
    for trait in result.traits.values():
        assert trait.value
        assert trait.supporting_documents == 12
        assert trait.supporting_words > 0
        assert 0.0 <= trait.confidence <= 1.0
        assert 0.0 <= trait.agreement <= 1.0


def test_more_evidence_raises_confidence():
    small = aggregate(_evidence(3, paragraphs=2))
    large = aggregate(_evidence(20, paragraphs=8))
    assert (
        large.traits["sentence_length"].confidence
        > small.traits["sentence_length"].confidence
    )


def test_disagreement_lowers_confidence():
    """Two corpora of equal size: the consistent one must score higher."""
    consistent = [
        DocumentEvidence(
            key=f"c{i}",
            features=extract_features("Six words in this short sentence. " * 30),
            context="general",
        )
        for i in range(10)
    ]
    conflicting = []
    for i in range(10):
        text = (
            "Six words in this short sentence. " * 30
            if i % 2 == 0 else
            ("A considerably longer sentence that continues well past the point "
             "where a shorter one would have stopped and keeps adding clauses. ") * 12
        )
        conflicting.append(
            DocumentEvidence(key=f"x{i}", features=extract_features(text), context="general")
        )

    consistent_result = aggregate(consistent)
    conflicting_result = aggregate(conflicting)
    assert (
        consistent_result.traits["sentence_length"].agreement
        > conflicting_result.traits["sentence_length"].agreement
    )
    assert (
        consistent_result.traits["sentence_length"].confidence
        > conflicting_result.traits["sentence_length"].confidence
    )


def test_context_blocks_need_their_own_evidence():
    evidence = _evidence(12, "academic") + _evidence(1, "social", seed=99)
    result = aggregate(evidence)
    assert "academic" in result.contexts
    assert "social" not in result.contexts
    assert "insufficient evidence" in result.skipped_contexts["social"]


def test_unknown_and_mixed_documents_never_become_contexts():
    evidence = _evidence(6, "unknown") + _evidence(6, "mixed", seed=50)
    result = aggregate(evidence)
    assert result.contexts == {}
    assert result.traits  # they still count globally


def test_a_context_block_only_records_what_differs_from_global():
    evidence = _evidence(14, "academic")
    result = aggregate(evidence)
    academic = result.contexts.get("academic")
    if academic is not None:
        for name, trait in academic.traits.items():
            assert result.traits[name].value != trait.value


# --- sufficiency -------------------------------------------------------

def test_a_tiny_corpus_is_reported_insufficient():
    level, warnings = assess_sufficiency(_evidence(2, paragraphs=1))
    assert level == SUFFICIENCY_INSUFFICIENT
    assert warnings


def test_single_document_dominance_is_flagged():
    evidence = _evidence(5, paragraphs=1, seed=1)
    evidence.append(
        DocumentEvidence(
            key="huge",
            features=extract_features(synthetic_prose(77, paragraphs=90)),
            context="academic",
        )
    )
    level, warnings = assess_sufficiency(evidence)
    assert any("supplies" in w and "% of the training words" in w for w in warnings)
    assert level in (SUFFICIENCY_LIMITED, SUFFICIENCY_INSUFFICIENT)


def test_no_documents_is_reported_not_crashed():
    level, warnings = assess_sufficiency([])
    assert level == SUFFICIENCY_INSUFFICIENT
    assert warnings


def test_aggregate_with_no_usable_documents_returns_empty():
    result = aggregate([])
    assert result.traits == {}
    assert result.sufficiency_warnings


# --- validation --------------------------------------------------------

def test_holdout_documents_do_not_influence_the_profile():
    """The invariant the whole split exists to protect."""
    train = _evidence(10, seed=0)
    holdout = [
        DocumentEvidence(
            key="wild",
            features=extract_features(
                "Tiny. Short. Clipped. Abrupt. Terse. Blunt. Curt. Brief. Spare. Bare."
            ),
            context="academic",
        )
    ]
    only_train = aggregate(train)
    with_holdout_present_but_not_passed = aggregate(train)
    assert only_train.traits.keys() == with_holdout_present_but_not_passed.traits.keys()
    for name in only_train.traits:
        assert only_train.traits[name].value == with_holdout_present_but_not_passed.traits[name].value
    # And aggregating WITH the holdout would have changed the answer, which is
    # what makes the exclusion meaningful rather than incidental.
    contaminated = aggregate(train + holdout)
    assert contaminated.traits["sentence_length"].agreement != \
        only_train.traits["sentence_length"].agreement


def test_validation_reports_bands_per_dimension():
    train = _evidence(10, seed=0)
    holdout = _evidence(3, seed=0)     # same generator: should align well
    result = validate(train=train, holdout=holdout, corpus_sufficiency="adequate")
    assert result.performed
    assert result.alignment()
    assert set(result.alignment().values()) <= {"STRONG", "MODERATE", "WEAK"}
    assert result.alignment()["sentence_cadence"] == STRONG


def test_validation_never_produces_an_authorship_probability():
    train = _evidence(10, seed=0)
    holdout = _evidence(3, seed=40)
    result = validate(train=train, holdout=holdout, corpus_sufficiency="adequate")
    assert result.overall_confidence in ("LOW", "MEDIUM_LOW", "MEDIUM", "HIGH")
    for band in result.alignment().values():
        assert band in ("STRONG", "MODERATE", "WEAK", "NOT_EVALUATED")


def test_dissimilar_holdout_scores_worse_than_a_similar_one():
    train = [
        DocumentEvidence(
            key=f"t{i}",
            features=extract_features("Six words in this short sentence. " * 30),
            context="general",
        )
        for i in range(10)
    ]
    similar = [DocumentEvidence(
        key="s", features=extract_features("Six words in this short sentence. " * 30),
        context="general",
    )]
    different = [DocumentEvidence(
        key="d",
        features=extract_features(
            ("An extraordinarily elaborate sentence which continues at considerable "
             "length through numerous subordinate clauses without pausing. ") * 20
        ),
        context="general",
    )]
    good = validate(train=train, holdout=similar, corpus_sufficiency="adequate")
    bad = validate(train=train, holdout=different, corpus_sufficiency="adequate")
    strong = sum(1 for b in good.alignment().values() if b == STRONG)
    weak_strong = sum(1 for b in bad.alignment().values() if b == STRONG)
    assert strong > weak_strong


def test_no_holdout_is_reported_as_not_validated():
    result = validate(train=_evidence(5), holdout=[], corpus_sufficiency="limited")
    assert not result.performed
    assert result.alignment() == {}
    assert any("not validated" in w or "too small" in w for w in result.warnings)


def test_corpus_sufficiency_caps_the_reported_confidence():
    train = _evidence(10, seed=0)
    holdout = _evidence(3, seed=0)
    strong_corpus = validate(train=train, holdout=holdout, corpus_sufficiency="strong")
    thin_corpus = validate(train=train, holdout=holdout, corpus_sufficiency="insufficient")
    order = ["LOW", "MEDIUM_LOW", "MEDIUM", "HIGH"]
    assert order.index(thin_corpus.overall_confidence) <= \
        order.index(strong_corpus.overall_confidence)
    assert thin_corpus.overall_confidence == "LOW"


def test_context_distributions_carry_the_structural_percentiles():
    """The aggregate must forward the spread, not only the means.

    A context whose percentiles arrive as zeros renders downstream as
    "typically 0-0 words", so this is where the values have to be real.
    """
    result = aggregate(_evidence(12, context="professional"))

    context = result.contexts.get("professional")
    assert context is not None
    assert context.distributions["paragraph_words_p90"] > 0
    assert (
        context.distributions["paragraph_words_p90"]
        > context.distributions["paragraph_words_p10"]
    )
    assert context.distributions["paragraph_sentences_p50"] > 0
    assert context.distributions["single_sentence_paragraph_rate"] >= 0


def test_a_split_corpus_records_the_runner_up_label():
    """Agreement alone cannot say what the other half of the corpus did."""
    from howlwriter.voice.corpus.aggregate import _label_agreement

    label, agreement, runner, runner_share = _label_agreement(
        [("absent", 1.0)] * 13 + [("prominent", 1.0)] * 12
    )
    assert label == "absent"
    assert runner == "prominent"
    assert agreement < 0.60
    assert runner_share > 0.40


# --- diversity ---------------------------------------------------------

def test_diversity_accepts_output_that_varies_like_the_corpus():
    corpus = [extract_features(synthetic_prose(i, paragraphs=6)) for i in range(10)]
    generated = [synthetic_prose(100 + i, paragraphs=6) for i in range(10)]
    result = compare(corpus, generated)
    assert result.verdict == PASS


def test_diversity_detects_excessive_convergence():
    """Ten outputs that are near-identical must not pass."""
    corpus = [extract_features(synthetic_prose(i, paragraphs=6)) for i in range(10)]
    template = (
        "The truth is that this matters. Every team learns it the hard way. "
        "The truth is that nobody listens. Every team pays for it eventually.\n\n"
        "The truth is that the fix is boring. Every team wants a better story."
    )
    generated = [template for _ in range(10)]
    result = compare(corpus, generated)
    assert result.verdict in (WARNING, FAIL)
    assert result.notes


def test_diversity_flags_a_shared_opening_across_outputs():
    corpus = [extract_features(synthetic_prose(i, paragraphs=6)) for i in range(10)]
    generated = [
        f"The truth is that item {i} matters here. " + synthetic_prose(200 + i, paragraphs=4)
        for i in range(10)
    ]
    result = compare(corpus, generated)
    assert result.repeated_openings
    assert any("share the same two-word opening" in note for note in result.notes)


def test_a_thin_context_slice_cannot_replace_the_corpus_baseline():
    """Two documents cannot supply a coefficient of variation.

    A slice that small produces a corpus CV large enough to clear real
    convergence, so substituting it does not weaken the check, it inverts it.
    """
    corpus = [extract_features(synthetic_prose(i, paragraphs=6)) for i in range(12)]
    thin_slice = [extract_features(synthetic_prose(500 + i, paragraphs=6)) for i in range(2)]
    generated = [synthetic_prose(100 + i, paragraphs=6) for i in range(10)]

    result = compare(corpus, generated, context_corpus_features=thin_slice)

    assert any("below the" in note and "context slice" in note for note in result.notes)


def test_a_sufficient_context_slice_is_used_as_the_baseline():
    corpus = [extract_features(synthetic_prose(i, paragraphs=6)) for i in range(12)]
    fat_slice = [extract_features(synthetic_prose(500 + i, paragraphs=6)) for i in range(10)]
    generated = [synthetic_prose(100 + i, paragraphs=6) for i in range(10)]

    result = compare(corpus, generated, context_corpus_features=fat_slice)

    assert not any("context slice held only" in note for note in result.notes)


def test_a_large_length_gap_withholds_a_pass_rather_than_granting_one():
    """Short outputs against long corpus documents cannot earn a PASS.

    The structural dimensions are dominated by length at that ratio, so a clean
    sheet means the comparison was never in a position to detect anything.
    """
    corpus = [extract_features(synthetic_prose(i, paragraphs=40)) for i in range(10)]
    generated = [synthetic_prose(100 + i, paragraphs=2) for i in range(10)]

    result = compare(corpus, generated)

    assert result.verdict != PASS
    assert any("much shorter than the corpus" in note for note in result.notes)


def test_diversity_needs_enough_samples_to_say_anything():
    corpus = [extract_features(synthetic_prose(i)) for i in range(10)]
    result = compare(corpus, ["one", "two"])
    assert result.verdict == NOT_EVALUATED
    assert result.notes


def test_an_empty_corpus_vector_cannot_distort_the_baseline():
    """A zero vector is not a document with short sentences.

    During dogfood a single excluded document's zero-filled feature vector
    inflated the corpus coefficient of variation elevenfold and produced a
    false convergence failure.
    """
    from howlwriter.voice.corpus.features import DocumentFeatures

    corpus = [extract_features(synthetic_prose(i, paragraphs=6)) for i in range(10)]
    generated = [synthetic_prose(100 + i, paragraphs=6) for i in range(10)]

    clean = compare(corpus, generated)
    polluted = compare(corpus + [DocumentFeatures()], generated)

    assert clean.verdict == PASS
    assert polluted.verdict == clean.verdict
    assert any("no measurable text" in note for note in polluted.notes)
    for a, b in zip(clean.dimensions, polluted.dimensions):
        assert a.corpus_variation == b.corpus_variation


def test_much_shorter_outputs_than_the_corpus_are_flagged_as_such():
    corpus = [extract_features(synthetic_prose(i, paragraphs=10)) for i in range(10)]
    snippets = [synthetic_prose(200 + i, paragraphs=1)[:120] for i in range(8)]
    result = compare(corpus, snippets)
    assert any("much shorter than the corpus" in note for note in result.notes)


def test_generated_outputs_with_no_measurable_text_are_not_evaluated():
    corpus = [extract_features(synthetic_prose(i)) for i in range(10)]
    result = compare(corpus, ["", "   ", "\n\n", "  \t "])
    assert result.verdict == NOT_EVALUATED
    assert result.notes
