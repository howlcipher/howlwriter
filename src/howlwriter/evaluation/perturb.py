"""Deterministic mechanical perturbations, for validating Naturalness.

A score that claims to notice mechanical prose has to be shown noticing it.
These functions take a real document and make it mechanical in one known
way, so the calibration can report how well the score separates the
original from the damaged copy. They are a sensitivity test, not a model of
AI writing, and are reported under that name: "synthetic mechanical
controls", never "AI-generated text".

Everything is a pure function of the input text. Perturbed text exists only
in memory for the length of one measurement and is never written anywhere.
"""

from __future__ import annotations

import re

from howlwriter.domain.document import Document

_CONNECTIVES = ("Moreover, ", "Furthermore, ", "Additionally, ", "Consequently, ")
_CLOSER = "Overall, this highlights the importance of a comprehensive approach."
_HEADING = re.compile(r"^\s*#{1,6}\s+")


def _sentences(text: str) -> list[list[str]]:
    document = Document.parse(text)
    return [
        [s.text.strip() for s in p.sentences if s.text.strip()]
        for p in document.body_paragraphs()
        if not _HEADING.match(p.raw_text)
    ]


def _lower_first(sentence: str) -> str:
    if len(sentence) > 1 and sentence[0].isupper() and not sentence[1].isupper():
        return sentence[0].lower() + sentence[1:]
    return sentence


def formulaic_injection(text: str) -> str:
    """Stock connectives on alternate sentences and a recap closing each paragraph."""
    paragraphs = []
    counter = 0
    for sentences in _sentences(text):
        rewritten = []
        for position, sentence in enumerate(sentences):
            if position % 2 == 1:
                sentence = _CONNECTIVES[counter % len(_CONNECTIVES)] + _lower_first(sentence)
                counter += 1
            rewritten.append(sentence)
        if len(rewritten) >= 2:
            rewritten.append(_CLOSER)
        if rewritten:
            paragraphs.append(" ".join(rewritten))
    return "\n\n".join(paragraphs)


def uniform_paragraphs(text: str, size: int = 4) -> str:
    """Every sentence kept, re-chunked into paragraphs of exactly `size`."""
    flat = [s for paragraph in _sentences(text) for s in paragraph]
    chunks = [flat[i:i + size] for i in range(0, len(flat), size)]
    return "\n\n".join(" ".join(chunk) for chunk in chunks if chunk)


def sentence_duplication(text: str, every: int = 4) -> str:
    """Restate every `every`-th sentence at the end of the following paragraph."""
    paragraphs = _sentences(text)
    carried: list[str] = []
    out = []
    counter = 0
    for sentences in paragraphs:
        current = list(sentences) + [f"In other words, {_lower_first(s)}" for s in carried]
        carried = []
        for sentence in sentences:
            counter += 1
            if counter % every == 0:
                carried.append(sentence)
        if current:
            out.append(" ".join(current))
    return "\n\n".join(out)


def combined(text: str) -> str:
    """All three at once: the strongest control."""
    return sentence_duplication(uniform_paragraphs(formulaic_injection(text)))


PERTURBATIONS = {
    "formulaic_injection": formulaic_injection,
    "uniform_paragraphs": uniform_paragraphs,
    "sentence_duplication": sentence_duplication,
    "combined": combined,
}
