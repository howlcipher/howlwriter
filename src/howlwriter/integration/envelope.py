"""The draft inside a writer reply, even when the reply's YAML does not parse.

Writer prompts ask for a fenced YAML block whose ``body_markdown`` holds the
draft. HowlPlane parses it into ``structured_output``. A small model often
indents only the first line of the block scalar, so the YAML fails, the
structured output is empty, and the raw reply (fence, keys and claim lists)
used to become the draft. This module recovers the body, and the other keys
when they parse on their own, from such a reply.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

#: Top-level keys that may follow ``body_markdown`` in a writer reply.
_ENVELOPE_KEYS = ("claims_made", "added_claims", "gaps", "word_count_estimate", "warnings")
_BODY_KEY = re.compile(r"^body_markdown:\s*[|>]?[-+]?\s*$", re.MULTILINE)
#: The opening fence of the reply's YAML block.
_OPENING_FENCE = re.compile(r"^```(?:ya?ml)?[ \t]*$", re.MULTILINE)
_NEXT_KEY = re.compile(r"^(?:%s)\s*:" % "|".join(_ENVELOPE_KEYS), re.MULTILINE)


def unfenced(text: str) -> str:
    """Model output without a wrapping ``` fence (small models often add one)."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text[: text.rfind("```")]
    return text.strip()


def _fenced_block(text: str) -> str:
    """From the opening fence to the last closing one: the body may hold fences of its own."""
    opening = _OPENING_FENCE.search(text)
    if opening is None:
        return text
    inner = text[opening.end():]
    closing = inner.rfind("\n```")
    return inner[:closing] if closing >= 0 else inner


def _outdent(lines: list[str]) -> str:
    """Remove the first line's indentation from every line that has at least that much."""
    first = next((line for line in lines if line.strip()), "")
    indent = len(first) - len(first.lstrip(" "))
    prefix = " " * indent
    return "\n".join(line[indent:] if line.startswith(prefix) else line.lstrip(" ") for line in lines).strip()


def salvage(raw: str) -> dict[str, Any]:
    """``body_markdown`` and any other parseable keys from a reply whose YAML failed.

    Returns ``{}`` when the reply has no ``body_markdown`` key, so the caller
    keeps its own fallback for a reply that is plain prose.
    """
    text = _fenced_block(raw or "")
    body_key = _BODY_KEY.search(text)
    if body_key is None:
        return {}
    rest = text[body_key.end():]
    next_key = _NEXT_KEY.search(rest)
    body_text = rest[: next_key.start()] if next_key else rest
    recovered: dict[str, Any] = {"body_markdown": _outdent(body_text.strip("\n").splitlines())}
    if next_key:
        try:
            tail = yaml.safe_load(rest[next_key.start():])
        except yaml.YAMLError:
            tail = None
        if isinstance(tail, dict):
            recovered.update({k: v for k, v in tail.items() if k in _ENVELOPE_KEYS})
    return recovered


def writer_envelope(result: Any) -> dict[str, Any]:
    """The structured writer reply: parsed by HowlPlane, else salvaged, else the raw text as the body."""
    structured = getattr(result, "structured_output", None) or {}
    body = structured.get("body_markdown")
    if isinstance(body, str) and body.strip():
        return structured
    raw = getattr(result, "raw_output", None) or ""
    return salvage(raw) or {"body_markdown": unfenced(raw)}
