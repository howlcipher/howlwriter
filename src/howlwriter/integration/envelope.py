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
    """Remove the block scalar's indentation, or only the first line's when the rest is unindented.

    A well-formed block scalar indents every line, so the prefix comes off all of them. In the
    broken shape only the first line is indented; the other lines (nested lists, code) are left
    exactly as written.
    """
    first_idx = next((i for i, line in enumerate(lines) if line.strip()), 0)
    first = lines[first_idx] if lines else ""
    indent = len(first) - len(first.lstrip(" "))
    prefix = " " * indent
    if indent and all(line.startswith(prefix) for line in lines if line.strip()):
        return "\n".join(line[indent:] for line in lines).strip()
    return "\n".join(line.lstrip(" ") if i == first_idx else line for i, line in enumerate(lines)).strip()


_STRUCTURAL_LINE = re.compile(r"^(?:\s+\S|\s*-\s|[A-Za-z_]\w*\s*:|\s*$)")


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
    # A key line only ends the body when everything from there on is an envelope mapping.
    body_text, tail = rest, None
    for candidate in _NEXT_KEY.finditer(rest):
        try:
            parsed = yaml.safe_load(rest[candidate.start():])
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and parsed and all(k in _ENVELOPE_KEYS for k in parsed):
            body_text, tail = rest[: candidate.start()], parsed
            break
    if tail is None:
        # Nothing parsed as a whole. Still end the body at the first key line when everything
        # after it at least looks like YAML (so a broken tail does not leak into the draft).
        for candidate in _NEXT_KEY.finditer(rest):
            if all(_STRUCTURAL_LINE.match(ln) for ln in rest[candidate.start():].splitlines()):
                body_text = rest[: candidate.start()]
                break
    recovered: dict[str, Any] = {"body_markdown": _outdent(body_text.strip("\n").splitlines())}
    if tail:
        recovered.update(tail)
    return recovered


def writer_envelope(result: Any) -> dict[str, Any]:
    """The structured writer reply: parsed by HowlPlane, else salvaged, else the raw text as the body."""
    structured = getattr(result, "structured_output", None) or {}
    body = structured.get("body_markdown")
    if isinstance(body, str) and body.strip():
        return structured
    raw = getattr(result, "raw_output", None) or ""
    return salvage(raw) or {"body_markdown": unfenced(raw)}
