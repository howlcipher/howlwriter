"""Meaning preservation: comparing ORIGINAL INTENT vs FINAL OUTPUT.

MeaningPreservationReviewer.compare() is a deterministic heuristic diff --
numbers, attribution phrases, and hedge words between before/after --
never a hardcoded PASS. It returns PASS only when nothing of substance
changed, and FLAGGED (with itemized diffs) otherwise; it never returns a
hard FAIL on its own, since a heuristic can raise a concern but shouldn't
unilaterally reject a rewrite -- that call belongs to a human or, later,
ModelMeaningReviewer, the reserved model-backed hook for real semantic
comparison.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal, Protocol

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole

Status = Literal["PASS", "FLAGGED"]

_NUMBER = re.compile(r"\b\d[\d,.]*\b")
_ATTRIBUTION_MARKERS = ("according to", "study by", "reports that", "found that")
_HEDGE_WORDS = ("may", "might", "could", "suggests", "appears", "likely", "possibly", "perhaps", "reportedly")
_WORD = re.compile(r"[A-Za-z']+")
_SENTENCE_COUNT_RATIO_THRESHOLD = 0.2
_SENTENCE_COUNT_MIN_DELTA = 2


@dataclass
class MeaningDiff(DataClassSerializationMixin):
    kind: str
    description: str


@dataclass
class MeaningPreservationResult(DataClassSerializationMixin):
    status: Status = "PASS"
    diffs: list[MeaningDiff] = field(default_factory=list)


def _count_markers(text: str, markers: tuple[str, ...]) -> Counter:
    lowered = text.lower()
    return Counter({marker: lowered.count(marker) for marker in markers if lowered.count(marker)})


def _count_words(text: str, words: tuple[str, ...]) -> Counter:
    tokens = [t.lower() for t in _WORD.findall(text)]
    token_counts = Counter(tokens)
    return Counter({word: token_counts[word] for word in words if token_counts[word]})


class MeaningPreservationReviewer:
    def compare(self, original: Document, revised: Document) -> MeaningPreservationResult:
        diffs: list[MeaningDiff] = []
        diffs.extend(self._number_diffs(original.text, revised.text))
        diffs.extend(self._attribution_diffs(original.text, revised.text))
        diffs.extend(self._hedge_diffs(original.text, revised.text))
        diffs.extend(self._sentence_count_diff(original, revised))

        status: Status = "FLAGGED" if diffs else "PASS"
        return MeaningPreservationResult(status=status, diffs=diffs)

    @staticmethod
    def _number_diffs(original_text: str, revised_text: str) -> list[MeaningDiff]:
        original_counts = Counter(_NUMBER.findall(original_text))
        revised_counts = Counter(_NUMBER.findall(revised_text))
        removed = original_counts - revised_counts
        added = revised_counts - original_counts

        diffs = []
        for number in removed:
            diffs.append(
                MeaningDiff(
                    "number_removed",
                    f'"{number}" appeared {original_counts[number]}x in the original '
                    f"vs {revised_counts[number]}x in the revision.",
                )
            )
        for number in added:
            diffs.append(
                MeaningDiff(
                    "number_added",
                    f'"{number}" appears {revised_counts[number]}x in the revision '
                    f"vs {original_counts[number]}x in the original.",
                )
            )
        return diffs

    @staticmethod
    def _attribution_diffs(original_text: str, revised_text: str) -> list[MeaningDiff]:
        original_counts = _count_markers(original_text, _ATTRIBUTION_MARKERS)
        revised_counts = _count_markers(revised_text, _ATTRIBUTION_MARKERS)
        removed = original_counts - revised_counts
        return [
            MeaningDiff("attribution_removed", f'Attribution phrase "{marker}" was dropped.')
            for marker in removed
        ]

    @staticmethod
    def _hedge_diffs(original_text: str, revised_text: str) -> list[MeaningDiff]:
        original_counts = _count_words(original_text, _HEDGE_WORDS)
        revised_counts = _count_words(revised_text, _HEDGE_WORDS)
        removed = original_counts - revised_counts
        added = revised_counts - original_counts

        diffs = []
        for word in removed:
            message = f'Hedge word "{word}" was dropped -- claim may be stronger.'
            diffs.append(MeaningDiff("hedge_removed", message))
        for word in added:
            message = f'Hedge word "{word}" was added -- claim may be weaker.'
            diffs.append(MeaningDiff("hedge_added", message))
        return diffs

    @staticmethod
    def _sentence_count_diff(original: Document, revised: Document) -> list[MeaningDiff]:
        original_count = len(original.all_sentences())
        revised_count = len(revised.all_sentences())
        delta = abs(original_count - revised_count)
        if original_count == 0 or delta < _SENTENCE_COUNT_MIN_DELTA:
            return []
        if delta / original_count < _SENTENCE_COUNT_RATIO_THRESHOLD:
            return []
        return [
            MeaningDiff(
                "sentence_count_changed",
                f"Sentence count changed from {original_count} to {revised_count}.",
            )
        ]


class ModelMeaningReviewer(Protocol):
    """Reserved hook for real semantic comparison. Unconfigured by default."""

    role: WritingRole

    def compare(self, original: Document, revised: Document) -> MeaningPreservationResult: ...


class NotConfiguredMeaningReviewer(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.FINAL_REVIEWER)

    def compare(self, original: Document, revised: Document) -> MeaningPreservationResult:
        return self.run(original, revised)
