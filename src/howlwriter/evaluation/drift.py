"""Voice drift: which passages depart from a person's usual writing.

A whole-document score hides where a document changes character. Drift
analysis splits the document into windows (consecutive paragraphs merged
until each carries at least `MIN_WINDOW_WORDS` words and `MIN_WINDOW_SENTENCES`
sentences) and compares each window against the same measurements taken over
windows of the profile's own training documents.

The baseline is window-level on purpose. A single paragraph varies far more
than a whole document, so comparing a paragraph against document-level
averages would flag ordinary variation everywhere. Comparing windows against
windows means a finding says "this passage is outside the range the author's
own passages occupy", which is the claim worth making.

What a finding never says: that a passage was AI-generated, copied, or
written by someone else. Departures from a person's habits have many causes
(a quotation, a technical section, a deliberate change of register), and the
finding names the measurement, the baseline, and the size of the departure,
and leaves the cause to the writer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import statistics
from typing import Any

from howlwriter.domain.document import Document
from howlwriter.evaluation.empirical import quantile

MIN_WINDOW_WORDS = 80
MIN_WINDOW_SENTENCES = 3
#: Below this many words a window can only produce a finding when the
#: departure is extreme, and even then at LOW confidence.
CONFIDENT_WINDOW_WORDS = 120
MIN_BASELINE_WINDOWS = 20

BASELINE_VERSION = "drift-baseline/v1"

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_HEADING = re.compile(r"^\s*#{1,6}\s+")
_STOCK = re.compile(
    r"^\s*(?:moreover|furthermore|additionally|in addition|consequently|importantly|"
    r"notably|overall|ultimately|in conclusion|in summary|thus|therefore|hence)\b",
    re.IGNORECASE,
)
_HEDGE = re.compile(
    r"\b(?:may|might|could|likely|possibly|perhaps|probably|appears?|seems?|suggests?|"
    r"generally|typically|tends? to|somewhat|relatively|arguably)\b",
    re.IGNORECASE,
)
_FIRST = re.compile(r"\b(?:i|me|my|we|us|our)\b", re.IGNORECASE)
_PASSIVE = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being)\b(?:\s+\w+ly)?\s+\w+(?:ed|en|wn|rn|ne|de|lt|pt)\b",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"\b(?:in order to|it is important to note|it is worth noting|plays? an? (?:crucial|vital|key) role|"
    r"a wide (?:range|variety) of|serves as an?|when it comes to|in today'?s)\b",
    re.IGNORECASE,
)

METRICS: dict[str, dict[str, str]] = {
    "sentence_length_mean": {
        "label": "sentence length",
        "unit": "words per sentence",
        "high": "substantially longer sentences",
        "low": "substantially shorter sentences",
    },
    "long_word_rate": {
        "label": "long-word share",
        "unit": "share of words with 8+ letters",
        "high": "denser vocabulary",
        "low": "plainer vocabulary",
    },
    "stock_transition_rate": {
        "label": "stock transitions",
        "unit": "share of sentences",
        "high": "a cluster of stock transitions",
        "low": "fewer transitions",
    },
    "filler_rate": {
        "label": "padding phrases",
        "unit": "per 100 words",
        "high": "more padding phrases",
        "low": "less padding",
    },
    "hedging_rate": {
        "label": "hedging",
        "unit": "hedges per 100 words",
        "high": "more hedging",
        "low": "less hedging",
    },
    "first_person_rate": {
        "label": "first person",
        "unit": "per 100 words",
        "high": "more first person",
        "low": "less first person",
    },
    "passive_rate": {
        "label": "passive constructions",
        "unit": "per sentence",
        "high": "more passive constructions",
        "low": "fewer passive constructions",
    },
    "comma_rate": {
        "label": "comma use",
        "unit": "commas per 100 words",
        "high": "heavier comma use",
        "low": "lighter comma use",
    },
    "opening_repetition": {
        "label": "repeated openings",
        "unit": "share of sentences",
        "high": "repetitive sentence openings",
        "low": "varied openings",
    },
}

#: Departures in these directions are reported; the opposite direction is
#: ordinary variation and stays silent ("fewer stock transitions than usual"
#: is not something a writer needs to be told).
_ONE_SIDED_HIGH = {"stock_transition_rate", "filler_rate", "opening_repetition"}


@dataclass
class Window:
    first_paragraph: int
    last_paragraph: int
    words: int
    sentences: int
    metrics: dict[str, float] = field(default_factory=dict)


def windows(text: str) -> list[Window]:
    """Split a document into analysis windows. Indices are 0-based paragraphs."""
    document = Document.parse(text)
    prose = [
        p
        for p in document.body_paragraphs()
        if not _HEADING.match(p.raw_text) and _WORD.search(p.raw_text)
    ]
    result: list[Window] = []
    bucket: list = []

    def flush() -> None:
        if not bucket:
            return
        sentences = [s.text for p in bucket for s in p.sentences if _WORD.search(s.text)]
        joined = " ".join(p.raw_text for p in bucket)
        words = len(_WORD.findall(joined))
        result.append(
            Window(
                first_paragraph=bucket[0].index,
                last_paragraph=bucket[-1].index,
                words=words,
                sentences=len(sentences),
                metrics=_metrics(joined, sentences, words),
            )
        )
        bucket.clear()

    for paragraph in prose:
        bucket.append(paragraph)
        sentences = sum(len(p.sentences) for p in bucket)
        words = sum(len(_WORD.findall(p.raw_text)) for p in bucket)
        if words >= MIN_WINDOW_WORDS and sentences >= MIN_WINDOW_SENTENCES:
            flush()
    if bucket:
        # A short tail joins the previous window instead of standing alone.
        if result and sum(len(_WORD.findall(p.raw_text)) for p in bucket) < MIN_WINDOW_WORDS:
            tail = list(bucket)
            bucket.clear()
            previous = result.pop()
            merged = [p for p in prose if previous.first_paragraph <= p.index <= tail[-1].index]
            bucket.extend(merged)
        flush()
    return result


def _metrics(text: str, sentences: list[str], words: int) -> dict[str, float]:
    count = max(1, len(sentences))
    per_100 = 100.0 / max(1, words)
    lengths = [len(_WORD.findall(s)) for s in sentences] or [0]
    tokens = _WORD.findall(text)
    openings: dict[str, int] = {}
    for sentence in sentences:
        head = _WORD.findall(sentence)[:2]
        if len(head) == 2:
            key = " ".join(w.lower() for w in head)
            openings[key] = openings.get(key, 0) + 1
    return {
        "sentence_length_mean": statistics.mean(lengths),
        "long_word_rate": sum(1 for t in tokens if len(t) >= 8) / max(1, len(tokens)),
        "stock_transition_rate": sum(1 for s in sentences if _STOCK.match(s)) / count,
        "filler_rate": len(_FILLER.findall(text)) * per_100,
        "hedging_rate": len(_HEDGE.findall(text)) * per_100,
        "first_person_rate": len(_FIRST.findall(text)) * per_100,
        "passive_rate": len(_PASSIVE.findall(text)) / count,
        "comma_rate": text.count(",") * per_100,
        "opening_repetition": sum(c - 1 for c in openings.values() if c > 1) / count,
    }


def window_metrics(text: str) -> list[dict[str, float]]:
    """Window metrics only (numbers, no positions), for caching at scan time."""
    return [dict(w.metrics, words=float(w.words)) for w in windows(text)]


@dataclass
class DriftBaseline:
    """Per-metric quantiles over the training documents' windows."""

    profile: str
    windows: int = 0
    documents: int = 0
    quantiles: dict[str, dict[str, float]] = field(default_factory=dict)
    version: str = BASELINE_VERSION

    @property
    def usable(self) -> bool:
        return self.windows >= MIN_BASELINE_WINDOWS

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DriftBaseline":
        return cls(
            profile=str(data.get("profile", "")),
            windows=int(data.get("windows", 0)),
            documents=int(data.get("documents", 0)),
            quantiles={
                k: {q: float(v) for q, v in qs.items()}
                for k, qs in (data.get("quantiles") or {}).items()
            },
            version=str(data.get("version", BASELINE_VERSION)),
        )


