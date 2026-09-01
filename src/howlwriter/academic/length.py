"""Deterministic word count calculation, tolerance bounds, and text cleaning."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import TYPE_CHECKING

from howlwriter.domain.serialization import DataClassSerializationMixin

if TYPE_CHECKING:
    from howlwriter.academic.spec import AssignmentSpec

DEFAULT_WORDS_PER_PAGE = 275.0


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


def pages_to_words(pages: float, words_per_page: float = DEFAULT_WORDS_PER_PAGE) -> int:
    """Converts an approximate page count to a word count using a planning estimate.

    This is planning guidance, not a rendering guarantee -- actual pagination
    depends on formatting, tables, and headings that this estimate ignores.
    """
    return max(0, round(pages * words_per_page))


@dataclass
class ResolvedLengthBounds(DataClassSerializationMixin):
    """The effective word-count target/min/max for an assignment, after
    reconciling target_words/word_tolerance_percent with any explicit
    length_constraints (hard word/page ceilings, soft page ranges)."""

    target_words: int
    min_words: int
    max_words: int
    hard_max_words: int | None = None
    source: str = "words"  # "words" | "pages"


def resolve_length_bounds(spec: "AssignmentSpec") -> ResolvedLengthBounds:
    """Resolves the effective length bounds for an assignment spec.

    Behavior is fully backward compatible: an assignment with no
    length_constraints set produces bounds identical to calling
    calculate_word_tolerance(spec.target_words, spec.word_tolerance_percent)
    directly. When length_constraints.target_page_min/target_page_max are both
    set, the soft target/min/max are derived from pages instead of
    target_words/word_tolerance_percent. Regardless of source, an explicit
    max_words and/or max_pages always clamps max_words down as a hard
    ceiling -- even below the soft-tolerance max -- since the point of a hard
    ceiling is that it must never be exceeded by aiming for a looser range.
    """
    lc = spec.length_constraints
    words_per_page = lc.words_per_page or DEFAULT_WORDS_PER_PAGE

    if lc.target_page_min is not None and lc.target_page_max is not None:
        source = "pages"
        min_words = pages_to_words(lc.target_page_min, words_per_page)
        soft_max_words = pages_to_words(lc.target_page_max, words_per_page)
        # Aim near the lower-middle of the requested range, not its midpoint
        # and never its maximum -- a requested 6-9 page range should be
        # planned around ~7-8 pages, not padded toward 9.
        target_words = min_words + round((soft_max_words - min_words) * 0.4)
    else:
        source = "words"
        min_words, soft_max_words = calculate_word_tolerance(
            spec.target_words, spec.word_tolerance_percent
        )
        target_words = spec.target_words

    hard_max_candidates: list[int] = []
    if lc.max_words is not None:
        hard_max_candidates.append(lc.max_words)
    if lc.max_pages is not None:
        hard_max_candidates.append(pages_to_words(lc.max_pages, words_per_page))
    hard_max_words = min(hard_max_candidates) if hard_max_candidates else None

    max_words = soft_max_words
    if hard_max_words is not None:
        max_words = min(max_words, hard_max_words)
        target_words = min(target_words, max_words)
        # min_words is intentionally NOT clamped down to max_words here: if
        # the hard ceiling is tighter than the soft-range minimum, that is a
        # genuine contradiction in the assignment spec (validate_assignment_spec
        # surfaces it as an error) rather than something to silently resolve.

    return ResolvedLengthBounds(
        target_words=target_words,
        min_words=min_words,
        max_words=max_words,
        hard_max_words=hard_max_words,
        source=source,
    )


def evaluate_word_count_bounds(
    actual_words: int,
    min_words: int,
    max_words: int,
    target_words: int,
    hard_max_words: int | None = None,
) -> tuple[str, str]:
    """Evaluates whether actual word count is within externally supplied bounds.

    Against bounds already resolved elsewhere (e.g. via resolve_length_bounds
    or a caller-supplied target_words/max_words pair), rather than
    recomputing symmetric tolerance bounds internally.

    hard_max_words is optional and distinguishes an absolute, non-negotiable
    ceiling from the soft target ceiling represented by max_words:

    - hard_max_words is None: legacy two-tier PASS/TOO_SHORT/TOO_LONG
      semantics, unchanged for callers that only ever had a single ceiling
      (e.g. the general howl pipeline's word-tolerance-only length hook).
    - hard_max_words is set: three-tier semantics distinguishing a soft
      target miss from a genuine hard-limit breach. Exceeding max_words
      while still at or under hard_max_words returns TARGET_MISS (a
      preference miss -- warrants tightening, not automatic rejection).
      Only exceeding hard_max_words returns HARD_LIMIT_FAILURE.
    """
    if actual_words < min_words:
        return (
            "TOO_SHORT",
            (
                f"Body word count ({actual_words}) is below the minimum allowed "
                f"({min_words} words; target: {target_words})."
            ),
        )
    if hard_max_words is None:
        if actual_words > max_words:
            return (
                "TOO_LONG",
                (
                    f"Body word count ({actual_words}) exceeds the maximum allowed "
                    f"({max_words} words; target: {target_words})."
                ),
            )
    else:
        if actual_words > hard_max_words:
            return (
                "HARD_LIMIT_FAILURE",
                (
                    f"Body word count ({actual_words}) exceeds the hard maximum "
                    f"({hard_max_words} words; target: {target_words})."
                ),
            )
        if actual_words > max_words:
            return (
                "TARGET_MISS",
                (
                    f"Body word count ({actual_words}) exceeds the preferred target "
                    f"ceiling ({max_words} words) but is within the hard maximum "
                    f"({hard_max_words} words; target: {target_words})."
                ),
            )
    return (
        "PASS",
        (
            f"Body word count ({actual_words}) is within the acceptable range "
            f"({min_words}–{max_words} words; target: {target_words})."
        ),
    )
