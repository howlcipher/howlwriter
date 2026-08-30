"""Deterministic humanization detection.

Reuses LintEngine rather than maintaining a second pattern list: the spec
lists overlapping concerns ("excessive em dashes," "canned conclusions")
under both Humanization and Deterministic Style Linting, and two lists
would drift apart. This module just re-labels the humanization-relevant
subset of lint findings. Excessive-heading and excessive-bold findings are
left out here -- those read as formatting/structure concerns rather than
"sounds like an AI wrote this," though they still surface via `lint`.
"""

from __future__ import annotations

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import (
    AI_STYLE_BANNED_WORD,
    AI_STYLE_CANNED_CONCLUSION,
    AI_STYLE_EMPTY_TRANSITION,
    AI_STYLE_EXCESSIVE_EM_DASH,
    AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS,
    AI_STYLE_NOT_X_BUT_Y,
    AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE,
    AI_STYLE_REPETITIVE_TRICOLON,
    RuleMatch,
)

HUMANIZATION_RULE_CODES = frozenset(
    {
        AI_STYLE_BANNED_WORD,
        AI_STYLE_NOT_X_BUT_Y,
        AI_STYLE_EMPTY_TRANSITION,
        AI_STYLE_CANNED_CONCLUSION,
        AI_STYLE_REPETITIVE_TRICOLON,
        AI_STYLE_EXCESSIVE_EM_DASH,
        AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE,
        AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS,
    }
)


def detect(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    matches = LintEngine().run(document, config)
    return [match for match in matches if match.rule_code in HUMANIZATION_RULE_CODES]
