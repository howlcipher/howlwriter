"""Deterministic corpus-statistics voice learning.

Computes real, stdlib-only statistics from a corpus of an author's own
writing: sentence length mean/stdev, paragraph length (in sentences),
contraction rate, rhetorical-question rate, and an approximate fragment
rate. No model call, no network access. This is the complete real MVP
voice capability -- see voice/model_hook.py for the reserved (unconfigured)
hook for qualitative model-backed analysis.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from howlwriter.domain.document import Document, Sentence
from howlwriter.domain.voice import VoiceExample, VoiceProfile

_CONTRACTION = re.compile(r"\w+(n't|'re|'ll|'ve|'d|'m)\b", re.IGNORECASE)
_COMMON_VERBS = re.compile(
    r"\b(is|are|was|were|am|be|been|being|has|have|had|do|does|did|will|would|"
    r"shall|should|can|could|may|might|must)\b",
    re.IGNORECASE,
)
_VERB_SUFFIX = re.compile(r"\b\w+(s|ed|ing)\b", re.IGNORECASE)
_MIN_WORDS_FOR_CLAUSE = 4


def _is_fragment(sentence_text: str) -> bool:
    """Approximate: no NLP/POS tagging is used. A sentence counts as a
    fragment when it's short and shows no sign of a finite verb. This will
    misjudge some real sentences either way -- documented as approximate in
    docs/voice.md, not a precision claim."""
    words = sentence_text.split()
    if len(words) < _MIN_WORDS_FOR_CLAUSE:
        return True
    if _COMMON_VERBS.search(sentence_text) or _VERB_SUFFIX.search(sentence_text):
        return False
    return True


def _pick_representative_examples(sentences: list[Sentence], *, count_each: int = 2) -> list[VoiceExample]:
    if not sentences:
        return []
    by_length = sorted(sentences, key=lambda s: len(s.text.split()))
    mean_len = statistics.mean(len(s.text.split()) for s in sentences)
    by_closeness = sorted(sentences, key=lambda s: abs(len(s.text.split()) - mean_len))

    picked: list[Sentence] = []
    for group in (by_length[:count_each], by_length[-count_each:], by_closeness[:count_each]):
        for sentence in group:
            if sentence not in picked:
                picked.append(sentence)
    return [VoiceExample(text=sentence.text, source_label="corpus") for sentence in picked]


@dataclass
class CorpusStatsLearner:
    def learn(self, corpus: list[str], *, author_name: str = "") -> VoiceProfile:
        if not corpus:
            raise ValueError("cannot learn a voice profile from an empty corpus")

        documents = [Document.parse(text, title="") for text in corpus]
        sentences = [sentence for doc in documents for _, _, sentence in doc.all_sentences()]
        if not sentences:
            raise ValueError("corpus contains no parsable sentences")

        sentence_lengths = [len(s.text.split()) for s in sentences]
        words = [word for s in sentences for word in s.text.split()]
        contraction_count = sum(1 for word in words if _CONTRACTION.search(word))
        question_count = sum(1 for s in sentences if s.text.rstrip().endswith("?"))
        fragment_count = sum(1 for s in sentences if _is_fragment(s.text))
        paragraph_sentence_counts = [len(p.sentences) for doc in documents for p in doc.paragraphs]

        return VoiceProfile(
            author_name=author_name,
            sentence_length_mean=statistics.mean(sentence_lengths),
            sentence_length_stdev=(
                statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
            ),
            paragraph_length_mean=(
                statistics.mean(paragraph_sentence_counts) if paragraph_sentence_counts else None
            ),
            contraction_rate=contraction_count / len(words) if words else 0.0,
            rhetorical_question_rate=question_count / len(sentences),
            fragment_rate=fragment_count / len(sentences),
            representative_examples=_pick_representative_examples(sentences),
            generated_from="corpus_stats",
        )
