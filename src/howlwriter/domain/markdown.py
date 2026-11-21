"""Markdown body extraction and assignment word counting."""

from __future__ import annotations

import re

_SHORT_FORM_REFERENCES = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*|\*\*[ \t]*|__[ \t]*)?"
    r"(?:\d+[.)][ \t]*)?"
    r"(?:references?|bibliography|works[ \t]+cited|reference[ \t]+list|citations?)[ \t]*:?"
    r"[ \t]*(?:\*\*|__|#+)?[ \t]*:?[ \t]*(?:\r?\n|$)"
    r"(?:[ \t]*(?:=+|-+)[ \t]*(?:\r?\n|$))?",
    re.IGNORECASE | re.MULTILINE,
)
_SHORT_FORM_TITLE = re.compile(r"^(?:#[ \t]+[^\n]+|[^\n]+\n[ \t]*=+[ \t]*)(?:\n|$)")


def strip_frontmatter(text: str) -> str:
    """Strips YAML/TOML frontmatter from the beginning of markdown text."""
    trimmed = text.strip()
    if trimmed.startswith("---"):
        parts = trimmed.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return trimmed


def extract_body_text(text: str) -> str:
    """Extracts only the body of the academic paper, excluding References section."""
    clean = strip_frontmatter(text)

    # Find where "# References" or "## References" or "### References" or "REFERENCES" starts
    ref_pattern = re.compile(
        r"(?:^|\n)(?:#{1,3}\s*|\*\*\s*)References(?:\s*\*\*)?(?:\s*\n|\Z)",
        re.IGNORECASE,
    )
    match = ref_pattern.search(clean)
    if match:
        return clean[: match.start()].strip()

    return clean.strip()


def split_short_form_document(text: str) -> tuple[str, str]:
    """Separate discussion prose from an initial Markdown title and terminal references."""
    clean = strip_frontmatter(text.replace("\r\n", "\n"))
    match = _SHORT_FORM_REFERENCES.search(clean)
    body, references = (clean[:match.start()], clean[match.end():]) if match else (clean, "")
    return _SHORT_FORM_TITLE.sub("", body, count=1).strip(), references


def count_body_words(text: str, *, short_form: bool = False) -> int:
    """Deterministically counts body words of an academic paper.

    Excludes frontmatter, references and Markdown syntax markers. Short-form
    review also excludes the leading document title.
    """
    body = split_short_form_document(text)[0] if short_form else extract_body_text(text)
    if not body:
        return 0

    # Remove markdown links [text](url) -> text
    # Short-form review also processes untrusted replies. A new opening
    # delimiter bounds a failed match instead of scanning the same tail again.
    link_pattern = r"\[([^\[\]]+)\]\([^()\s]+\)" if short_form else r"\[([^\]]+)\]\([^)]+\)"
    body = re.sub(link_pattern, r"\1", body)

    # Remove code blocks
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"`[^`]+`", "", body)

    # Remove markdown heading symbols (#, ##, etc.)
    body = re.sub(r"^#{1,6}\s+", "", body, flags=re.MULTILINE)

    # Remove bold/italic markers
    body = re.sub(r"[*_]{1,3}", "", body)

    # Tokenize words using standard word boundaries
    tokens = re.findall(r"\b[\w'-]+\b", body)
    return len(tokens)
