"""Detects repetitive paragraph structure: many paragraphs opening with the
same word, a common tell of templated LLM output."""

from __future__ import annotations

import re
from collections import Counter

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.rules import AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE, RuleMatch

_FIRST_WORD = re.compile(r"^[#*\s]*([A-Za-z']+)")
_MIN_REPEATS = 3


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
