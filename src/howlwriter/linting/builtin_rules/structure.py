"""Detects repetitive paragraph structure: many paragraphs opening with the
same word or having highly uniform length, both common tells of templated
LLM output."""

from __future__ import annotations

import re
import statistics
from collections import Counter

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.rules import (
    AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY,
    AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE,
    RuleMatch,
)

_FIRST_WORD = re.compile(r"^[#*\s]*([A-Za-z']+)")
_MIN_REPEATS = 3
_MIN_PARAGRAPHS_FOR_SYMMETRY = 4
_LENGTH_SYMMETRY_STDEV_THRESHOLD = 0.75  # paragraphs within one sentence of each other


def check(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "repetitive_paragraph_structure" not in config.banned_patterns:
        return []
    if len(document.paragraphs) < _MIN_REPEATS:
        return []

    openers = []
    for paragraph in document.paragraphs:
        found = _FIRST_WORD.match(paragraph.raw_text)
        openers.append(found.group(1).lower() if found else None)

    counts = Counter(word for word in openers if word)
    repeated = [(word, count) for word, count in counts.items() if count >= _MIN_REPEATS]
    if not repeated:
        return []

    return [
        RuleMatch(
            rule_code=AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE,
            matched_text=word,
            message=f'{count} paragraphs open with "{word.capitalize()}" -- repetitive structure.',
        )
        for word, count in repeated
    ]


def check_paragraph_length_symmetry(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    """Flag paragraphs with suspiciously uniform sentence counts.

    Natural writing varies; many paragraphs containing the same number of
    sentences can indicate mechanical generation."""
    if "paragraph_length_symmetry" not in config.banned_patterns:
        return []
    counts = [len(p.sentences) for p in document.paragraphs if p.sentences]
    if len(counts) < _MIN_PARAGRAPHS_FOR_SYMMETRY:
        return []
    if len(set(counts)) == 1:
        return [
            RuleMatch(
                rule_code=AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY,
                matched_text=str(counts[0]),
                message=(
                    f"All {len(counts)} paragraphs have {counts[0]} sentences "
                    "-- highly uniform structure."
                ),
            )
        ]
    stdev = statistics.pstdev(counts) if len(counts) > 1 else 0
    mean_count = statistics.mean(counts)
    if mean_count > 2.0 and stdev <= _LENGTH_SYMMETRY_STDEV_THRESHOLD:
        return [
            RuleMatch(
                rule_code=AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY,
                matched_text=str(int(mean_count)),
                message=(
                    f"Paragraph sentence counts vary only by {stdev:.1f} "
                    "sentences -- may be mechanically uniform."
                ),
            )
        ]
    return []
