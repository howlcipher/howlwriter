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

#: A trailing line of hashtags is a publishing convention, not a paragraph.
#: Counting it as one put a three-word block into every short-form post, which
#: dragged the minimum paragraph length under any floor and made the word-count
#: symmetry check below unreachable for exactly the content it was written for.
_TAG_ONLY_LINE = re.compile(r"^\s*(?:#[\w-]+|@[\w-]+)(?:\s+(?:#[\w-]+|@[\w-]+))*\s*$")

#: Shortest paragraph a body has to contain before uniform word counts mean
#: anything. Below this, a run of one-line paragraphs is a cadence choice.
_MIN_WORDS_FOR_WORD_SYMMETRY = 15

#: Coefficient of variation at or under which paragraph word counts read as
#: mechanically produced rather than written.
#:
#: Heuristic, not derived from any one corpus. Human short-form prose measured
#: during this work sat between 0.15 and 0.75; the value is set below that
#: observed floor so the rule accuses only genuinely metronomic output, and is
#: expected to need revisiting as more shapes are seen. It is a tell, not a
#: measurement, and it is deliberately biased towards missing cases rather
#: than towards flagging real writing.
_WORD_SYMMETRY_CV_THRESHOLD = 0.12


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
    """Flag paragraphs with suspiciously uniform sentence or word counts.

    Natural writing varies; many paragraphs containing the same number of
    sentences or nearly identical word counts can indicate mechanical generation."""
    if "paragraph_length_symmetry" not in config.banned_patterns:
        return []
    counts = [len(p.sentences) for p in document.paragraphs if p.sentences]
    if len(counts) < _MIN_PARAGRAPHS_FOR_SYMMETRY:
        return []

    # 1. Sentence-count symmetry. A short post built from four or five
    # one-line paragraphs is a cadence choice rather than a tell, so it is
    # exempted and falls through to the word-count check below.
    short_form_cadence = (
        counts[0] == 1 and len(counts) <= 5 and len(document.text.split()) < 150
    )
    if len(set(counts)) == 1 and not short_form_cadence:
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

    # 2. Word-count hyper-symmetry (paragraphs with suspiciously identical word counts)
    words_per_p = [
        len(p.raw_text.split())
        for p in document.paragraphs
        if p.raw_text.strip() and not _TAG_ONLY_LINE.match(p.raw_text.strip())
    ]
    if (
        len(words_per_p) >= _MIN_PARAGRAPHS_FOR_SYMMETRY
        and min(words_per_p) >= _MIN_WORDS_FOR_WORD_SYMMETRY
    ):
        w_mean = statistics.mean(words_per_p)
        w_stdev = statistics.pstdev(words_per_p)
        if w_mean > 0 and (w_stdev / w_mean) <= _WORD_SYMMETRY_CV_THRESHOLD:
            return [
                RuleMatch(
                    rule_code=AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY,
                    matched_text=f"{w_mean:.0f} words",
                    message=(
                        f"Paragraph word counts are hyper-uniform (~{w_mean:.0f} words each, "
                        f"variation {w_stdev / w_mean:.2f}) -- may be mechanically generated."
                    ),
                )
            ]

    return []
