"""Deterministic word count calculation, tolerance bounds, and text cleaning."""

from __future__ import annotations

import math
import re


def strip_frontmatter(text: str) -> str:
    """Strips YAML/TOML frontmatter from the beginning of markdown text."""
    trimmed = text.strip()
    if trimmed.startswith("---"):
        parts = trimmed.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return trimmed


def extract_body_text(text: str) -> str:
    """Extracts only the body of the academic paper, excluding References section."""
    clean = strip_frontmatter(text)

    # Find where "# References" or "## References" or "### References" or "REFERENCES" starts
    ref_pattern = re.compile(
        r"(?:^|\n)#{1,3}\s*References(?:\s*\n|\Z)",
        re.IGNORECASE,
    )
    match = ref_pattern.search(clean)
    if match:
        return clean[: match.start()].strip()

    return clean.strip()


def count_body_words(text: str) -> int:
    """Deterministically counts body words of an academic paper.

    Excludes:
    - YAML frontmatter
    - References / Bibliography section
    - Markdown headers/syntax markers
    """
    body = extract_body_text(text)
    if not body:
        return 0

    # Remove markdown links [text](url) -> text
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)

    # Remove code blocks
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"`[^`]+`", "", body)

    # Remove markdown heading symbols (#, ##, etc.)
    body = re.sub(r"^#{1,6}\s+", "", body, flags=re.MULTILINE)

    # Remove bold/italic markers
    body = re.sub(r"[*_]{1,3}", "", body)

    # Tokenize words using standard word boundaries
    tokens = re.findall(r"\b[\w'-]+\b", body)
    return len(tokens)


def calculate_word_tolerance(
    target_words: int, tolerance_percent: float = 10.0
) -> tuple[int, int]:
    """Calculates min and max allowed words given target and tolerance percentage."""
    if target_words <= 0:
        return (0, 0)
    delta = target_words * (tolerance_percent / 100.0)
    min_words = max(1, math.floor(target_words - delta))
    max_words = math.ceil(target_words + delta)
    return (min_words, max_words)


def evaluate_word_count(
    actual_words: int, target_words: int, tolerance_percent: float = 10.0
) -> tuple[str, str]:
    """Evaluates whether actual word count is within bounds.

    Returns (status, explanation) where status is 'PASS', 'TOO_SHORT', or 'TOO_LONG'.
    """
    min_words, max_words = calculate_word_tolerance(target_words, tolerance_percent)
    if actual_words < min_words:
        return (
            "TOO_SHORT",
            (
                f"Body word count ({actual_words}) is below the minimum allowed "
                f"({min_words} words; target: {target_words} ±{tolerance_percent:.0f}%)."
            ),
        )
    if actual_words > max_words:
        return (
            "TOO_LONG",
            (
                f"Body word count ({actual_words}) exceeds the maximum allowed "
                f"({max_words} words; target: {target_words} ±{tolerance_percent:.0f}%)."
            ),
        )
    return (
        "PASS",
        (
            f"Body word count ({actual_words}) is within the acceptable range "
            f"({min_words}–{max_words} words; target: {target_words})."
        ),
    )
