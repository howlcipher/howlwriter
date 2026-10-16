"""Making a drafted report read like the person, and measuring whether it does.

Three local, deterministic helpers around the writer model:

* ``compact_voice_block`` keeps the measured description of the voice and
  drops the long application rules, for small local models whose whole
  context is a few thousand tokens.
* ``style_feedback`` measures a drafted passage against the profile's drift
  baseline (the same windows ``howlwriter evaluate`` uses) and turns the
  notable differences into concrete revision instructions.
* ``revision_preserved`` decides whether a voice revision may replace the
  original: every evidence marker, every [MISSING] placeholder, every
  heading, and no new number.

Scores reported at the end come from ``evaluate_text``. A draft revised
toward the profile is no longer an independent sample of the person's
writing, so the scores say how close the draft came, not who wrote it.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

_MARKER = re.compile(r"\[ev-[0-9a-f]+\]")
_MISSING = re.compile(r"\[MISSING:[^\]]*\]")
_HEADING = re.compile(r"^\s*#{1,6}\s.*$", re.MULTILINE)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,:]\d+)*(?![\w])")

COMPACT_RULES = """HOW TO USE THIS VOICE (short form):
- Write the way this author tends to write: match the measured ranges below, including
  their variation, not their averages.
- Mix sentence and paragraph lengths the way the ranges describe; avoid uniform rhythm and
  repeated sentence openings.
- Keep the author's level of formality and hedging; do not upgrade plain words to jargon.
- The voice governs expression only: it never adds or changes facts, numbers, citations, or
  evidence markers."""

_DROP_BLOCKS = ("HOW TO APPLY THIS VOICE", "PRESENCE ACROSS PIECES")


def compact_voice_block(block: str) -> str:
    """The measured part of a rendered voice block, with short rules; unchanged if not recognised."""
    if "GLOBAL TENDENCIES" not in block:
        return block
    kept: list[str] = []
    for chunk in block.split("\n\n"):
        stripped = chunk.lstrip()
        if stripped.startswith(_DROP_BLOCKS) or stripped.startswith("This describes how"):
            continue
        lines = [line for line in chunk.splitlines() if not line.lstrip().startswith("(")]
        if lines:
            kept.append("\n".join(lines))
    return "\n\n".join([kept[0], COMPACT_RULES, *kept[1:]]) if kept else block


def plain_text(markdown: str) -> str:
    """The prose of a draft, for measurement: no markers, placeholders, or headings."""
    text = _MARKER.sub("", markdown)
    text = _MISSING.sub("", text)
    text = _HEADING.sub("", text)
    return re.sub(r"[ \t]+([.,;:])", r"\1", text).strip()


def _evaluate(text: str, voice: str, mode: str) -> dict[str, Any] | None:
    from howlwriter.evaluation.personal import evaluate_text

    try:
        return evaluate_text(plain_text(text), mode=mode, voice=voice)
    except Exception:  # a profile without a baseline must not stop a draft
        return None


def style_feedback(text: str, voice: str, mode: str, *, limit: int = 5, min_words: int = 120) -> list[str]:
    """Concrete differences between this passage and the person's writing, strongest first."""
    if len(plain_text(text).split()) < min_words:
        return []
    report = _evaluate(text, voice, mode)
    findings = ((report or {}).get("drift") or {}).get("findings") or []
    ranked = sorted(
        (f for f in findings if f.get("severity") in ("strong", "notable")),
        key=lambda f: 0 if f.get("severity") == "strong" else 1,
    )
    lines = []
    for finding in ranked:
        line = f"The draft {finding.get('message', '').strip()}"
        if finding.get("suggestion"):
            line += f" {finding['suggestion']}"
        if line not in lines:
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def style_distance(text: str, voice: str, mode: str, *, min_words: int = 120) -> float | None:
    """How far a passage reads from the person's writing: 2 per strong drift finding, 1 per notable.

    None when it cannot be measured (too short, or no baseline). Used to keep a
    voice revision only when it actually moved closer.
    """
    if len(plain_text(text).split()) < min_words:
        return None
    report = _evaluate(text, voice, mode)
    if report is None:
        return None
    findings = (report.get("drift") or {}).get("findings") or []
    return float(sum(2 if f.get("severity") == "strong" else 1 if f.get("severity") == "notable" else 0
                     for f in findings))


def revision_preserved(original: str, revised: str) -> tuple[bool, str]:
    """Whether a voice revision kept every grounded element of the original."""
    if not revised.strip():
        return False, "the revision was empty"
    if Counter(_MARKER.findall(original)) != Counter(_MARKER.findall(revised)):
        return False, "the revision changed the evidence markers"
    if len(_MISSING.findall(original)) != len(_MISSING.findall(revised)):
        return False, "the revision changed the [MISSING] placeholders"
    if len(_HEADING.findall(original)) != len(_HEADING.findall(revised)):
        return False, "the revision changed the section headings"
    added = set(_NUMBER.findall(_MARKER.sub("", revised))) - set(_NUMBER.findall(_MARKER.sub("", original)))
    if added:
        return False, f"the revision introduced numbers not in the original ({', '.join(sorted(added)[:5])})"
    return True, ""


def draft_scores(text: str, voice: str, mode: str) -> dict[str, Any]:
    """Naturalness, Voice Match, and drift for the finished draft, as reported by `evaluate`."""
    report = _evaluate(text, voice, mode)
    if report is None:
        return {"status": "UNAVAILABLE", "reason": "the selected voice could not be evaluated"}
    natural = report.get("naturalness") or {}
    match = report.get("voice_match") or {}
    findings = (report.get("drift") or {}).get("findings") or []
    return {
        "words": report.get("words"),
        "naturalness": {k: natural.get(k) for k in ("status", "score", "reason")},
        "voice_match": {k: match.get(k) for k in ("status", "score", "band", "reason")},
        "drift_findings": {
            "strong": sum(1 for f in findings if f.get("severity") == "strong"),
            "notable": sum(1 for f in findings if f.get("severity") == "notable"),
        },
        "note": (
            "Measured locally against your profile. A draft revised toward the profile is not an "
            "independent sample of your writing: these scores say how close it came, not who wrote it."
        ),
    }
