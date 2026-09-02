"""Writing modes: named behavior profiles, not separate applications."""

from __future__ import annotations

import enum


class WritingMode(enum.Enum):
    CASUAL = "casual"
    PROFESSIONAL = "professional"
    LINKEDIN = "linkedin"
    TECHNICAL = "technical"
    DOCUMENTATION = "documentation"
    ACADEMIC = "academic"
    EMAIL = "email"
    ARTICLE = "article"
    CUSTOM = "custom"


def parse_mode(value: str | WritingMode | None) -> WritingMode:
    """Resolve a writing-mode name (case-insensitive) to a WritingMode enum.

    Returns CUSTOM for None or unknown values so callers never crash on
    user-supplied mode strings.
    """
    if isinstance(value, WritingMode):
        return value
    if not value:
        return WritingMode.CUSTOM
    normalized = str(value).strip().lower()
    try:
        return WritingMode(normalized)
    except ValueError:
        return WritingMode.CUSTOM
