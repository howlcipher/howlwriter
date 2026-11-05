"""Platform-specific publishing validation and linting rules."""

from __future__ import annotations

import re

from howlwriter.linting.rules import RuleMatch

LINKEDIN_CHAR_LIMIT = "LINKEDIN_CHAR_LIMIT"
LINKEDIN_UNRENDERED_MARKDOWN = "LINKEDIN_UNRENDERED_MARKDOWN"
LINKEDIN_EXCESSIVE_HASHTAGS = "LINKEDIN_EXCESSIVE_HASHTAGS"
LINKEDIN_CONTROL_CHARACTERS = "LINKEDIN_CONTROL_CHARACTERS"
LINKEDIN_HOOK_LENGTH = "LINKEDIN_HOOK_LENGTH"

# Markdown syntax patterns that do not render on LinkedIn
_MARKDOWN_HEADER = re.compile(r"^\s*#{1,6}\s+.+", re.MULTILINE)
_MARKDOWN_BOLD = re.compile(r"\*\*[^*]+\*\*|__[^_]+__")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_MARKDOWN_CODE_BLOCK = re.compile(r"```[a-zA-Z0-9_-]*")
_HASHTAG = re.compile(r"#\w+")
_BAD_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff]")


def check_linkedin_conformance(text: str) -> list[RuleMatch]:
    """Validate text against LinkedIn formatting, length, and rendering constraints."""
    findings: list[RuleMatch] = []

    # 1. Length check (3,000 character maximum)
    char_count = len(text)
    if char_count > 3000:
        findings.append(
            RuleMatch(
                rule_code=LINKEDIN_CHAR_LIMIT,
                matched_text=text[:40] + "...",
                message=(
                    f"Post length ({char_count} characters) exceeds LinkedIn 3,000 character limit "
                    f"by {char_count - 3000} characters."
                ),
                severity="error",
            )
        )

    # 2. Markdown syntax check
    for match in _MARKDOWN_HEADER.finditer(text):
        findings.append(
            RuleMatch(
                rule_code=LINKEDIN_UNRENDERED_MARKDOWN,
                matched_text=match.group(0),
                message="Markdown header syntax ('# Header') will appear as literal characters on LinkedIn.",
                severity="warning",
            )
        )

    for match in _MARKDOWN_BOLD.finditer(text):
        findings.append(
            RuleMatch(
                rule_code=LINKEDIN_UNRENDERED_MARKDOWN,
                matched_text=match.group(0),
                message="Markdown bold syntax ('**bold**') will not render as bold text on LinkedIn.",
                severity="warning",
            )
        )

    for match in _MARKDOWN_LINK.finditer(text):
        findings.append(
            RuleMatch(
                rule_code=LINKEDIN_UNRENDERED_MARKDOWN,
                matched_text=match.group(0),
                message="Markdown link syntax ('[text](url)') will appear as raw literal markup on LinkedIn.",
                severity="warning",
            )
        )

    for match in _MARKDOWN_CODE_BLOCK.finditer(text):
        findings.append(
            RuleMatch(
                rule_code=LINKEDIN_UNRENDERED_MARKDOWN,
                matched_text=match.group(0),
                message="Markdown code fences ('```') will not render code boxes on LinkedIn.",
                severity="warning",
            )
        )

    # 3. Excessive hashtags
    hashtags = _HASHTAG.findall(text)
    if len(hashtags) > 5:
        findings.append(
            RuleMatch(
                rule_code=LINKEDIN_EXCESSIVE_HASHTAGS,
                matched_text=" ".join(hashtags),
                message=(
                    f"Found {len(hashtags)} hashtags. More than 5 hashtags degrades reach and readability "
                    "on LinkedIn."
                ),
                severity="warning",
            )
        )

    # 4. Problematic control characters
    bad_chars = _BAD_CONTROL_CHARS.findall(text)
    if bad_chars:
        findings.append(
            RuleMatch(
                rule_code=LINKEDIN_CONTROL_CHARACTERS,
                matched_text=f"{len(bad_chars)} invalid control characters",
                message="Text contains invalid control characters or byte markers that corrupt copy-pasting.",
                severity="error",
            )
        )

    # 5. Hook length check (first paragraph before 'see more')
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if paragraphs:
        first_para = paragraphs[0]
        if len(first_para) > 350:
            findings.append(
                RuleMatch(
                    rule_code=LINKEDIN_HOOK_LENGTH,
                    matched_text=first_para[:60] + "...",
                    message=(
                        f"Opening hook paragraph is {len(first_para)} characters. LinkedIn mobile truncates "
                        "at ~210 characters ('see more'); consider an earlier line break for visual impact."
                    ),
                    paragraph_index=0,
                    severity="info",
                )
            )

    return findings


def check_platform_rules(text: str, platform: str) -> list[RuleMatch]:
    """Check text conformance against the requested target platform."""
    plat = platform.strip().lower()
    if plat == "linkedin":
        return check_linkedin_conformance(text)
    return []
