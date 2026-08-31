"""Tests for deterministic academic word counting and tolerance evaluation."""

from howlwriter.academic.length import (
    calculate_word_tolerance,
    count_body_words,
    evaluate_word_count,
    extract_body_text,
    strip_frontmatter,
)


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
