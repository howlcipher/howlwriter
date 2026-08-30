"""Span-addressable text model.

Documents are split into paragraphs and sentences so that lint findings, red
pen critique, and evidence can point at an exact location ("paragraph 4,
sentence 2") instead of an opaque string offset.

The splitter is deliberately simple: blank-line paragraph breaks and a regex
sentence boundary. It does not handle abbreviations ("Dr.", "e.g.") or
decimal numbers ("3.14") correctly in all cases -- those can be split as
false sentence boundaries. This is a known, documented limitation for v1
(see docs/architecture.md); pulling in a full NLP sentence tokenizer is not
worth the dependency weight for the MVP's deterministic subsystems.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from howlwriter.domain.modes import WritingMode
from howlwriter.domain.serialization import DataClassSerializationMixin

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@dataclass
class Sentence(DataClassSerializationMixin):
    index: int
    text: str
    char_start: int
    char_end: int


@dataclass
class Paragraph(DataClassSerializationMixin):
    index: int
    raw_text: str
    sentences: list[Sentence] = field(default_factory=list)


@dataclass
class Document(DataClassSerializationMixin):
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    mode: WritingMode = WritingMode.CUSTOM
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(p.raw_text for p in self.paragraphs)

    def sentence(self, paragraph_index: int, sentence_index: int) -> Sentence:
        return self.paragraphs[paragraph_index].sentences[sentence_index]

    def all_sentences(self) -> list[tuple[int, int, Sentence]]:
        """Every sentence, tagged with (paragraph_index, sentence_index)."""
        return [
            (p.index, s.index, s)
            for p in self.paragraphs
            for s in p.sentences
        ]

    @classmethod
    def parse(cls, text: str, *, title: str = "", mode: WritingMode = WritingMode.CUSTOM) -> "Document":
        """Splits plain text or Markdown into paragraphs and sentences.

        Paragraph boundaries are blank lines. Sentence boundaries are a
        regex heuristic (see module docstring for known limitations).
        """
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
        paragraphs: list[Paragraph] = []
        for p_index, raw in enumerate(raw_paragraphs):
            sentences: list[Sentence] = []
            cursor = 0
            for s_index, chunk in enumerate(_split_sentences(raw)):
                start = raw.index(chunk, cursor)
                end = start + len(chunk)
                cursor = end
                sentences.append(Sentence(index=s_index, text=chunk, char_start=start, char_end=end))
            paragraphs.append(Paragraph(index=p_index, raw_text=raw, sentences=sentences))
        return cls(title=title, paragraphs=paragraphs, mode=mode)


def _split_sentences(paragraph_text: str) -> list[str]:
    pieces = _SENTENCE_BOUNDARY.split(paragraph_text)
    return [piece.strip() for piece in pieces if piece.strip()]