def build_baseline(
    profile: str, per_document_windows: list[list[dict[str, float]]]
) -> DriftBaseline:
    pooled: dict[str, list[float]] = {name: [] for name in METRICS}
    count = 0
    for doc_windows in per_document_windows:
        for window in doc_windows:
            count += 1
            for name in METRICS:
                if name in window:
                    pooled[name].append(float(window[name]))
    quantiles = {
        name: {
            "p05": quantile(values, 0.05),
            "p25": quantile(values, 0.25),
            "p50": quantile(values, 0.50),
            "p75": quantile(values, 0.75),
            "p95": quantile(values, 0.95),
        }
        for name, values in pooled.items()
        if values
    }
    return DriftBaseline(
        profile=profile,
        windows=count,
        documents=sum(1 for w in per_document_windows if w),
        quantiles=quantiles,
    )


@dataclass
class DriftFinding:
    first_paragraph: int
    last_paragraph: int
    metric: str
    observed: float
    baseline_typical: tuple[float, float]
    baseline_range: tuple[float, float]
    direction: str
    severity: str
    confidence: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["observed"] = round(self.observed, 3)
        data["baseline_typical"] = [round(v, 3) for v in self.baseline_typical]
        data["baseline_range"] = [round(v, 3) for v in self.baseline_range]
        data["span"] = (
            f"paragraph {self.first_paragraph + 1}"
            if self.first_paragraph == self.last_paragraph
            else f"paragraphs {self.first_paragraph + 1}-{self.last_paragraph + 1}"
        )
        return data


