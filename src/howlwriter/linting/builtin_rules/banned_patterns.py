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
    AI_STYLE_CANNED_OPENING,
    AI_STYLE_CORPORATE_FILLER,
    AI_STYLE_EMPTY_TRANSITION,
    AI_STYLE_FORMULAIC_CONTRAST,
    AI_STYLE_GENERIC_INTENSIFIER,
    AI_STYLE_GENERIC_TRANSITION,
    AI_STYLE_NOT_X_BUT_Y,
    AI_STYLE_REPETITIVE_MINI_CONCLUSION,
    AI_STYLE_REPETITIVE_TRICOLON,
    RuleMatch,
)

_NOT_X_BUT_Y = re.compile(
    r"\b(?:it'?s|it is) not (?:just |merely )?[^,.;!?]+,?\s*(?:it'?s|it is)\b",
    re.IGNORECASE,
)

_FORMULAIC_CONTRAST = re.compile(
    r"\bnot only\s+[^,.;!?]+?\s*,?\s*but also\b|"
    r"\b(?:this|it)\s+is(?:n't| not)\s+(?:just |merely |about )?"
    r"[^,.;!?]+?\s*[;:,]\s*(?:it is|it's)\s+"
    r"(?:about|a matter of|simply)\b",
    re.IGNORECASE,
)

# Public (not underscore-prefixed): reused by redpen/critic.py so filler
# detection doesn't grow a second, drifting phrase list.
EMPTY_TRANSITION_PHRASES = (
    "at its core",
    "in today's rapidly evolving",
    "in an era where",
    "as technology continues to evolve",
    "in the ever-changing landscape",
    "in the rapidly changing world of",
    "whether you're",
    "whether you are",
)

CANNED_OPENING_PHRASES = (
    "in today's rapidly evolving",
    "in an era where",
    "as technology continues to evolve",
    "in the ever-changing landscape",
    "in the rapidly changing world of",
    "in recent years",
    "nowadays",
)

CANNED_CONCLUSION_PHRASES = (
    "this highlights the importance of",
    "the reality is",
    "in conclusion",
    "to conclude",
    "as we move forward",
    "the future is bright",
    "ultimately, it is clear that",
    "it is clear that",
)

# Flag only when these transitions are used mechanically (3+ occurrences across
# the document). Normal use of "furthermore" once is fine.
GENERIC_TRANSITIONS = (
    "furthermore",
    "moreover",
    "additionally",
    "consequently",
    "therefore",
    "thus",
    "hence",
)
_GENERIC_TRANSITION_THRESHOLD = 3

GENERIC_INTENSIFIERS = (
    "crucial",
    "pivotal",
    "transformative",
    "groundbreaking",
    "game-changing",
    "powerful",
    "robust",
    "vital",
    "essential",
    "critical",
)

CORPORATE_FILLER = (
    "leverage",
    "synergy",
    "unlock",
    "empower",
    "drive value",
    "seamless",
    "holistic",
    "optimize",
    "elevate",
    "streamline",
    "maximize",
    "scalable",
)

_TRICOLON = re.compile(r"\b\w+,\s+\w+,\s+(?:and|or)\s+\w+\b")
_TRICOLON_THRESHOLD = 3  # 3+ parallel three-item lists reads as a tic, not a style.

_MINI_CONCLUSION_PHRASES = (
    "in summary",
    "to summarize",
    "overall",
    "all in all",
    "at the end of the day",
)
_MINI_CONCLUSION_THRESHOLD = 3


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


def check_formulaic_contrast(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "formulaic_contrast" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        found = _FORMULAIC_CONTRAST.search(sentence.text)
        if found:
            matches.append(
                RuleMatch(
                    rule_code=AI_STYLE_FORMULAIC_CONTRAST,
                    matched_text=found.group(0),
                    message=(
                        'Formulaic contrast ("not only X but also Y" / '
                        "\"isn't about X, it's about Y\") -- "
                        "consider a simpler construction."
                    ),
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
        for phrase in _phrase_matches(sentence.text, EMPTY_TRANSITION_PHRASES):
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


def check_canned_opening(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "canned_opening" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    # Canned openings matter most when they appear at the start of the document.
    first_paragraphs = document.paragraphs[:2]
    for paragraph in first_paragraphs:
        for s_index, sentence in enumerate(paragraph.sentences):
            for phrase in _phrase_matches(sentence.text, CANNED_OPENING_PHRASES):
                matches.append(
                    RuleMatch(
                        rule_code=AI_STYLE_CANNED_OPENING,
                        matched_text=phrase,
                        message=f'Canned opening phrase: "{phrase}"',
                        paragraph_index=paragraph.index,
                        sentence_index=s_index,
                    )
                )
    return matches


def check_canned_conclusion(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "canned_conclusion" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        for phrase in _phrase_matches(sentence.text, CANNED_CONCLUSION_PHRASES):
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


def check_generic_transition(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "generic_transition" not in config.banned_patterns:
        return []
    hits: list[tuple[int, int, str]] = []
    for p_index, s_index, sentence in document.all_sentences():
        lowered = sentence.text.lower()
        for phrase in GENERIC_TRANSITIONS:
            if phrase in lowered:
                hits.append((p_index, s_index, phrase))
    if len(hits) < _GENERIC_TRANSITION_THRESHOLD:
        return []
    first_p, first_s, first_phrase = hits[0]
    return [
        RuleMatch(
            rule_code=AI_STYLE_GENERIC_TRANSITION,
            matched_text=first_phrase,
            message=f"Generic transition words appear {len(hits)} times -- may read mechanically.",
            paragraph_index=first_p,
            sentence_index=first_s,
        )
    ]


def check_generic_intensifier(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "generic_intensifier" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        for phrase in _phrase_matches(sentence.text, GENERIC_INTENSIFIERS):
            matches.append(
                RuleMatch(
                    rule_code=AI_STYLE_GENERIC_INTENSIFIER,
                    matched_text=phrase,
                    message=f'Generic intensifier that often adds no concrete meaning: "{phrase}"',
                    paragraph_index=p_index,
                    sentence_index=s_index,
                )
            )
    return matches


def check_corporate_filler(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "corporate_filler" not in config.banned_patterns:
        return []
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        for phrase in _phrase_matches(sentence.text, CORPORATE_FILLER):
            matches.append(
                RuleMatch(
                    rule_code=AI_STYLE_CORPORATE_FILLER,
                    matched_text=phrase,
                    message=f'Abstract corporate filler: "{phrase}"',
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


def check_repetitive_mini_conclusion(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    """Flag paragraphs whose final sentence is a mini-conclusion phrase."""
    if "repetitive_mini_conclusion" not in config.banned_patterns:
        return []
    hits: list[tuple[int, int, str]] = []
    for paragraph in document.paragraphs:
        if not paragraph.sentences:
            continue
        last = paragraph.sentences[-1]
        for phrase in _phrase_matches(last.text, _MINI_CONCLUSION_PHRASES):
            hits.append((paragraph.index, last.index, phrase))
    if len(hits) < _MINI_CONCLUSION_THRESHOLD:
        return []
    first_p, first_s, first_phrase = hits[0]
    return [
        RuleMatch(
            rule_code=AI_STYLE_REPETITIVE_MINI_CONCLUSION,
            matched_text=first_phrase,
            message=(
                f"{len(hits)} paragraphs end with a mini-conclusion phrase "
                f"(e.g., '{first_phrase}') -- may be a structural tic."
            ),
            paragraph_index=first_p,
            sentence_index=first_s,
        )
    ]
