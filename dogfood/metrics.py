"""Every benchmark number, computed from raw artifacts in one place.

The previous milestone's report said parentheticals appeared in 92% of outputs
when the artifacts said 100%, said a range was 2-5 when the raw output was 3-6,
and called a run production-ready while the diversity checker said FAIL. The
correct values existed in data structures at the time. What failed was a person
reading them across.

Three of the four dogfood runners had their own `compute_batch_stats` and their
own result schema, so there was no single place those numbers could be checked
against. This module is that place. Every runner writes the same shape, and the
final report is generated from it rather than transcribed out of it.

Nothing here takes a summary as input. Everything is recomputed from the stored
generation text, so a report figure can always be re-derived from the artifact
it describes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import statistics
from typing import Any, Iterable

from howlwriter.voice.corpus.features import DocumentFeatures, extract_features
from howlwriter.voice.corpus.diversity import (
    classify_closing,
    classify_opening,
    classify_reasoning_moves,
    classify_reasoning_shape,
)

#: Features summarised for every batch. Chosen to cover the axes a converged
#: batch actually collapses on: length, rhythm, and the sparse habits that turn
#: into signatures.
BATCH_FEATURES = (
    "words",
    "sentences",
    "paragraphs",
    "sentence_length_mean",
    "sentence_length_stdev",
    "paragraph_words_mean",
    "paragraph_words_stdev",
    "single_sentence_paragraph_rate",
    "short_sentence_rate",
    "long_sentence_rate",
    "first_person_rate",
    "second_person_rate",
    "parenthetical_rate",
    "question_rate",
    "contraction_rate",
    "em_dash_rate",
    "semicolon_rate",
    "transition_rate",
    "sentence_initial_conjunction_rate",
    "fragment_rate",
    "list_rate",
    "lexical_diversity",
)

_PARENTHETICAL = re.compile(r"\(([^)]{1,200})\)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_FIRST_PERSON = re.compile(r"\b(I|I'm|I've|I'd|I'll|me|my|mine|we|we're|we've|our|ours|us)\b", re.I)
_HASHTAG_LINE = re.compile(r"^\s*(?:#[\w-]+\s*)+$")
_HEADING_LINE = re.compile(r"^\s*#{1,6}\s+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")


def _stat_block(values: list[float]) -> dict[str, float]:
    """Mean, spread, range and coefficient of variation for one measure."""
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0, "cv": 0.0, "n": 0}
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "mean": round(mean, 4),
        "stdev": round(stdev, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        # CV is what makes "varies a lot" mean the same thing for a batch of
        # 130-word posts and a batch of 900-word papers.
        "cv": round(stdev / mean, 4) if mean else 0.0,
        "n": len(values),
    }


def batch_stats(texts: Iterable[str]) -> dict[str, dict[str, float]]:
    """Per-feature statistics across a batch of generated pieces."""
    vectors = [extract_features(text) for text in texts if text and text.strip()]
    return {
        name: _stat_block([float(getattr(v, name, 0.0) or 0.0) for v in vectors])
        for name in BATCH_FEATURES
    }


# --- signature analysis --------------------------------------------------
#
# A signature is not a habit that appears often. It is a habit that appears at
# the same rate, in the same position, doing the same job, every time. Counting
# occurrences cannot tell those apart, so placement and syntactic function are
# measured separately from frequency.

@dataclass
class ParentheticalReport:
    documents: int = 0
    documents_with: int = 0
    presence_rate: float = 0.0
    total: int = 0
    per_document: list[int] = field(default_factory=list)
    #: Share of parentheticals opening with the same one or two words. The
    #: previous audit found 7 of 26 opening with "such as", which frequency
    #: alone would never have shown.
    opening_words: dict[str, int] = field(default_factory=dict)
    top_opening_share: float = 0.0
    #: Where in the piece they land, as a fraction of the way through.
    mean_position: float = 0.0
    position_cv: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents": self.documents,
            "documents_with": self.documents_with,
            "presence_rate": round(self.presence_rate, 4),
            "total": self.total,
            "per_document": self.per_document,
            "opening_words": self.opening_words,
            "top_opening_share": round(self.top_opening_share, 4),
            "mean_position": round(self.mean_position, 4),
            "position_cv": round(self.position_cv, 4),
        }


def parenthetical_report(texts: list[str]) -> ParentheticalReport:
    report = ParentheticalReport(documents=len(texts))
    positions: list[float] = []
    openings: dict[str, int] = {}

    for text in texts:
        matches = list(_PARENTHETICAL.finditer(text))
        report.per_document.append(len(matches))
        if matches:
            report.documents_with += 1
        report.total += len(matches)
        length = max(1, len(text))
        for match in matches:
            positions.append(match.start() / length)
            words = match.group(1).strip().lower().split()
            if words:
                key = " ".join(words[:2]) if len(words) > 1 else words[0]
                openings[key] = openings.get(key, 0) + 1

    report.presence_rate = report.documents_with / len(texts) if texts else 0.0
    report.opening_words = dict(
        sorted(openings.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    )
    if report.total:
        report.top_opening_share = max(openings.values()) / report.total if openings else 0.0
    if positions:
        report.mean_position = statistics.mean(positions)
        if len(positions) > 1 and report.mean_position:
            report.position_cv = statistics.pstdev(positions) / report.mean_position
    return report


def first_person_report(texts: list[str]) -> dict[str, Any]:
    """Rate and presence, kept apart for the same reason the profile does."""
    rates: list[float] = []
    for text in texts:
        words = max(1, len(text.split()))
        rates.append(len(_FIRST_PERSON.findall(text)) * 100.0 / words)
    non_zero = [r for r in rates if r > 0]
    return {
        "documents": len(texts),
        "documents_with": len(non_zero),
        "presence_rate": round(len(non_zero) / len(texts), 4) if texts else 0.0,
        "mean_per_100_words": round(statistics.mean(rates), 4) if rates else 0.0,
        "median_when_present": round(statistics.median(non_zero), 4) if non_zero else 0.0,
        "per_document": [round(r, 4) for r in rates],
    }


def body_paragraphs(text: str) -> list[str]:
    """Return prose paragraphs, excluding headings and hashtag trailers."""
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [
            line.strip()
            for line in block.splitlines()
            if line.strip()
            and not _HEADING_LINE.match(line)
            and not _HASHTAG_LINE.match(line)
        ]
        if lines:
            paragraphs.append(" ".join(lines))
    return paragraphs


def paragraph_structure_report(texts: list[str]) -> dict[str, Any]:
    """Paragraph count, word distribution, and within-piece weight variance."""
    counts: list[float] = []
    all_words: list[float] = []
    weight_variances: list[float] = []
    per_document: list[dict[str, Any]] = []
    distribution: dict[str, int] = {}
    for text in texts:
        paragraphs = body_paragraphs(text)
        word_counts = [len(_WORD.findall(p)) for p in paragraphs]
        count = len(paragraphs)
        counts.append(float(count))
        distribution[str(count)] = distribution.get(str(count), 0) + 1
        all_words.extend(float(value) for value in word_counts)
        total = sum(word_counts)
        weights = [value / total for value in word_counts] if total else []
        weight_variance = (
            statistics.pvariance(weights) if len(weights) > 1 else 0.0
        )
        weight_variances.append(weight_variance)
        per_document.append(
            {
                "paragraph_count": count,
                "paragraph_words": word_counts,
                "paragraph_weight_variance": round(weight_variance, 6),
            }
        )

    mode_count = max(distribution.values(), default=0)
    modes = sorted(
        int(value) for value, count in distribution.items() if count == mode_count
    )
    return {
        "count_distribution": dict(
            sorted(distribution.items(), key=lambda item: int(item[0]))
        ),
        "count_stats": _stat_block(counts),
        "paragraph_word_distribution": _stat_block(all_words),
        "paragraph_weight_variance": _stat_block(weight_variances),
        "modal_counts": modes,
        "modal_share": round(mode_count / len(texts), 4) if texts else 0.0,
        "per_document": per_document,
    }


def opening_closing_convergence(texts: list[str]) -> dict[str, Any]:
    """How often a batch starts and ends the same way.

    A shared opening formula is the most legible tell a batch can carry, and it
    survives every check that looks only at aggregate rates.
    """
    openings: dict[str, int] = {}
    closings: dict[str, int] = {}
    opening_classes: dict[str, int] = {}
    closing_classes: dict[str, int] = {}
    for text in texts:
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
        if not sentences:
            continue
        first = " ".join(sentences[0].lower().split()[:2])
        last = " ".join(sentences[-1].lower().split()[-3:])
        openings[first] = openings.get(first, 0) + 1
        closings[last] = closings.get(last, 0) + 1
        opening_class = classify_opening(text)
        closing_class = classify_closing(text)
        opening_classes[opening_class] = opening_classes.get(opening_class, 0) + 1
        closing_classes[closing_class] = closing_classes.get(closing_class, 0) + 1
    total = max(1, len(texts))
    return {
        "top_opening": max(openings.items(), key=lambda kv: kv[1]) if openings else None,
        "top_opening_share": round(max(openings.values()) / total, 4) if openings else 0.0,
        "top_closing": max(closings.items(), key=lambda kv: kv[1]) if closings else None,
        "top_closing_share": round(max(closings.values()) / total, 4) if closings else 0.0,
        "distinct_openings": len(openings),
        "distinct_closings": len(closings),
        "opening_classes": opening_classes,
        "closing_classes": closing_classes,
    }


def reasoning_shape(text: str) -> dict[str, Any]:
    """Describe a piece's argumentative progression, not its paragraph count.

    The template the previous audit named -- thesis, mechanism, deeper
    mechanism, rule, declarative close -- is a progression, and counting
    paragraphs cannot see it. This looks for the moves: a claim, causal
    development, a generalising rule, and how the piece lands.
    """
    paragraphs = body_paragraphs(text)
    moves = classify_reasoning_moves(text)
    closing_class = classify_closing(text)
    return {
        "paragraphs": len(paragraphs),
        "shape": moves,
        "signature": classify_reasoning_shape(text),
        "opening_class": classify_opening(text),
        "closing_class": closing_class,
        "closes_declarative": bool(paragraphs) and closing_class != "question",
        "closes_with_rule": closing_class == "recommendation",
        "has_hashtags": any(
            _HASHTAG_LINE.match(line.strip())
            for line in text.splitlines()
            if line.strip()
        ),
    }


def reasoning_template_convergence(texts: list[str]) -> dict[str, Any]:
    """How many pieces in a batch share one argumentative progression."""
    shapes = [reasoning_shape(t) for t in texts]
    signatures: dict[str, int] = {}
    for shape in shapes:
        signatures[shape["signature"]] = signatures.get(shape["signature"], 0) + 1
    total = max(1, len(texts))
    declarative = sum(1 for s in shapes if s["closes_declarative"])
    return {
        "distinct_signatures": len(signatures),
        "documents": len(texts),
        "top_signature": max(signatures.items(), key=lambda kv: kv[1]) if signatures else None,
        "top_signature_share": round(max(signatures.values()) / total, 4) if signatures else 0.0,
        "declarative_close_share": round(declarative / total, 4),
        "rule_close_share": round(
            sum(1 for s in shapes if s["closes_with_rule"]) / total, 4
        ),
        "per_document": [s["signature"] for s in shapes],
    }


def diversity_verdict(
    corpus_features: list[DocumentFeatures],
    generated: list[str],
    *,
    context_features: list[DocumentFeatures] | None = None,
) -> dict[str, Any]:
    """Run the real diversity checker and serialize its verdict.

    Serialized in full -- every dimension, every ratio -- because a bare verdict
    cannot be re-checked, and the previous report presented one that disagreed
    with the checker it came from.
    """
    from howlwriter.voice.corpus.diversity import compare

    result = compare(
        corpus_features,
        generated,
        context_corpus_features=context_features,
    )
    return {
        "verdict": result.verdict,
        "converged_dimensions": list(result.converged_dimensions),
        "notes": list(result.notes),
        "dimensions": [
            {
                "name": d.name,
                "corpus_variation": round(d.corpus_variation, 4),
                "generated_variation": round(d.generated_variation, 4),
                "ratio": round(d.ratio, 4),
                "converged": d.converged,
            }
            for d in result.dimensions
        ],
    }


def analyze_batch(
    texts: list[str],
    *,
    corpus_features: list[DocumentFeatures] | None = None,
    context_features: list[DocumentFeatures] | None = None,
) -> dict[str, Any]:
    """The complete measured picture of one generation batch."""
    usable = [t for t in texts if t and t.strip()]
    payload: dict[str, Any] = {
        "samples": len(usable),
        "stats": batch_stats(usable),
        "paragraphs": paragraph_structure_report(usable),
        "parentheticals": parenthetical_report(usable).to_dict(),
        "first_person": first_person_report(usable),
        "openings_closings": opening_closing_convergence(usable),
        "reasoning": reasoning_template_convergence(usable),
    }
    if corpus_features:
        payload["diversity"] = diversity_verdict(
            corpus_features,
            usable,
            context_features=context_features,
        )
    return payload


def grouped_variation(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate variation across prompts from repeat variation within prompts."""
    groups: dict[str, list[DocumentFeatures]] = {}
    for record in records:
        output = str(record.get("output") or "")
        if record.get("status") != "OK" or not output.strip():
            continue
        groups.setdefault(str(record.get("id") or ""), []).append(
            extract_features(output)
        )

    between: dict[str, dict[str, float]] = {}
    within: dict[str, Any] = {}
    for feature in BATCH_FEATURES:
        group_means = [
            statistics.mean(float(getattr(item, feature, 0.0) or 0.0) for item in items)
            for items in groups.values()
            if items
        ]
        between[feature] = _stat_block(group_means)

        per_prompt: dict[str, dict[str, float]] = {}
        stdevs: list[float] = []
        cvs: list[float] = []
        for prompt_id, items in groups.items():
            if len(items) < 2:
                continue
            values = [float(getattr(item, feature, 0.0) or 0.0) for item in items]
            mean = statistics.mean(values)
            stdev = statistics.pstdev(values)
            cv = stdev / abs(mean) if mean else 0.0
            stdevs.append(stdev)
            cvs.append(cv)
            per_prompt[prompt_id] = {
                "mean": round(mean, 4),
                "stdev": round(stdev, 4),
                "cv": round(cv, 4),
            }
        within[feature] = {
            "groups_with_repeats": len(per_prompt),
            "stdev_across_repeat_groups": _stat_block(stdevs),
            "cv_across_repeat_groups": _stat_block(cvs),
            "per_prompt": per_prompt,
        }
    return {
        "prompts": len(groups),
        "between_prompt": between,
        "within_prompt": within,
    }
