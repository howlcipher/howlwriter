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
    section_type: str = "body"


_REFERENCES_HEADING = re.compile(
    r"^(?:#{1,6}\s*)?(?:references|bibliography|works cited)\s*$", re.IGNORECASE
)
_PROVENANCE_HEADING = re.compile(
    r"^(?:#{1,6}\s*)?(?:appendix:\s*generation provenance|generation provenance|provenance appendix)\s*$",
    re.IGNORECASE,
)
_MANIFEST_HEADING = re.compile(
    r"^(?:---\s*manifest\s*---|generation manifest)\s*$", re.IGNORECASE
)
_GENERIC_HEADING = re.compile(r"^#{1,6}\s+\S+", re.MULTILINE)


@dataclass
class Document(DataClassSerializationMixin):
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    mode: WritingMode = WritingMode.CUSTOM
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(p.raw_text for p in self.paragraphs)

    @property
    def body_text(self) -> str:
        return "\n\n".join(p.raw_text for p in self.body_paragraphs())

    def sentence(self, paragraph_index: int, sentence_index: int) -> Sentence:
        return self.paragraphs[paragraph_index].sentences[sentence_index]

    def all_sentences(self) -> list[tuple[int, int, Sentence]]:
        """Every sentence, tagged with (paragraph_index, sentence_index)."""
        return [
            (p.index, s.index, s)
            for p in self.paragraphs
            for s in p.sentences
        ]

    def body_paragraphs(self) -> list[Paragraph]:
        """Paragraphs in the document body, excluding references, appendices, manifests, etc."""
        return [p for p in self.paragraphs if p.section_type == "body"]

    def body_sentences(self) -> list[tuple[int, int, Sentence]]:
        """Sentences in body paragraphs only."""
        return [
            (p.index, s.index, s)
            for p in self.paragraphs
            if p.section_type == "body"
            for s in p.sentences
        ]

    @classmethod
    def parse(cls, text: str, *, title: str = "", mode: WritingMode = WritingMode.CUSTOM) -> "Document":
        """Splits plain text or Markdown into paragraphs and sentences,
        classifying each paragraph into its document section (body, references, provenance, manifest).
        """
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
        paragraphs: list[Paragraph] = []
        current_section = "body"

        for p_index, raw in enumerate(raw_paragraphs):
            first_line = raw.split("\n")[0].strip()
            if _REFERENCES_HEADING.match(first_line):
                current_section = "references"
            elif _PROVENANCE_HEADING.match(first_line):
                current_section = "provenance"
            elif _MANIFEST_HEADING.match(first_line):
                current_section = "manifest"
            elif _GENERIC_HEADING.match(first_line) and current_section != "body":
                # Check if this heading indicates an appendix or non-body section
                if re.match(r"^#{1,6}\s+appendix\b", first_line, re.IGNORECASE):
                    current_section = "provenance"
                else:
                    # Return to body if another regular section begins
                    current_section = "body"

            sentences: list[Sentence] = []
            cursor = 0
            for s_index, chunk in enumerate(_split_sentences(raw)):
                start = raw.index(chunk, cursor)
                end = start + len(chunk)
                cursor = end
                sentences.append(Sentence(index=s_index, text=chunk, char_start=start, char_end=end))
            paragraphs.append(
                Paragraph(
                    index=p_index,
                    raw_text=raw,
                    sentences=sentences,
                    section_type=current_section,
                )
            )
        return cls(title=title, paragraphs=paragraphs, mode=mode)


def _split_sentences(paragraph_text: str) -> list[str]:
    pieces = _SENTENCE_BOUNDARY.split(paragraph_text)
    return [piece.strip() for piece in pieces if piece.strip()]
