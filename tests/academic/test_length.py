"""Tests for deterministic academic word counting and tolerance evaluation."""

from howlwriter.academic.length import (
    calculate_word_tolerance,
    count_body_words,
    evaluate_word_count,
    evaluate_word_count_bounds,
    extract_body_text,
    resolve_length_bounds,
    strip_frontmatter,
)
from howlwriter.academic.spec import AssignmentSpec, LengthConstraints


def test_strip_frontmatter():
    text_with_fm = """---
title: Test Paper
author: Alice
---
# Main Heading

This is the body text."""
    assert strip_frontmatter(text_with_fm).startswith("# Main Heading")


def test_extract_body_text_excludes_references():
    paper = """# Autonomous Agents in Zero Trust

Autonomous agents require robust authentication (Smith, 2024).
They challenge static perimeter defenses.

# References

Smith, J. (2024). Zero Trust Systems. ACM Press.
"""
    body = extract_body_text(paper)
    assert "Smith, J. (2024)" not in body
    assert "# References" not in body
    assert "Autonomous agents require robust" in body


def test_count_body_words_accuracy():
    paper = """# Zero Trust Identity

Autonomous agents complicate enterprise authorization by delegating sensitive tokens.
Furthermore, static API keys create persistent vulnerability windows across microservices.

# References

Smith, J. (2024). Enterprise Security.
"""
    # 3 heading words ("Zero Trust Identity") + 19 body words = 22 total words
    words = count_body_words(paper)
    assert words == 22


def test_calculate_word_tolerance():
    # 2000 words ± 10% -> 1800 to 2200
    min_w, max_w = calculate_word_tolerance(2000, 10.0)
    assert min_w == 1800
    assert max_w == 2200

    # 1500 words ± 5% -> 1425 to 1575
    min_w, max_w = calculate_word_tolerance(1500, 5.0)
    assert min_w == 1425
    assert max_w == 1575


def test_evaluate_word_count_statuses():
    # Within bounds
    status, reason = evaluate_word_count(2045, 2000, 10.0)
    assert status == "PASS"
    assert "within the acceptable range" in reason

    # Too short
    status_short, reason_short = evaluate_word_count(1650, 2000, 10.0)
    assert status_short == "TOO_SHORT"
    assert "below the minimum allowed" in reason_short

    # Too long
    status_long, reason_long = evaluate_word_count(2350, 2000, 10.0)
    assert status_long == "TOO_LONG"
    assert "exceeds the maximum allowed" in reason_long


def test_resolve_length_bounds_words_only_matches_legacy():
    # No length_constraints set: bounds must be identical to calling
    # calculate_word_tolerance directly -- this is the backward-compat guarantee.
    spec = AssignmentSpec(title="Test", target_words=2000, word_tolerance_percent=10.0)
    bounds = resolve_length_bounds(spec)
    expected_min, expected_max = calculate_word_tolerance(2000, 10.0)
    assert bounds.min_words == expected_min
    assert bounds.max_words == expected_max
    assert bounds.target_words == 2000
    assert bounds.hard_max_words is None
    assert bounds.source == "words"


def test_resolve_length_bounds_hard_ceiling_overrides_soft_tolerance():
    # A tolerance-derived max of 2200 would normally apply, but an explicit
    # max_words=1900 must win as the hard ceiling.
    spec = AssignmentSpec(
        title="Test",
        target_words=2000,
        word_tolerance_percent=10.0,
        length_constraints=LengthConstraints(max_words=1900),
    )
    bounds = resolve_length_bounds(spec)
    assert bounds.hard_max_words == 1900
    assert bounds.max_words == 1900
    assert bounds.target_words <= 1900


def test_resolve_length_bounds_page_range_aims_below_midpoint():
    spec = AssignmentSpec(
        title="Test",
        length_constraints=LengthConstraints(
            target_page_min=6, target_page_max=9, max_pages=10, words_per_page=275.0
        ),
    )
    bounds = resolve_length_bounds(spec)
    assert bounds.source == "pages"
    assert bounds.min_words == 1650  # 6 * 275
    assert bounds.hard_max_words == 2750  # 10 * 275
    # Target must sit strictly below the midpoint of the soft range (7.5 pages
    # = 2062 words), never near the maximum.
    soft_max = round(9 * 275)
    midpoint = (bounds.min_words + soft_max) / 2
    assert bounds.min_words < bounds.target_words < midpoint


# The following tests exercise evaluate_word_count_bounds' distinction
# between a soft target-range miss (TARGET_MISS) and a genuine hard-maximum
# breach (HARD_LIMIT_FAILURE), using the CYBR-601 dogfood scale: a 6-9 page
# soft target (1650-2475 words) with a 10-page hard maximum (2750 words).
_MIN_WORDS = 1650
_SOFT_MAX_WORDS = 2475
_HARD_MAX_WORDS = 2750
_TARGET_WORDS = 1980


def test_evaluate_word_count_bounds_backward_compat_without_hard_max():
    # No hard_max_words supplied (e.g. the general howl pipeline's call
    # pattern): legacy two-tier TOO_LONG literal must be preserved exactly.
    status, _ = evaluate_word_count_bounds(2300, 1800, 2200, 2000)
    assert status == "TOO_LONG"


def test_evaluate_word_count_bounds_within_soft_target_passes():
    # 8-9 pages, within the preferred range.
    status, _ = evaluate_word_count_bounds(
        2200, _MIN_WORDS, _SOFT_MAX_WORDS, _TARGET_WORDS, hard_max_words=_HARD_MAX_WORDS
    )
    assert status == "PASS"


def test_evaluate_word_count_bounds_over_soft_under_hard_is_target_miss():
    # ~9.4 pages: over the soft 9-page target, under the 10-page hard max.
    status, reason = evaluate_word_count_bounds(
        2585, _MIN_WORDS, _SOFT_MAX_WORDS, _TARGET_WORDS, hard_max_words=_HARD_MAX_WORDS
    )
    assert status == "TARGET_MISS"
    assert "hard maximum" in reason


def test_evaluate_word_count_bounds_at_hard_max_is_target_miss_not_hard_failure():
    # Exactly 10 pages / 2750 words: at the hard boundary, not over it --
    # "acceptable... though outside preferred target", not a hard failure.
    status, _ = evaluate_word_count_bounds(
        _HARD_MAX_WORDS,
        _MIN_WORDS,
        _SOFT_MAX_WORDS,
        _TARGET_WORDS,
        hard_max_words=_HARD_MAX_WORDS,
    )
    assert status == "TARGET_MISS"


def test_evaluate_word_count_bounds_over_hard_max_is_hard_limit_failure():
    # >10 pages: a genuine hard-maximum breach.
    status, reason = evaluate_word_count_bounds(
        2800, _MIN_WORDS, _SOFT_MAX_WORDS, _TARGET_WORDS, hard_max_words=_HARD_MAX_WORDS
    )
    assert status == "HARD_LIMIT_FAILURE"
    assert "exceeds the hard maximum" in reason


def test_evaluate_word_count_bounds_too_short_unaffected_by_hard_max():
    status, _ = evaluate_word_count_bounds(
        1000, _MIN_WORDS, _SOFT_MAX_WORDS, _TARGET_WORDS, hard_max_words=_HARD_MAX_WORDS
    )
    assert status == "TOO_SHORT"
