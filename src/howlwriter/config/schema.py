"""The HowlWriterConfig schema.

Deliberately limited to the fields the spec actually names (voice,
banned_words, banned_patterns, citation_style, research_depth,
allowed_sources, preferred_sources, fact_checking_strength,
humanization_strength, editing_strength, minimum_source_quality,
provider_preferences, review_requirements) plus one MVP-specific escape
hatch (apply_safe_rewrites) that gates the one rewrite the humanizer is
allowed to perform on its own. Not over-engineered beyond that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.domain.serialization import DataClassSerializationMixin


@dataclass
class BannedWord(DataClassSerializationMixin):
    """A banned word, with an optional safe replacement.

    When replacement is None, the word is findings-only: the linter and
    humanizer report it but never rewrite it. A replacement is what makes a
    substitution "safe" enough for SafeRewriter to apply automatically.
    """

    word: str
    replacement: str | None = None


@dataclass
class HowlWriterConfig(DataClassSerializationMixin):
    voice_profile: str | None = None
    banned_words: list[BannedWord] = field(default_factory=list)
    banned_patterns: list[str] = field(default_factory=list)
    citation_style: str = "apa7"
    research_depth: str = "none"
    allowed_sources: list[str] = field(default_factory=list)
    preferred_sources: list[str] = field(default_factory=list)
    fact_checking_strength: str = "medium"
    humanization_strength: str = "medium"
    editing_strength: str = "medium"
    minimum_source_quality: str = "medium"
    provider_preferences: dict[str, list[str]] = field(default_factory=dict)
    review_requirements: list[str] = field(default_factory=list)
    apply_safe_rewrites: bool = False
