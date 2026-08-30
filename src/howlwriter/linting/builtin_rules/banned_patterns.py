"""Detects common AI-style phrase constructions.

Each pattern here is only active when its key is present in
config.banned_patterns -- see linting/rules.py:PATTERN_KEY_TO_RULE_CODE.
Nothing in this module treats a match as automatically wrong; the engine
only ever reports findings, never rewrites.
"""

from __future__ import annotations

import re

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.rules import (
    AI_STYLE_CANNED_CONCLUSION,
    AI_STYLE_EMPTY_TRANSITION,
    AI_STYLE_NOT_X_BUT_Y,
    AI_STYLE_REPETITIVE_TRICOLON,
    RuleMatch,
)

_NOT_X_BUT_Y = re.compile(
    r"\b(?:it'?s|it is) not (?:just )?[^,.;!?]+,\s*(?:it'?s|it is)\b",
    re.IGNORECASE,
)

_EMPTY_TRANSITION_PHRASES = (
    "at its core",
    "in today's rapidly evolving",
    "whether you're",
    "whether you are",
)

_CANNED_CONCLUSION_PHRASES = (
    "this highlights the importance of",
    "the reality is",
)

_TRICOLON = re.compile(r"\b\w+,\s+\w+,\s+(?:and|or)\s+\w+\b")
_TRICOLON_THRESHOLD = 3  # 3+ parallel three-item lists reads as a tic, not a style.


def _phrase_matches(sentence_text: str, phrases: tuple[str, ...]) -> list[str]:
    lowered = sentence_text.lower()
    return [phrase for phrase in phrases if phrase in lowered]


def check_not_x_but_y(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "not_x_but_y" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        found = _NOT_X_BUT_Y.search(sentence.text)
        if found:
            matches.append(
                RuleMatch(
                    rule_code=AI_STYLE_NOT_X_BUT_Y,
                    matched_text=found.group(0),
                    message='Contrast construction ("It\'s not X, it\'s Y") -- often filler.',
                    paragraph_index=p_index,
                    sentence_index=s_index,
                )
            )
    return matches


def check_empty_transition(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "empty_transition" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        for phrase in _phrase_matches(sentence.text, _EMPTY_TRANSITION_PHRASES):
            matches.append(
                RuleMatch(
                    rule_code=AI_STYLE_EMPTY_TRANSITION,
                    matched_text=phrase,
                    message=f'Empty transition phrase: "{phrase}"',
                    paragraph_index=p_index,
                    sentence_index=s_index,
                )
            )
    return matches


def check_canned_conclusion(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "canned_conclusion" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        for phrase in _phrase_matches(sentence.text, _CANNED_CONCLUSION_PHRASES):
            matches.append(
                RuleMatch(
                    rule_code=AI_STYLE_CANNED_CONCLUSION,
                    matched_text=phrase,
                    message=f'Canned-conclusion phrase: "{phrase}"',
                    paragraph_index=p_index,
                    sentence_index=s_index,
                )
            )
    return matches


def check_repetitive_tricolon(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "repetitive_tricolon" not in config.banned_patterns:
        return []
    hits: list[tuple[int, int, str]] = []
    for p_index, s_index, sentence in document.all_sentences():
        found = _TRICOLON.search(sentence.text)
        if found:
            hits.append((p_index, s_index, found.group(0)))
    if len(hits) < _TRICOLON_THRESHOLD:
        return []
    return [
        RuleMatch(
            rule_code=AI_STYLE_REPETITIVE_TRICOLON,
            matched_text=text,
            message=f"Repetitive three-item list pattern ({len(hits)} occurrences in this document).",
            paragraph_index=p_index,
            sentence_index=s_index,
        )
        for p_index, s_index, text in hits
    ]
