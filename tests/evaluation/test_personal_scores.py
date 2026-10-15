"""Naturalness, Voice Match, drift, and revision comparison.

Synthetic corpora only (see tests/voice/identity/conftest.py). The tests pin
behaviour that the scores' definitions promise: percentiles against a
reference, withholding when unsupported, independence, contamination
refusal, and integrity checks that outrank any score.
"""

from __future__ import annotations

import pytest

from howlwriter.evaluation import drift
from howlwriter.evaluation import naturalness as nat
from howlwriter.evaluation import voice_match as vm
from howlwriter.evaluation.empirical import midrank_percentile, robust_centre, separation
from howlwriter.evaluation.perturb import PERTURBATIONS, formulaic_injection, uniform_paragraphs

from tests.voice.identity.conftest import author_a, author_b


def _measure(texts):
    return [nat.measure_naturalness(t) for t in texts]


@pytest.fixture(scope="module")
def reference_texts():
    return [author_a(seed, byline=False) for seed in range(30)]


@pytest.fixture(scope="module")
def calibration(reference_texts):
    controls = {
        name: _measure([fn(t) for t in reference_texts[:10]]) for name, fn in PERTURBATIONS.items()
    }
    return nat.build_calibration(
        _measure(reference_texts), context="academic", source="synthetic", controls=controls
    )


# --- empirical helpers ---


def test_midrank_counts_ties_half():
    assert midrank_percentile(1.0, [1.0, 1.0]) == 0.5
    assert midrank_percentile(5.0, [1.0, 2.0]) == 1.0
    assert midrank_percentile(0.0, []) == 0.5


def test_robust_scale_is_floored():
    assert robust_centre([0.0, 0.0, 0.0], floor=0.1).scale == 0.1


def test_separation_auc_and_untested_case():
    assert separation([3, 4, 5], [0, 1, 2]).auc == 1.0
    assert separation([1, 2], []).auc is None


# --- naturalness ---


def test_short_documents_are_unavailable_with_reason(calibration):
    report = nat.score_naturalness(
        nat.measure_naturalness("Too short to judge."), calibration, context="academic"
    )
    assert report.status == nat.STATUS_UNAVAILABLE and report.score is None
    assert "at least" in report.reason


def test_no_calibration_means_no_number(reference_texts):
    report = nat.score_naturalness(
        nat.measure_naturalness(reference_texts[0]), None, context="academic"
    )
    assert report.status == nat.STATUS_UNAVAILABLE and report.dimensions


def test_thin_reference_set_withholds(reference_texts):
    thin = nat.build_calibration(_measure(reference_texts[:5]), context="academic", source="thin")
    report = nat.score_naturalness(
        nat.measure_naturalness(reference_texts[6]), thin, context="academic"
    )
    assert report.status == nat.STATUS_UNAVAILABLE and report.evidence == "insufficient_reference"


def test_reference_documents_score_as_a_percentile(calibration):
    median = calibration.validation["reference_scores"]["median"]
    assert 30 <= median <= 70


def test_mechanical_perturbation_lowers_naturalness(calibration):
    fresh = author_a(777, byline=False)
    original = nat.score_naturalness(
        nat.measure_naturalness(fresh), calibration, context="academic"
    )
    damaged = nat.score_naturalness(
        nat.measure_naturalness(formulaic_injection(fresh)), calibration, context="academic"
    )
    assert original.status == damaged.status == nat.STATUS_SCORED
    assert damaged.score < original.score
    assert any("Mechanical transitions" in w or "Formulaic" in w for w in damaged.weaknesses)
    assert damaged.locations and damaged.suggestions


def test_calibration_reports_control_separation(calibration):
    pooled = calibration.validation["pooled_separation"]
    assert pooled["auc"] is not None and pooled["auc"] > 0.8
    assert calibration.validation["validated"] is True


