"""Voice Generation Diagnostics.

Diagnostic evaluation of stylistic and voice drift (sentence length, readability,
long-word rate, formality/register drift) without performing generative rewriting.
Voice-generation rewrite algorithms are explicitly deferred to post-audit milestones.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

from howlwriter.domain.serialization import DataClassSerializationMixin

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+(?:\s+|$)")
_WORD_RE = re.compile(r"\b[A-Za-z0-9_\-']+\b")

_INFORMAL_MARKERS = frozenset({
    "gonna", "wanna", "kinda", "sorta", "yeah", "nope", "yep", "stuff",
    "things", "cool", "super", "really", "pretty", "lots", "bunch",
    "awesome", "crazy", "huge", "totally", "basically",
})

_FORMAL_MARKERS = frozenset({
    "consequently", "furthermore", "moreover", "nonetheless", "notwithstanding",
    "predominantly", "subsequently", "demonstrably", "systematically",
    "elucidate", "delineate", "substantiate", "empirical", "methodology",
})


def _count_syllables(word: str) -> int:
    """Heuristic syllable counter for English words."""
    w = word.lower().strip()
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    # Remove trailing silent e
    if w.endswith("e") and not w.endswith("le") and not w.endswith("ee"):
        w = w[:-1]
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in w:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)


@dataclass
class VoiceDiagnostics(DataClassSerializationMixin):
    """Stylistic and voice diagnostic metrics."""

    word_count: int = 0
    sentence_count: int = 0
    sentence_length_mean: float = 0.0
    sentence_length_std: float = 0.0
    long_word_rate: float = 0.0
    avg_syllables_per_word: float = 0.0
    flesch_reading_ease: float = 0.0
    flesch_kincaid_grade: float = 0.0
    formality_score: float = 0.0


def compute_voice_diagnostics(text: str) -> VoiceDiagnostics:
    """Computes stylistic diagnostics for a passage of text."""
    raw_sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    all_words = _WORD_RE.findall(text)
    total_words = len(all_words)
    total_sentences = max(1, len(raw_sentences))

    if total_words == 0:
        return VoiceDiagnostics()

    sentence_lengths = [len(_WORD_RE.findall(s)) for s in raw_sentences if s]
    mean_len = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0.0
    variance = (
        sum((l - mean_len) ** 2 for l in sentence_lengths) / len(sentence_lengths)
        if sentence_lengths
        else 0.0
    )
    std_len = math.sqrt(variance)

    # Long words: length >= 7 or syllables >= 3
    long_words = [w for w in all_words if len(w) >= 7]
    long_word_rate = len(long_words) / total_words

    syllable_counts = [_count_syllables(w) for w in all_words]
    total_syllables = sum(syllable_counts)
    avg_syllables = total_syllables / total_words

    # Flesch Reading Ease: 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
    reading_ease = 206.835 - (1.015 * (total_words / total_sentences)) - (84.6 * avg_syllables)
    reading_ease = max(0.0, min(100.0, round(reading_ease, 2)))

    # Flesch-Kincaid Grade Level: 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
    grade_level = (0.39 * (total_words / total_sentences)) + (11.8 * avg_syllables) - 15.59
    grade_level = max(0.0, round(grade_level, 2))

    # Formality score: (formal - informal) / total_words normalized
    lowered_words = [w.lower() for w in all_words]
    formal_hits = sum(1 for w in lowered_words if w in _FORMAL_MARKERS)
    informal_hits = sum(1 for w in lowered_words if w in _INFORMAL_MARKERS)
    formality = (formal_hits - informal_hits) / max(1, formal_hits + informal_hits) if (formal_hits + informal_hits) > 0 else 0.0

    return VoiceDiagnostics(
        word_count=total_words,
        sentence_count=total_sentences,
        sentence_length_mean=round(mean_len, 2),
        sentence_length_std=round(std_len, 2),
        long_word_rate=round(long_word_rate, 4),
        avg_syllables_per_word=round(avg_syllables, 2),
        flesch_reading_ease=reading_ease,
        flesch_kincaid_grade=grade_level,
        formality_score=round(formality, 3),
    )


def diagnose_voice_drift(
    current_text: str,
    baseline: VoiceDiagnostics | str,
) -> dict[str, Any]:
    """Compares current text diagnostics against baseline voice profile."""
    curr_diag = compute_voice_diagnostics(current_text)
    if isinstance(baseline, str):
        base_diag = compute_voice_diagnostics(baseline)
    else:
        base_diag = baseline

    return {
        "current": curr_diag.to_dict(),
        "baseline": base_diag.to_dict(),
        "drift": {
            "sentence_length_drift": round(curr_diag.sentence_length_mean - base_diag.sentence_length_mean, 2),
            "long_word_rate_drift": round(curr_diag.long_word_rate - base_diag.long_word_rate, 4),
            "reading_ease_drift": round(curr_diag.flesch_reading_ease - base_diag.flesch_reading_ease, 2),
            "grade_level_drift": round(curr_diag.flesch_kincaid_grade - base_diag.flesch_kincaid_grade, 2),
            "formality_drift": round(curr_diag.formality_score - base_diag.formality_score, 3),
        },
    }
