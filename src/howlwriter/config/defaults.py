"""Built-in defaults: the bottom of the config layering stack.

Pattern keys here must match the rule codes registered in
linting/rules.py (each key is the AI_STYLE_<KEY> suffix, lowercased). A
default pattern key with no matching registered rule is simply inert, not
an error -- keeps this module decoupled from the linting package.
"""

from __future__ import annotations

from howlwriter.config.schema import BannedWord, HowlWriterConfig

BUILTIN_BANNED_WORDS: list[BannedWord] = [
    BannedWord(word="delve"),
    BannedWord(word="tapestry"),
    BannedWord(word="crucial"),
]

BUILTIN_BANNED_PATTERNS: list[str] = [
    "not_x_but_y",
    "empty_transition",
    "canned_opening",
    "canned_conclusion",
    "generic_transition",
    "formulaic_contrast",
    "generic_intensifier",
    "corporate_filler",
    "repetitive_tricolon",
    "excessive_em_dash",
    "excessive_headings",
    "excessive_bold",
    "repetitive_paragraph_structure",
    "excessive_rhetorical_questions",
    "repetitive_mini_conclusion",
    "paragraph_length_symmetry",
    "engagement_bait",
    "fake_rhetorical_hook",
    "hashtag_spam",
    "emoji_bullets",
    "motivational_slop",
]


def default_config() -> HowlWriterConfig:
    """Returns a fresh HowlWriterConfig with built-in defaults.

    Returns a new instance each call so callers can freely mutate the
    result without corrupting a shared module-level object.
    """
    return HowlWriterConfig(
        banned_words=list(BUILTIN_BANNED_WORDS),
        banned_patterns=list(BUILTIN_BANNED_PATTERNS),
    )
