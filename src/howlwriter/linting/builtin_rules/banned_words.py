"""Detects configured banned words. Always active; simply finds nothing
when config.banned_words is empty -- this is the one rule not gated by
banned_patterns, since it has its own config list."""

from __future__ import annotations

import re

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD, RuleMatch

_WORD = re.compile(r"[A-Za-z']+")


def check(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if not config.banned_words:
        return []
    banned = {bw.word.lower() for bw in config.banned_words}
    matches: list[RuleMatch] = []
    for p_index, s_index, sentence in document.all_sentences():
        for word_match in _WORD.finditer(sentence.text):
            token = word_match.group(0)
            if token.lower() in banned:
                matches.append(
                    RuleMatch(
                        rule_code=AI_STYLE_BANNED_WORD,
                        matched_text=token,
                        message=f'Banned word "{token}"',
                        paragraph_index=p_index,
                        sentence_index=s_index,
                    )
                )
    return matches
