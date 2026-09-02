"""The two claims outline mode makes, and the checks that keep them honest.

The first claim is that supplying more authorship buys more control. That is
testable only because freedom is derived from the outline rather than declared,
so the progression tests below walk one idea through five authorship levels and
assert the states come out in order.

The second claim is that the outline's guarantees actually hold in the finished
text. A model asked whether it followed the outline will say yes, so every
check here reads the artifact instead.
"""

from __future__ import annotations

from howlwriter.domain.outline import GenerationFreedom, load_outline
from howlwriter.outline.coverage import (
    ALTERED,
    FAIL,
    MISSING,
    PASS,
    PRESENT,
    check_coverage,
)
from howlwriter.outline.freedom import assess_freedom

_IDEA = "AI reduces implementation cost, so code stops being the moat."
_VERBATIM = "If every company has access to the same models, using AI isn't really a moat."


# --- the five authorship levels -----------------------------------------

def _sparse():
    return load_outline({"topic": _IDEA, "target_words": 250, "nodes": [
        {"kind": "idea", "text": _IDEA},
    ]})


def _minimal():
    return load_outline({"topic": _IDEA, "target_words": 250, "nodes": [
        {"kind": "idea", "text": "AI lowers implementation cost."},
        {"kind": "required_point", "text": "everyone gets similar models"},
        {"kind": "required_point", "text": "feature replication gets easier"},
        {"kind": "ending", "text": "close on data, distribution and trust"},
    ]})


def _structured():
    return load_outline({"topic": _IDEA, "target_words": 250, "nodes": [
        {"kind": "thesis", "text": "If AI makes developers replaceable, it makes SaaS replaceable too."},
        {"kind": "claim", "text": "Implementation used to require significant effort."},
        {"kind": "claim", "text": "That effort created friction."},
        {"kind": "claim", "text": "AI reduces the friction."},
        {"kind": "required_point", "text": "competitors gain the same capability"},
        {"kind": "required_point", "text": "code becomes less defensible"},
        {"kind": "ending", "text": "stop on proprietary data, distribution and integration"},
    ]})


def _authorship_rich():
    return load_outline({"topic": _IDEA, "target_words": 250, "nodes": [
        {"kind": "preserve", "text": _VERBATIM},
        {"kind": "thesis", "text": "If AI makes developers replaceable, it makes SaaS replaceable too."},
        {"kind": "claim", "text": "Implementation cost historically creates competitive friction."},
        {"kind": "claim", "text": "AI collapses that friction for everyone at once."},
        {"kind": "example", "text": "A workflow that previously required six months of engineering."},
        {"kind": "required_point", "text": "proprietary data and distribution remain defensible"},
        {"kind": "transition", "text": "move to proprietary data and distribution"},
        {"kind": "ending", "text": "no motivational ending"},
        {"kind": "voice_seed", "text": "I keep seeing this framed as an advantage."},
    ]})


def _near_complete():
    body = (
        "If every company has access to the same models, using AI isn't really a moat. "
        "Implementation cost used to create friction, and friction is what protected "
        "incumbents from fast followers. That friction is collapsing for everyone at "
        "the same time, which means the advantage was never the code. What survives is "
        "proprietary data, distribution you already own, and the trust that took years "
        "to earn. The moat moved; it did not disappear."
    )
    return load_outline({"topic": _IDEA, "target_words": 90, "nodes": [
        {"kind": "preserve", "text": body},
    ]})


def test_freedom_decreases_as_authorship_increases():
    """The product claim, asserted as an ordering rather than five constants."""
    levels = [
        assess_freedom(_sparse()).freedom,
        assess_freedom(_minimal()).freedom,
        assess_freedom(_structured()).freedom,
        assess_freedom(_authorship_rich()).freedom,
        assess_freedom(_near_complete()).freedom,
    ]
    assert levels == [
        GenerationFreedom.HIGH,
        GenerationFreedom.MEDIUM,
        GenerationFreedom.MEDIUM,
        GenerationFreedom.LOW,
        GenerationFreedom.MINIMAL,
    ]
    # And the structured outline must be at least as constrained as the minimal
    # one even where they share a state.
    assert (
        assess_freedom(_structured()).structure_signals
        > assess_freedom(_minimal()).structure_signals
    )