def test_naturalness_is_deterministic(reference_texts, calibration):
    a = nat.score_naturalness(
        nat.measure_naturalness(reference_texts[3]), calibration, context="academic"
    )
    b = nat.score_naturalness(
        nat.measure_naturalness(reference_texts[3]), calibration, context="academic"
    )
    assert a.to_dict() == b.to_dict()


def test_formal_register_is_not_a_naturalness_dimension():
    assert not {"passive_rate", "long_word_rate", "contraction_rate"} & set(nat.DIMENSIONS)


def test_more_variation_than_reference_is_not_penalised(calibration):
    reference = calibration.reference["sentence_variation"]
    pairs = [(v, 1.0) for v in reference]
    assert nat._tail("sentence_variation", max(reference) * 3, pairs) == 1.0


def test_uniform_paragraphs_registers_as_less_paragraph_variation(reference_texts):
    original = nat.measure_naturalness(reference_texts[0])
    uniform = nat.measure_naturalness(uniform_paragraphs(reference_texts[0]))
    assert uniform.values["paragraph_variation"] < original.values["paragraph_variation"]


def test_disclaimer_rejects_authorship_probability():
    assert "not the probability" in nat.DISCLAIMER and "not an AI detector" in nat.DISCLAIMER


# --- voice match ---


@pytest.fixture(scope="module")
def vm_calibration():
    training = [vm.measure_text(author_a(seed, byline=False))[0] for seed in range(20)]
    holdout = [vm.measure_text(author_a(seed, byline=False))[0] for seed in range(20, 26)]
    controls = {"third_party": [vm.measure_text(author_b(seed))[0] for seed in range(10)]}
    fingerprints = [vm.TextFingerprint.of(author_a(seed, byline=False)) for seed in range(20)]
    return vm.build_calibration(
        profile="test-academic",
        context="academic",
        training=training,
        holdout=holdout,
        controls=controls,
        training_fingerprints=fingerprints,
    )


def test_voice_match_separates_authors(vm_calibration):
    same = vm.score_voice_match(
        author_a(900, byline=False), vm_calibration, profile="p", context="academic"
    )
    other = vm.score_voice_match(author_b(901), vm_calibration, profile="p", context="academic")
    assert same.status == vm.STATUS_SCORED and other.status == vm.STATUS_SCORED
    assert same.score > other.score
    assert other.band == vm.ATYPICAL
    assert vm_calibration.validated()


def test_voice_match_refuses_training_documents(vm_calibration):
    report = vm.score_voice_match(
        author_a(3, byline=False), vm_calibration, profile="p", context="academic"
    )
    assert report.status == vm.STATUS_UNAVAILABLE and report.calibration_status == "CONTAMINATED"


def test_voice_match_withholds_short_documents(vm_calibration):
    report = vm.score_voice_match(
        "A short note about a capture.", vm_calibration, profile="p", context="academic"
    )
    assert report.status == vm.STATUS_UNAVAILABLE and str(vm.MIN_WORDS) in report.reason


def test_voice_match_withholds_without_enough_calibration():
    training = [vm.measure_text(author_a(seed, byline=False))[0] for seed in range(4)]
    calibration = vm.build_calibration(profile="p", context="academic", training=training)
    report = vm.score_voice_match(
        author_a(950, byline=False), calibration, profile="p", context="academic"
    )
    assert report.status == vm.STATUS_UNAVAILABLE and report.calibration_status == "INSUFFICIENT"
    assert report.dimensions  # descriptive output still present


def test_voice_match_withholds_when_validation_failed():
    # Controls drawn from the same author cannot be separated from it.
    training = [vm.measure_text(author_a(seed, byline=False))[0] for seed in range(16)]
    controls = {
        "same": [vm.measure_text(author_a(seed, byline=False))[0] for seed in range(100, 130)]
    }
    calibration = vm.build_calibration(
        profile="p", context="academic", training=training, controls=controls
    )
    if not calibration.validation_failed():
        pytest.skip(
            "synthetic draw happened to separate; the refusal path is covered by the ceiling check"
        )
    report = vm.score_voice_match(
        author_a(999, byline=False), calibration, profile="p", context="academic"
    )
    assert report.calibration_status == "FAILED_VALIDATION" and report.score is None


