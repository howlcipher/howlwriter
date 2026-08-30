"""Rule codes and the RuleMatch result type shared by every built-in rule."""

from __future__ import annotations

from dataclasses import dataclass

from howlwriter.domain.serialization import DataClassSerializationMixin

AI_STYLE_BANNED_WORD = "AI_STYLE_BANNED_WORD"
AI_STYLE_NOT_X_BUT_Y = "AI_STYLE_NOT_X_BUT_Y"
AI_STYLE_EMPTY_TRANSITION = "AI_STYLE_EMPTY_TRANSITION"
AI_STYLE_CANNED_CONCLUSION = "AI_STYLE_CANNED_CONCLUSION"
AI_STYLE_REPETITIVE_TRICOLON = "AI_STYLE_REPETITIVE_TRICOLON"
AI_STYLE_EXCESSIVE_EM_DASH = "AI_STYLE_EXCESSIVE_EM_DASH"
AI_STYLE_EXCESSIVE_HEADINGS = "AI_STYLE_EXCESSIVE_HEADINGS"
AI_STYLE_EXCESSIVE_BOLD = "AI_STYLE_EXCESSIVE_BOLD"
AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE = "AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE"
AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS = "AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS"

# Maps a config.banned_patterns entry to the rule code it activates. A
# pattern name with no entry here is inert -- see linting/engine.py.
PATTERN_KEY_TO_RULE_CODE = {
    "not_x_but_y": AI_STYLE_NOT_X_BUT_Y,
    "empty_transition": AI_STYLE_EMPTY_TRANSITION,
    "canned_conclusion": AI_STYLE_CANNED_CONCLUSION,
    "repetitive_tricolon": AI_STYLE_REPETITIVE_TRICOLON,
    "excessive_em_dash": AI_STYLE_EXCESSIVE_EM_DASH,
    "excessive_headings": AI_STYLE_EXCESSIVE_HEADINGS,
    "excessive_bold": AI_STYLE_EXCESSIVE_BOLD,
    "repetitive_paragraph_structure": AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE,
    "excessive_rhetorical_questions": AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS,
}


@dataclass
class RuleMatch(DataClassSerializationMixin):
    rule_code: str
    matched_text: str
    message: str
    paragraph_index: int | None = None
    sentence_index: int | None = None
    severity: str = "warning"