_SUGGESTIONS = {
    "sentence_length_mean": (
        "Check whether these sentences are carrying several ideas that would read better "
        "apart (or the reverse)."
    ),
    "stock_transition_rate": "Remove connectives the logic already implies.",
    "filler_rate": "Cut padding phrases that add length without meaning.",
    "opening_repetition": "Vary how consecutive sentences begin.",
    "hedging_rate": "Keep qualifications the evidence requires; drop the ones it does not.",
}


def analyze(
    text: str, baseline: DriftBaseline | None, *, context_label: str = ""
) -> dict[str, Any]:
    """Drift findings for one document, or an explanation of why there are none."""
    if baseline is None or not baseline.usable:
        return {
            "status": "UNAVAILABLE",
            "reason": (
                "no window-level baseline for this profile"
                if baseline is None
                else (
                    f"baseline has {baseline.windows} windows; drift analysis needs at least "
                    f"{MIN_BASELINE_WINDOWS}"
                )
            ),
            "findings": [],
        }
    found: list[DriftFinding] = []
    label = f"the {context_label} reference" if context_label else "the profile's reference"
    for window in windows(text):
        if window.words < MIN_WINDOW_WORDS:
            continue
        for name, spec in METRICS.items():
            q = baseline.quantiles.get(name)
            if not q:
                continue
            value = window.metrics.get(name, 0.0)
            iqr = max(q["p75"] - q["p25"], 1e-9)
            if value > q["p95"]:
                direction = "high"
                strong = value > q["p75"] + 3.0 * iqr
            elif value < q["p05"] and name not in _ONE_SIDED_HIGH:
                direction = "low"
                strong = value < q["p25"] - 3.0 * iqr
            else:
                continue
            if window.words < CONFIDENT_WINDOW_WORDS:
                if not strong:
                    continue
                confidence = "LOW"
            else:
                confidence = "HIGH" if window.words >= 250 and strong else "MEDIUM"
            found.append(
                DriftFinding(
                    first_paragraph=window.first_paragraph,
                    last_paragraph=window.last_paragraph,
                    metric=name,
                    observed=value,
                    baseline_typical=(q["p25"], q["p75"]),
                    baseline_range=(q["p05"], q["p95"]),
                    direction=direction,
                    severity="strong" if strong else "notable",
                    confidence=confidence,
                    message=(
                        f"uses {spec[direction]} ({value:.2f} {spec['unit']}) than {label} "
                        f"(typical {q['p25']:.2f}-{q['p75']:.2f}; 90% of reference passages "
                        f"{q['p05']:.2f}-{q['p95']:.2f})"
                    ),
                    suggestion=_SUGGESTIONS.get(name, ""),
                )
            )
    merged = _merge_adjacent(found)
    return {
        "status": "ANALYZED",
        "baseline_windows": baseline.windows,
        "baseline_documents": baseline.documents,
        "findings": [f.to_dict() for f in merged],
        "note": (
            "Findings describe departures from the profile's usual passages. They do not "
            "say how a passage was written, and ordinary variation is expected."
        ),
    }


def _merge_adjacent(findings: list[DriftFinding]) -> list[DriftFinding]:
    """Join consecutive windows that depart on the same metric, same direction."""
    by_metric: dict[tuple[str, str], list[DriftFinding]] = {}
    for finding in findings:
        by_metric.setdefault((finding.metric, finding.direction), []).append(finding)
    merged: list[DriftFinding] = []
    for group in by_metric.values():
        group.sort(key=lambda f: f.first_paragraph)
        current = group[0]
        for nxt in group[1:]:
            if nxt.first_paragraph <= current.last_paragraph + 1:
                severity = "strong" if "strong" in (current.severity, nxt.severity) else "notable"
                order = ["LOW", "MEDIUM", "HIGH"]
                confidence = order[
                    max(order.index(current.confidence), order.index(nxt.confidence))
                ]
                current = DriftFinding(
                    current.first_paragraph,
                    nxt.last_paragraph,
                    current.metric,
                    (
                        max(current.observed, nxt.observed)
                        if current.direction == "high"
                        else min(current.observed, nxt.observed)
                    ),
                    current.baseline_typical,
                    current.baseline_range,
                    current.direction,
                    severity,
                    confidence,
                    current.message.replace("uses", "consistently use", 1),
                    current.suggestion,
                )
            else:
                merged.append(current)
                current = nxt
        merged.append(current)
    merged.sort(key=lambda f: (f.first_paragraph, f.metric))
    return merged
