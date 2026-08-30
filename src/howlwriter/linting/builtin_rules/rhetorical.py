"""Detects an excessive rate of rhetorical questions."""

from __future__ import annotations

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.linting.rules import AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS, RuleMatch

_MIN_QUESTION_COUNT = 3
_RATIO_THRESHOLD = 0.25


def check(document: Document, config: HowlWriterConfig) -> list[RuleMatch]:
    if "excessive_rhetorical_questions" not in config.banned_patterns:
        return []
    sentences = document.all_sentences()
    if not sentences:
        return []
    questions = [(p, s, sent) for p, s, sent in sentences if sent.text.rstrip().endswith("?")]
    if len(questions) < _MIN_QUESTION_COUNT:
        return []
    if len(questions) / len(sentences) < _RATIO_THRESHOLD:
        return []
    p_index, s_index, sentence = questions[0]
    return [
        RuleMatch(
            rule_code=AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS,
            matched_text=sentence.text,
            message=f"{len(questions)} of {len(sentences)} sentences are questions -- rhetorical overuse.",
            paragraph_index=p_index,
            sentence_index=s_index,
        )
    ]
