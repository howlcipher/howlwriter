"""The deterministic lint engine: runs every registered rule and collects
findings. No rule is hard-coded as always-on -- each checks config for
itself (see builtin_rules/*) and returns no findings when its pattern or
word list is not configured."""

from __future__ import annotations

from typing import Callable

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.builtin_rules import banned_patterns, banned_words, punctuation, rhetorical, structure
from howlwriter.linting.rules import RuleMatch

RuleFunc = Callable[[Document, HowlWriterConfig], list[RuleMatch]]

RULE_REGISTRY: list[RuleFunc] = [
    banned_words.check,
    banned_patterns.check_not_x_but_y,
    banned_patterns.check_empty_transition,
    banned_patterns.check_canned_conclusion,
    banned_patterns.check_repetitive_tricolon,
    punctuation.check_excessive_em_dash,
    punctuation.check_excessive_headings,
    punctuation.check_excessive_bold,
    structure.check,
    rhetorical.check,
]


class LintEngine:
    def run(self, document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
        matches: list[RuleMatch] = []
        for rule in RULE_REGISTRY:
            matches.extend(rule(document, config))
        return matches
