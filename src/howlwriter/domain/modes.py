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
