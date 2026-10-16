"""Span-addressable text model.

Documents are split into paragraphs and sentences so that lint findings, red
pen critique, and evidence can point at an exact location ("paragraph 4,
sentence 2") instead of an opaque string offset.

The splitter is deliberately simple: blank-line paragraph breaks and a regex
sentence boundary, followed by a narrow merge for dotted initialisms and
common abbreviations. It is not a full NLP sentence tokenizer, but it avoids
turning forms such as "U.S." and "e.g." into fragment claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from howlwriter.domain.modes import WritingMode
from howlwriter.domain.serialization import DataClassSerializationMixin

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

# A period that ends a dotted initialism ("U.S.", "D.C.") or a common
# abbreviation is not a sentence boundary. Without this, "the U.S. Government"
# split into two sentences, and the claim extractor then reported the
# fragment "Government Accountability Office, 2020)." as an unsupported claim.
_ABBREVIATION_END = re.compile(
    r"(?:(?:^|\s|\()(?:[A-Za-z]\.){2,}"
    r"|\b(?:e\.g|i\.e|cf|vs|etc|Dr|Mr|Mrs|Ms|Prof|No|Nos|Fig|Vol|St|Inc|Ltd|Co"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.)$"
)


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
            for s_index, (start, end) in enumerate(_sentence_spans(raw)):
                sentences.append(
                    Sentence(index=s_index, text=raw[start:end], char_start=start, char_end=end)
                )
            paragraphs.append(
                Paragraph(
                    index=p_index,
                    raw_text=raw,
                    sentences=sentences,
                    section_type=current_section,
                )
            )
        return cls(title=title, paragraphs=paragraphs, mode=mode)


def _sentence_spans(paragraph_text: str) -> list[tuple[int, int]]:
    """Character spans of each sentence in `paragraph_text`.

    Pieces split after an abbreviation are re-joined by extending the span,
    so a merged sentence keeps the original whitespace between its parts.
    Joining the stripped pieces with a single space instead produced text
    that was not a substring of the paragraph whenever the original break
    was a newline or a run of spaces ("U.S.\nGovernment"), and the offset
    lookup that followed raised for the whole document.
    """
    raw_spans: list[tuple[int, int]] = []
    position = 0
    for match in _SENTENCE_BOUNDARY.finditer(paragraph_text):
        raw_spans.append((position, match.start()))
        position = match.end()
    raw_spans.append((position, len(paragraph_text)))

    stripped: list[tuple[int, int]] = []
    for start, end in raw_spans:
        segment = paragraph_text[start:end]
        if not segment.strip():
            continue
        leading = len(segment) - len(segment.lstrip())
        stripped.append((start + leading, start + len(segment.rstrip())))

    merged: list[tuple[int, int]] = []
    for start, end in stripped:
        if merged and _ABBREVIATION_END.search(paragraph_text[merged[-1][0]:merged[-1][1]]):
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _split_sentences(paragraph_text: str) -> list[str]:
    return [paragraph_text[start:end] for start, end in _sentence_spans(paragraph_text)]
