"""Sentence splitting that does not break at citation locators and common abbreviations."""

from __future__ import annotations

import re

_PROTECTED = re.compile(
    r"\b(?:pp?|ch|chs|fig|figs|no|nos|vol|vols|ed|eds|sec|secs|cf|vs|approx|dept|inc|corp|st|dr|mr|ms|mrs|prof)\.(?=\s)"
    r"|\bet al\.(?=\s)|\be\.g\.(?=\s)|\bi\.e\.(?=\s)|\bU\.S\.(?=\s)",
    re.IGNORECASE)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_MARK = "\u0001"


def split_sentences(text: str) -> list[str]:
    """Sentences of `text`, keeping "(Smith, 2022, p. 5)" and "et al." inside their sentence."""
    protected = _PROTECTED.sub(lambda m: m.group(0)[:-1] + _MARK, re.sub(r"\s+", " ", text))
    return [part.replace(_MARK, ".").strip() for part in _SPLIT.split(protected) if part.strip()]