def test_every_assessment_carries_the_counts_that_produced_it():
    assessment = assess_freedom(_authorship_rich())
    assert assessment.preserved_sentences == 1
    assert assessment.claims == 3
    assert assessment.examples == 1
    assert assessment.voice_seeds == 1
    assert assessment.reasons


def test_a_near_complete_draft_is_minimal_because_of_coverage_not_structure():
    assessment = assess_freedom(_near_complete())
    assert assessment.freedom is GenerationFreedom.MINIMAL
    assert assessment.coverage >= 0.70
    assert any("editing rather than writing" in r for r in assessment.reasons)


# --- coverage ------------------------------------------------------------

_OUTLINE = load_outline({"topic": "moats", "target_words": 200, "enforce_order": True, "nodes": [
    {"kind": "preserve", "text": _VERBATIM},
    {"kind": "claim", "text": "Implementation cost creates competitive friction."},
    {"kind": "required_point", "text": "proprietary data and distribution"},
]})

_GOOD = (
    f"{_VERBATIM}\n\n"
    "Implementation cost creates competitive friction between firms.\n\n"
    "What survives is proprietary data and distribution."
)


def test_a_faithful_artifact_passes():
    report = check_coverage(_OUTLINE, _GOOD)
    assert report.status == PASS
    assert report.preserved_retained == report.preserved_supplied == 1
    assert report.required_represented == report.required_supplied == 3
    assert report.order_satisfied is True


def test_a_smoothed_verbatim_sentence_is_reported_as_altered_not_missing():
    """The failure mode that matters: it looks fine and is not what was written."""
    altered = _GOOD.replace("isn't really a moat", "is not truly a moat")
    report = check_coverage(_OUTLINE, altered)

    assert report.status == FAIL
    finding = next(f for f in report.findings if f.node_id == "preserve_1")
    assert finding.status == ALTERED
    assert "closest text" in finding.detail


def test_a_capitalisation_change_still_counts_as_altered():
    changed = _GOOD.replace("If every company", "IF EVERY COMPANY")
    report = check_coverage(_OUTLINE, changed)
    finding = next(f for f in report.findings if f.node_id == "preserve_1")
    assert finding.status == ALTERED
    assert "capitalisation" in finding.detail


def test_a_dropped_required_point_fails():
    dropped = _GOOD.replace("What survives is proprietary data and distribution.", "")
    report = check_coverage(_OUTLINE, dropped)
    assert report.status == FAIL
    assert [f.node_id for f in report.missing] == ["required_point_1"]


def test_reordering_a_fixed_argument_fails():
    reordered = (
        "What survives is proprietary data and distribution.\n\n"
        f"{_VERBATIM}\n\n"
        "Implementation cost creates competitive friction between firms."
    )
    report = check_coverage(_OUTLINE, reordered)
    assert report.order_satisfied is False
    assert report.status == FAIL
    assert report.order_findings


def test_ordering_is_not_checked_when_the_outline_leaves_it_free():
    free = load_outline({**_OUTLINE.to_dict(), "enforce_order": False})
    reordered = (
        "What survives is proprietary data and distribution.\n\n"
        f"{_VERBATIM}\n\n"
        "Implementation cost creates competitive friction between firms."
    )
    report = check_coverage(free, reordered)
    assert report.order_enforced is False
    assert report.status == PASS


def test_an_unlocatable_ordering_says_so_rather_than_passing_quietly():
    report = check_coverage(_OUTLINE, "Entirely unrelated prose about gardening.")
    assert report.status == FAIL
    assert any("too few required points" in note for note in report.notes)


def test_coverage_never_consults_a_model():
    """Structural guarantee: the checker takes text, not a provider."""
    import inspect

    from howlwriter.outline import coverage

    source = inspect.getsource(coverage)
    for forbidden in ("execute_writing_role", "bridge", "custom_backend"):
        assert forbidden not in source


def test_an_empty_artifact_reports_everything_missing_rather_than_erroring():
    report = check_coverage(_OUTLINE, "")
    assert report.status == FAIL
    assert len(report.missing) >= 2


def test_findings_serialize_for_the_provenance_record():
    report = check_coverage(_OUTLINE, _GOOD)
    payload = report.to_dict()
    assert payload["status"] == PASS
    assert all(f["status"] == PRESENT for f in payload["findings"])
    assert isinstance(payload["required_represented"], int)


def test_missing_and_present_are_distinct_statuses():
    assert PRESENT != MISSING != ALTERED
