"""Detects excessive em-dash use, excessive headings, and unnecessary bold.

Each is a document-level count against a threshold, not a per-sentence
check -- a single em dash is normal prose, only volume makes it a tic.
Findings are document-level (paragraph_index=None) since the signal is the
aggregate, not any one occurrence.
"""

from __future__ import annotations

import re

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.rules import (
    AI_STYLE_EXCESSIVE_BOLD,
    AI_STYLE_EXCESSIVE_EM_DASH,
    AI_STYLE_EXCESSIVE_HEADINGS,
    RuleMatch,
)

_EM_DASH_THRESHOLD = 4
_HEADING_RATIO_THRESHOLD = 0.4  # headings as a fraction of all paragraphs
_HEADING_MIN_COUNT = 3
_BOLD_THRESHOLD = 5
_BOLD_PATTERN = re.compile(r"\*\*[^*]+\*\*")


def check_excessive_em_dash(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "excessive_em_dash" not in config.banned_patterns:
        return []
    count = document.text.count("—") + document.text.count("--")
    if count < _EM_DASH_THRESHOLD:
        return []
    return [
        RuleMatch(
            rule_code=AI_STYLE_EXCESSIVE_EM_DASH,
            matched_text="—",
            message=f"{count} em dashes in this document -- consider varying punctuation.",
        )
    ]


def check_excessive_headings(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "excessive_headings" not in config.banned_patterns:
        return []
    total = len(document.paragraphs)
    if total == 0:
        return []
    heading_paragraphs = [p for p in document.paragraphs if p.raw_text.lstrip().startswith("#")]
    heading_count = len(heading_paragraphs)
    if heading_count < _HEADING_MIN_COUNT or heading_count / total < _HEADING_RATIO_THRESHOLD:
        return []
    return [
        RuleMatch(
            rule_code=AI_STYLE_EXCESSIVE_HEADINGS,
            matched_text="#",
            message=f"{heading_count} of {total} paragraphs are headings -- may be over-structured.",
        )
    ]


def check_excessive_bold(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "excessive_bold" not in config.banned_patterns:
        return []
    count = len(_BOLD_PATTERN.findall(document.text))
    if count < _BOLD_THRESHOLD:
        return []
    return [
        RuleMatch(
            rule_code=AI_STYLE_EXCESSIVE_BOLD,
            matched_text="**",
            message=f"{count} bolded spans in this document -- bold is losing its emphasis.",
        )
    ]