def test_scores_are_independent(calibration, vm_calibration):
    """Natural prose by someone else: fine on naturalness, far on voice."""
    other = author_b(4040, paragraphs=14)
    natural = nat.score_naturalness(nat.measure_naturalness(other), calibration, context="academic")
    voice = vm.score_voice_match(other, vm_calibration, profile="p", context="academic")
    assert voice.band == vm.ATYPICAL
    assert natural.dimensions and voice.dimensions
    assert {d.name for d in natural.dimensions}.isdisjoint({d.name for d in voice.dimensions})


def test_calibration_round_trips(vm_calibration):
    again = vm.VoiceMatchCalibration.from_dict(vm_calibration.to_dict())
    text = author_a(1234, byline=False)
    assert (
        vm.score_voice_match(text, again, profile="p", context="a").score
        == vm.score_voice_match(text, vm_calibration, profile="p", context="a").score
    )


# --- drift ---


def test_drift_flags_a_departing_passage_and_says_nothing_about_authorship():
    baseline = drift.build_baseline(
        "p", [drift.window_metrics(author_a(s, byline=False)) for s in range(25)]
    )
    assert baseline.usable
    long_passage = " ".join(
        "Furthermore, the comprehensive multi-layered monitoring architecture leverages a wide range "
        "of interconnected telemetry sources in order to holistically surface every conceivable "
        "category of anomalous behaviour across the entire enterprise environment."
        for _ in range(5)
    )
    document = author_a(31, byline=False) + "\n\n" + long_passage
    result = drift.analyze(document, baseline, context_label="academic")
    assert result["status"] == "ANALYZED"
    assert any(
        f["metric"] == "sentence_length_mean" and f["direction"] == "high"
        for f in result["findings"]
    )
    assert all("AI" not in f["message"] for f in result["findings"])
    assert "do not say how a passage was written" in result["note"]


def test_drift_unavailable_without_baseline():
    assert drift.analyze(author_a(1), None)["status"] == "UNAVAILABLE"


def test_ordinary_documents_produce_few_drift_findings():
    baseline = drift.build_baseline(
        "p", [drift.window_metrics(author_a(s, byline=False)) for s in range(25)]
    )
    findings = drift.analyze(author_a(60, byline=False), baseline)["findings"]
    assert len(findings) <= 2


def test_style_altered_diagnostics_are_reported_but_not_pooled():
    from howlwriter.evaluation.perturb import formulaic_injection

    training = [vm.measure_text(author_a(seed, byline=False))[0] for seed in range(16)]
    holdout_texts = [author_a(seed, byline=False) for seed in range(16, 20)]
    calibration = vm.build_calibration(
        profile="p",
        context="academic",
        training=training,
        holdout=[vm.measure_text(t)[0] for t in holdout_texts],
        diagnostic_controls={
            "style_altered": [vm.measure_text(formulaic_injection(t))[0] for t in holdout_texts]
        },
    )
    assert "style_altered" in calibration.validation["diagnostics"]
    assert calibration.validation["pooled_separation"]["control_n"] == 0
    assert calibration.validated() is False


def test_naturalness_is_ranked_against_comparable_lengths(reference_texts):
    """A long document is not ranked against a reference of short ones."""
    short = [author_a(seed, paragraphs=6, byline=False) for seed in range(200, 230)]
    calibration = nat.build_calibration(_measure(short), context="academic", source="short only")
    long_doc = "\n\n".join(author_a(seed, paragraphs=9, byline=False) for seed in range(300, 312))
    report = nat.score_naturalness(nat.measure_naturalness(long_doc), calibration, context="academic")
    assert report.status == nat.STATUS_UNAVAILABLE
    assert "comparable length" in report.reason


def test_calibration_records_its_length_correlation(calibration):
    assert "length_correlation" in calibration.validation
    assert calibration.validation["length_bandwidth"] == nat.LENGTH_BANDWIDTH
