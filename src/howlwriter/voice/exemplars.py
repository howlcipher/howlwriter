"""Style examples: short passages the person actually wrote, shown to a model as a pattern.

A description of a voice ("sentences typically 9-29 words, rare semicolons")
tells a model what to aim for; a few real paragraphs show it. The bank is
built with the profile from the same attested, selection-filtered training
text (never holdout documents, never Workshop bundles, never unattested
paragraphs), stored privately beside the profile, and read only when a
draft is written.

The passages are private writing. Callers decide whether they may leave the
machine; ``howlwriter.projects.writing`` sends them to local models by
default and to remote models only on an explicit request.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

EXEMPLARS_FILE = "exemplars.json"
VERSION = 1
MIN_WORDS = 40
MAX_WORDS = 200
PER_DOCUMENT = 25
MAX_PARAGRAPHS = 600

_LIST_OR_HEADING = re.compile(r"^\s*(?:[-*•#>]|\d+[.)]\s|[A-Z][A-Z0-9 ]{3,}:?$)")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]+")
_STOP = frozenset(
    "the a an and or but of to in on for with by at from as is are was were be been being it this that "
    "these those which who what when where why how not no can could should would will may might must "
    "do does did has have had i you we they he she its their our your my his her them us than then so "
    "if into about over under between also more most such each other any all some very just only".split()
)


def _is_prose(paragraph: str) -> bool:
    words = paragraph.split()
    if not MIN_WORDS <= len(words) <= MAX_WORDS:
        return False
    if _LIST_OR_HEADING.match(paragraph) or "|" in paragraph or "http" in paragraph:
        return False
    if paragraph.rstrip()[-1:] not in ".?!\"”)’'":
        return False
    letters = sum(c.isalpha() for c in paragraph)
    return letters / max(len(paragraph), 1) > 0.7 and paragraph.count(".") >= 2


def build_bank(documents: Iterable[tuple[str, str, float, str]]) -> dict:
    """documents: (key, cleaned text, weight, authorship) for training documents only."""
    paragraphs: list[dict] = []
    for key, text, weight, authorship in documents:
        doc = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        kept = 0
        for paragraph in (p.strip() for p in text.split("\n\n")):
            if kept >= PER_DOCUMENT or not _is_prose(paragraph):
                continue
            paragraphs.append(
                {
                    "doc": doc,
                    "weight": weight,
                    "authorship": authorship,
                    "words": len(paragraph.split()),
                    "text": " ".join(paragraph.split()),
                }
            )
            kept += 1
    # Fully attested writing first, so the cap never drops it for half-weight text.
    paragraphs.sort(key=lambda p: (-p["weight"], p["doc"]))
    return {"version": VERSION, "paragraphs": paragraphs[:MAX_PARAGRAPHS]}


def load_bank(voice_directory: Path | str | None) -> list[dict]:
    if not voice_directory:
        return []
    path = Path(voice_directory) / EXEMPLARS_FILE
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("paragraphs", []))
    except (OSError, ValueError):
        return []


def _terms(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and len(w) > 2}


def choose(bank: list[dict], query: str, *, max_chars: int, limit: int = 3) -> list[str]:
    """A few passages for this section: related wording first, one per document, fully attested first."""
    if not bank or max_chars <= 0:
        return []
    wanted = _terms(query)

    def score(item: dict) -> tuple:
        overlap = len(wanted & _terms(item["text"])) if wanted else 0
        return (item["weight"] >= 1.0, overlap, -abs(item["words"] - 110))

    chosen: list[str] = []
    used_docs: set[str] = set()
    total = 0
    for item in sorted(bank, key=score, reverse=True):
        if item["doc"] in used_docs or total + len(item["text"]) > max_chars:
            continue
        chosen.append(item["text"])
        used_docs.add(item["doc"])
        total += len(item["text"])
        if len(chosen) >= limit:
            break
    return chosen


def render(examples: list[str]) -> str:
    if not examples:
        return ""
    lines = [
        "These are passages the author wrote. Imitate HOW they are written: sentence length and rhythm, "
        "how paragraphs open and close, word choice, how claims are qualified. Never copy their content, "
        "facts, numbers, names, or phrases.",
    ]
    for number, text in enumerate(examples, start=1):
        lines += ["", f"Example {number}:", text]
    return "\n".join(lines)
