"""Redundancy-aware compression signals: table-restatement and near-duplicate
paragraph detection.

Deliberately generic (operates on a Document only, no AssignmentSpec) so the
general howl pipeline can reuse it later. Follows the codebase's established
pattern of locally duplicating small content-word-set helpers (see
review/meaning.py's private _content_word_set) rather than introducing a new
shared-utilities module for a handful of lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin

_CONTENT_WORD_RE = re.compile(r"\b\w{4,}\b")
_STOP_WORDS = frozenset({
    "this", "that", "these", "those", "with", "from", "into", "onto",
    "such", "than", "then", "when", "where", "which", "while", "will",
    "would", "could", "should", "have", "does", "some", "each", "also",
    "only", "more", "most", "over", "under", "both", "their", "there",
})
_MIN_WORDS_FOR_DUPLICATE_CHECK = 20
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$", re.MULTILINE)


@dataclass
class RedundancyFinding(DataClassSerializationMixin):
    kind: str  # "table_restatement" | "near_duplicate_paragraph"
    paragraph_index: int
    related_paragraph_index: int | None
    overlap_ratio: float
    description: str


@dataclass
class RedundancyResult(DataClassSerializationMixin):
    findings: list[RedundancyFinding] = field(default_factory=list)


def _content_word_set(text: str) -> set[str]:
    return {w for w in _CONTENT_WORD_RE.findall(text.lower()) if w not in _STOP_WORDS}


def _is_markdown_table(raw_text: str) -> bool:
    return "|" in raw_text and bool(_TABLE_SEPARATOR_RE.search(raw_text))


def _is_heading_only(raw_text: str) -> bool:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return len(lines) == 1 and lines[0].startswith("#")


def detect_redundancy(
    document: Document,
    near_duplicate_threshold: float = 0.75,
    table_restatement_threshold: float = 0.6,
) -> RedundancyResult:
    """Detects two redundancy patterns that indicate rubric evidence is being
    restated rather than newly elaborated:

    (i) a paragraph immediately following a markdown table whose content
        substantially restates the table's own cell contents, and
    (ii) near-duplicate paragraphs anywhere in the document (by content-word
         Jaccard overlap), which often indicates the same point being made
         once in prose and again elsewhere rather than compressed once.
    """
    findings: list[RedundancyFinding] = []
    paragraphs = document.paragraphs

    word_sets: dict[int, set[str]] = {}
    for p in paragraphs:
        if _is_heading_only(p.raw_text):
            continue
        word_sets[p.index] = _content_word_set(p.raw_text)

    # (i) table-restatement: a table followed immediately by a paragraph that
    # substantially overlaps the table's own content words.
    for i, p in enumerate(paragraphs):
        if not _is_markdown_table(p.raw_text):
            continue
        if i + 1 >= len(paragraphs):
            continue
        following = paragraphs[i + 1]
        if _is_markdown_table(following.raw_text) or _is_heading_only(following.raw_text):
            continue
        table_words = _content_word_set(p.raw_text)
        following_words = word_sets.get(following.index, set())
        if not table_words or not following_words:
            continue
        overlap = len(table_words & following_words) / len(following_words)
        if overlap >= table_restatement_threshold:
            findings.append(
                RedundancyFinding(
                    kind="table_restatement",
                    paragraph_index=following.index,
                    related_paragraph_index=p.index,
                    overlap_ratio=round(overlap, 3),
                    description=(
                        f"Paragraph {following.index} substantially restates the content "
                        f"of the preceding table (paragraph {p.index})."
                    ),
                )
            )

    # (ii) near-duplicate paragraphs anywhere in the document.
    indices = [
        idx for idx, words in word_sets.items()
        if len(words) >= _MIN_WORDS_FOR_DUPLICATE_CHECK
    ]
    seen_pairs: set[tuple[int, int]] = set()
    for a_pos in range(len(indices)):
        for b_pos in range(a_pos + 1, len(indices)):
            a_idx, b_idx = indices[a_pos], indices[b_pos]
            a_words, b_words = word_sets[a_idx], word_sets[b_idx]
            union = a_words | b_words
            if not union:
                continue
            overlap = len(a_words & b_words) / len(union)
            if overlap >= near_duplicate_threshold and (a_idx, b_idx) not in seen_pairs:
                seen_pairs.add((a_idx, b_idx))
                findings.append(
                    RedundancyFinding(
                        kind="near_duplicate_paragraph",
                        paragraph_index=b_idx,
                        related_paragraph_index=a_idx,
                        overlap_ratio=round(overlap, 3),
                        description=(
                            f"Paragraph {b_idx} substantially restates paragraph {a_idx}."
                        ),
                    )
                )

    return RedundancyResult(findings=findings)
