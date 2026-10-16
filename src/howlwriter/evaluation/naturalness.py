"""Human Naturalness: how mechanical a document reads, against real writing.

What the number means, exactly. The Naturalness Score is an empirical
percentile. A document scoring 70 reads as less mechanical than 70% of the
reference documents (human writing in the same context), on the dimensions
below, with each reference document scored as if it were unseen
(leave-one-out). 50 is a typical reference document.

What it does not mean, also exactly:

* It is not the probability that a human wrote the document. Nothing here
  estimates authorship, and no code path could produce such a number.
* It is not an AI detector and is not tuned against any third-party detector.
* Formal is not mechanical. Passive voice, long words, and academic register
  are deliberately not dimensions. A dense, formal paper is compared against
  formal reference writing, not against a blog post.

Why direction matters. Every dimension is scored only in its mechanical
direction. A document with MORE sentence variation than every reference
document is not penalised for being unusual; one with less is. That one-sided
rule is what keeps Naturalness independent of Voice Match: a natural writer
whose style differs from the profile scores high here and low there.

When there is no number. Short documents (below `MIN_WORDS` words or
`MIN_SENTENCES` sentences) and missing or thin reference sets produce status
UNAVAILABLE with the descriptive measurements still reported. An unsupported
percentage is worse than none.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
import statistics
from typing import Any

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.evaluation.empirical import describe, quantile, separation
from howlwriter.linting.engine import LintEngine
from howlwriter.linting import rules as lint_rules

MEASUREMENT_VERSION = "naturalness-measure/v1"
CALIBRATION_VERSION = "naturalness-calibration/v2-length-weighted"

#: Below these, the dimensions are too noisy to rank against anything.
MIN_WORDS = 250
MIN_SENTENCES = 12

#: A reference set smaller than this cannot support a percentile: one
#: document moves the answer by more than five points.
MIN_REFERENCE_DOCUMENTS = 12

#: The lower bound of the 95% AUC interval, against controls, below which the
#: score is still reported but its confidence is marked unvalidated.
VALIDATED_AUC_FLOOR = 0.65

STATUS_SCORED = "SCORED"
STATUS_UNAVAILABLE = "UNAVAILABLE"

DISCLAIMER = (
    "Naturalness ranks how mechanical the prose reads against a reference set of "
    "human writing in the same context. It is not the probability that a human "
    "wrote the document, and it is not an AI detector."
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_HEADING = re.compile(r"^\s*#{1,6}\s+")

#: Sentence-initial connectives that, stacked, make prose read assembled.
#: Each is legitimate; the measure is their density, ranked against real
#: writing in the same context, so formal papers are not penalised for
#: the "however" that formal papers use.
_STOCK_CONNECTIVES = re.compile(
    r"^\s*(?:moreover|furthermore|additionally|in addition|consequently|"
    r"importantly|notably|overall|ultimately|in conclusion|in summary|"
    r"to summarize|in essence|thus|therefore|hence|as a result|"
    r"it is (?:important|worth|crucial) to (?:note|mention|highlight))\b",
    re.IGNORECASE,
)
_SUMMARY_CLOSER = re.compile(
    r"^\s*(?:overall|in short|in summary|in conclusion|ultimately|in essence|"
    r"this (?:shows|highlights|demonstrates|underscores|illustrates|ensures)|"
    r"these (?:findings|results|steps) (?:show|highlight|demonstrate))\b",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"\b(?:in order to|it is important to note|it is worth noting|it should be noted|"
    r"plays? an? (?:crucial|vital|key|pivotal|important) role|a wide (?:range|variety) of|"
    r"due to the fact that|at the end of the day|in today'?s|when it comes to|"
    r"serves as an?|in the realm of|a testament to|navigat(?:e|ing) the complexities)\b",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    "a an the and or but if then so of to in on at by for with from as is are was were be "
    "been being it its this that these those there here which who whom what when where why "
    "how not no can could should would may might will shall do does did has have had i we "
    "you he she they them our your their my me us his her also than too very just into over "
    "under about between through during each such any all some more most other".split()
)

#: Lint families that count as formulaic language. Generic transitions are
#: counted with the connectives instead, so one habit is not counted twice.
_FORMULAIC_CODES = frozenset(
    {
        lint_rules.AI_STYLE_BANNED_WORD,
        lint_rules.AI_STYLE_NOT_X_BUT_Y,
        lint_rules.AI_STYLE_FORMULAIC_CONTRAST,
        lint_rules.AI_STYLE_EMPTY_TRANSITION,
        lint_rules.AI_STYLE_CANNED_OPENING,
        lint_rules.AI_STYLE_CANNED_CONCLUSION,
        lint_rules.AI_STYLE_GENERIC_INTENSIFIER,
        lint_rules.AI_STYLE_CORPORATE_FILLER,
        lint_rules.AI_STYLE_REPETITIVE_TRICOLON,
        lint_rules.AI_STYLE_ENGAGEMENT_BAIT,
        lint_rules.AI_STYLE_FAKE_RHETORICAL_HOOK,
        lint_rules.AI_STYLE_MOTIVATIONAL_SLOP,
    }
)
_TRANSITION_CODES = frozenset({lint_rules.AI_STYLE_GENERIC_TRANSITION})
_CONCLUSION_CODES = frozenset({lint_rules.AI_STYLE_REPETITIVE_MINI_CONCLUSION})
_STRUCTURE_CODES = frozenset(
    {
        lint_rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY,
        lint_rules.AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE,
    }
)

LOW_IS_MECHANICAL = "low_is_mechanical"
HIGH_IS_MECHANICAL = "high_is_mechanical"
TWO_SIDED = "two_sided"


@dataclass(frozen=True)
class DimensionSpec:
    label: str
    direction: str
    measures: str
    weakness: str
    suggestion: str


DIMENSIONS: dict[str, DimensionSpec] = {
    "sentence_variation": DimensionSpec(
        "Sentence variation",
        LOW_IS_MECHANICAL,
        "coefficient of variation of sentence length",
        "sentence lengths are more uniform than in comparable human writing",
        "Let sentence length follow the thought: a short sentence where a point lands, a "
        "longer one where an idea needs its qualifications.",
    ),
    "paragraph_variation": DimensionSpec(
        "Paragraph variation",
        LOW_IS_MECHANICAL,
        "coefficient of variation of paragraph length in words",
        "paragraphs are closer to one size than in comparable human writing",
        "Size paragraphs by what they carry rather than to a target; some ideas need two "
        "sentences and some need six.",
    ),
    "opening_repetition": DimensionSpec(
        "Repeated sentence openings",
        HIGH_IS_MECHANICAL,
        "share of sentences reusing an opening two-word pattern",
        "many sentences start the same way",
        "Vary how sentences enter: start some with the subject, some with the condition, "
        "some with the consequence.",
    ),
    "formulaic_density": DimensionSpec(
        "Formulaic language",
        HIGH_IS_MECHANICAL,
        "formulaic phrases, canned openings/conclusions and filler per 1000 words",
        "formulaic or canned phrasing appears more often than in comparable writing",
        "Replace stock phrases with the specific claim they stand in for.",
    ),
    "stock_transitions": DimensionSpec(
        "Mechanical transitions",
        HIGH_IS_MECHANICAL,
        "share of sentences opening with a stock connective",
        "sentences lean on stock connectives (moreover, furthermore, additionally)",
        "Drop connectives the logic already implies; keep the ones that mark a real turn.",
    ),
    "structural_uniformity": DimensionSpec(
        "Structural uniformity",
        HIGH_IS_MECHANICAL,
        "share of adjacent paragraphs with identical sentence counts",
        "consecutive paragraphs repeat the same shape",
        "Let paragraph structure differ where the content differs.",
    ),
    "redundancy": DimensionSpec(
        "Redundancy",
        HIGH_IS_MECHANICAL,
        "share of content-word trigrams that repeat within the document",
        "the same phrasing recurs more than in comparable writing",
        "Say each thing once in its strongest place; cut restatements.",
    ),
    "conclusion_repetition": DimensionSpec(
        "Repetitive conclusions",
        HIGH_IS_MECHANICAL,
        "share of paragraphs that end on a summarising closer",
        "paragraphs repeatedly end by summarising themselves",
        "End paragraphs on their last real point rather than a recap.",
    ),
    "filler_rate": DimensionSpec(
        "Verbosity",
        HIGH_IS_MECHANICAL,
        "padding phrases per 100 words",
        "padding phrases add words without adding meaning",
        "Cut padding such as 'in order to' and 'it is important to note'.",
    ),
    "readability_fit": DimensionSpec(
        "Readability for context",
        TWO_SIDED,
        "Flesch-Kincaid grade, compared with the context's reference range",
        "reading level sits outside the usual range for this kind of document",
        "Check whether sentences are carrying more (or less) than the context calls for.",
    ),
    "cohesion": DimensionSpec(
        "Sentence-to-sentence cohesion",
        TWO_SIDED,
        "mean content-word overlap between adjacent sentences",
        "adjacent sentences are unusually disconnected or unusually repetitive",
        "Check that each sentence picks up from the last without restating it.",
    ),
}

#: Paragraph-count requirements per dimension; a measure of paragraph shape
#: on a two-paragraph document is noise.
_MIN_PARAGRAPHS = {
    "paragraph_variation": 4,
    "structural_uniformity": 4,
    "conclusion_repetition": 3,
}


@dataclass
class Location:
    """Where in the document a finding applies. Indices are 0-based."""

    kind: str
    paragraph_index: int | None = None
    sentence_index: int | None = None
    message: str = ""
    excerpt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NaturalnessMeasurement:
    """Raw, context-free measurements of one document."""

    words: int = 0
    sentences: int = 0
    paragraphs: int = 0
    values: dict[str, float] = field(default_factory=dict)
    applicable: dict[str, bool] = field(default_factory=dict)
    locations: list[Location] = field(default_factory=list)
    lint_counts: dict[str, int] = field(default_factory=dict)
    version: str = MEASUREMENT_VERSION

    def to_dict(self, *, include_locations: bool = True) -> dict:
        data = {
            "words": self.words,
            "sentences": self.sentences,
            "paragraphs": self.paragraphs,
            "values": {k: round(v, 5) for k, v in self.values.items()},
            "applicable": dict(self.applicable),
            "lint_counts": dict(self.lint_counts),
            "version": self.version,
        }
        if include_locations:
            data["locations"] = [loc.to_dict() for loc in self.locations]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "NaturalnessMeasurement":
        return cls(
            words=int(data.get("words", 0)),
            sentences=int(data.get("sentences", 0)),
            paragraphs=int(data.get("paragraphs", 0)),
            values={k: float(v) for k, v in (data.get("values") or {}).items()},
            applicable={k: bool(v) for k, v in (data.get("applicable") or {}).items()},
            lint_counts={k: int(v) for k, v in (data.get("lint_counts") or {}).items()},
            version=str(data.get("version", MEASUREMENT_VERSION)),
        )

    @property
    def sufficient(self) -> bool:
        return self.words >= MIN_WORDS and self.sentences >= MIN_SENTENCES


def _cv(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    return statistics.pstdev(values) / mean if mean > 0 else 0.0


def _content_words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text) if w.lower() not in _STOPWORDS and len(w) > 2]


def _excerpt(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def measure_naturalness(text: str, *, lint: bool = True) -> NaturalnessMeasurement:
    """Measure one document. Pure, deterministic, local.

    `lint=False` skips the lint engine, for callers that only need the
    structural dimensions (the perturbation sensitivity suite uses the full
    measurement, so this is mainly for tests).
    """
    measurement = NaturalnessMeasurement()
    if not text or not text.strip():
        return measurement

    document = Document.parse(text)
    prose_paragraphs = [
        p
        for p in document.body_paragraphs()
        if not _HEADING.match(p.raw_text) and _WORD.search(p.raw_text)
    ]
    sentences: list[tuple[int, int, str]] = [
        (p.index, s.index, s.text)
        for p in prose_paragraphs
        for s in p.sentences
        if _WORD.search(s.text)
    ]
    lengths = [len(_WORD.findall(s)) for _, _, s in sentences]
    words = sum(len(_WORD.findall(p.raw_text)) for p in prose_paragraphs)

    measurement.words = words
    measurement.sentences = len(sentences)
    measurement.paragraphs = len(prose_paragraphs)
    if not sentences:
        return measurement

    values = measurement.values
    applicable = measurement.applicable
    locations = measurement.locations

    # --- variation ---
    values["sentence_variation"] = _cv([float(n) for n in lengths])
    paragraph_words = [float(len(_WORD.findall(p.raw_text))) for p in prose_paragraphs]
    values["paragraph_variation"] = _cv(paragraph_words)

    # --- repeated openings ---
    openings: dict[str, list[tuple[int, int, str]]] = {}
    for p_index, s_index, sentence in sentences:
        tokens = _WORD.findall(sentence)
        if len(tokens) < 2:
            continue
        openings.setdefault(" ".join(t.lower() for t in tokens[:2]), []).append(
            (p_index, s_index, sentence)
        )
    repeats = sum(len(group) - 1 for group in openings.values() if len(group) > 1)
    values["opening_repetition"] = repeats / len(sentences)
    for key, group in openings.items():
        if len(group) >= 3:
            for p_index, s_index, sentence in group:
                locations.append(
                    Location(
                        "opening_repetition",
                        p_index,
                        s_index,
                        f"one of {len(group)} sentences opening with the same two words",
                        _excerpt(sentence),
                    )
                )

    # --- connectives and summary closers ---
    stock = [(p, s, t) for p, s, t in sentences if _STOCK_CONNECTIVES.match(t)]
    values["stock_transitions"] = len(stock) / len(sentences)
    for p_index, s_index, sentence in stock:
        locations.append(
            Location(
                "stock_transitions",
                p_index,
                s_index,
                "sentence opens with a stock connective",
                _excerpt(sentence),
            )
        )

    closers = 0
    multi_sentence = [p for p in prose_paragraphs if len(p.sentences) >= 2]
    for paragraph in multi_sentence:
        last = paragraph.sentences[-1].text
        if _SUMMARY_CLOSER.match(last):
            closers += 1
            locations.append(
                Location(
                    "conclusion_repetition",
                    paragraph.index,
                    paragraph.sentences[-1].index,
                    "paragraph ends by summarising itself",
                    _excerpt(last),
                )
            )

    # --- structure ---
    counts = [len(p.sentences) for p in prose_paragraphs]
    identical = sum(1 for a, b in zip(counts, counts[1:]) if a == b and a >= 2)
    values["structural_uniformity"] = identical / max(1, len(counts) - 1)

    # --- redundancy and cohesion ---
    content = _content_words(" ".join(t for _, _, t in sentences))
    trigrams = [tuple(content[i:i + 3]) for i in range(max(0, len(content) - 2))]
    if trigrams:
        seen: dict[tuple[str, ...], int] = {}
        for gram in trigrams:
            seen[gram] = seen.get(gram, 0) + 1
        values["redundancy"] = sum(c - 1 for c in seen.values() if c > 1) / len(trigrams)
    else:
        values["redundancy"] = 0.0

    overlaps: list[float] = []
    sentence_sets = [set(_content_words(t)) for _, _, t in sentences]
    for left, right in zip(sentence_sets, sentence_sets[1:]):
        if left and right:
            overlaps.append(len(left & right) / len(left | right))
    values["cohesion"] = statistics.mean(overlaps) if overlaps else 0.0

    # --- filler and readability ---
    prose = "\n\n".join(p.raw_text for p in prose_paragraphs)
    filler_hits = list(_FILLER.finditer(prose))
    values["filler_rate"] = len(filler_hits) * 100.0 / max(1, words)

    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in _WORD.findall(prose))
    values["readability_fit"] = (
        0.39 * (words / len(sentences)) + 11.8 * (syllables / max(1, words)) - 15.59
    )

    # --- lint-backed formulaic language ---
    formulaic = 0
    conclusion_lint = 0
    if lint:
        matches = LintEngine().run(document, default_config())
        for match in matches:
            measurement.lint_counts[match.rule_code] = (
                measurement.lint_counts.get(match.rule_code, 0) + 1
            )
            if match.rule_code in _FORMULAIC_CODES:
                formulaic += 1
                locations.append(
                    Location(
                        "formulaic_density",
                        match.paragraph_index,
                        match.sentence_index,
                        match.message,
                        _excerpt(match.matched_text or ""),
                    )
                )
            elif match.rule_code in _CONCLUSION_CODES:
                conclusion_lint += 1
            elif match.rule_code in _TRANSITION_CODES:
                locations.append(
                    Location(
                        "stock_transitions",
                        match.paragraph_index,
                        match.sentence_index,
                        match.message,
                        _excerpt(match.matched_text or ""),
                    )
                )
            elif match.rule_code in _STRUCTURE_CODES:
                locations.append(
                    Location(
                        "structural_uniformity",
                        match.paragraph_index,
                        None,
                        match.message,
                        "",
                    )
                )
    values["formulaic_density"] = formulaic * 1000.0 / max(1, words)
    values["conclusion_repetition"] = (
        (closers + conclusion_lint) / len(multi_sentence) if multi_sentence else 0.0
    )

    for name in DIMENSIONS:
        needed = _MIN_PARAGRAPHS.get(name, 0)
        applicable[name] = name in values and measurement.paragraphs >= needed
        if name == "cohesion" and not overlaps:
            applicable[name] = False

    measurement.locations.sort(
        key=lambda loc: (
            loc.paragraph_index if loc.paragraph_index is not None else -1,
            loc.sentence_index if loc.sentence_index is not None else -1,
        )
    )
    return measurement


# --- calibration ----------------------------------------------------------

#: Width, in natural-log units of word count, of the length kernel. A
#: reference document 1.8x longer or shorter carries weight e^-0.5 (0.61);
#: one 3.3x away carries e^-2 (0.14). Chosen a priori so that a document is
#: ranked mainly against references within about a factor of two of its
#: length, and reported with every calibration.
LENGTH_BANDWIDTH = 0.6

#: A score needs at least this many comparable reference documents at the
#: document's length, counted as the sum of kernel weights (a reference of the
#: same length counts 1, one 1.8x away counts 0.61). An absolute count, not
#: the Kish effective sample size: Kish is scale-invariant, so thirty
#: references all far shorter than the document would still count as ~30.
MIN_EFFECTIVE_REFERENCE = 8.0


def _kernel(words: int, other: int) -> float:
    distance = math.log(max(words, 1) / max(other, 1))
    return math.exp(-0.5 * (distance / LENGTH_BANDWIDTH) ** 2)


def _weighted_rank(value: float, pairs: list[tuple[float, float]]) -> float:
    """Weighted share of reference values below `value`, ties counted half."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.5
    below = sum(w for v, w in pairs if v < value)
    equal = sum(w for v, w in pairs if v == value)
    return (below + 0.5 * equal) / total


def _tail(name: str, value: float, pairs: list[tuple[float, float]]) -> float:
    """How natural `value` is on one dimension, as a weighted reference tail."""
    direction = DIMENSIONS[name].direction
    rank = _weighted_rank(value, pairs)
    if direction == HIGH_IS_MECHANICAL:
        return 1.0 - rank
    if direction == LOW_IS_MECHANICAL:
        return rank
    return min(1.0, 2.0 * min(rank, 1.0 - rank))


def _index(
    measurement: NaturalnessMeasurement, reference: list[dict], skip: int | None = None
) -> tuple[float, dict[str, float]]:
    """Mean dimension tail against length-weighted reference documents."""
    tails: dict[str, float] = {}
    for name in DIMENSIONS:
        if not measurement.applicable.get(name):
            continue
        pairs = [
            (float(doc["values"][name]), _kernel(measurement.words, int(doc["words"])))
            for position, doc in enumerate(reference)
            if position != skip and (doc.get("applicable") or {}).get(name)
        ]
        if len(pairs) < 3:
            continue
        tails[name] = _tail(name, measurement.values[name], pairs)
    if not tails:
        return 0.5, tails
    return statistics.mean(tails.values()), tails


@dataclass
class NaturalnessCalibration:
    """A reference set, reduced to numbers, and the score mapping it implies.

    Holds each reference document's word count and dimension values, and its
    leave-one-out index. Every percentile is length-weighted: a document is
    ranked against reference documents of comparable length, because on a
    real corpus document length (and the genre that comes with it) correlated
    with the unweighted index at rho -0.67. No text, no titles, no paths.
    """

    context: str
    source: str
    reference_docs: list[dict] = field(default_factory=list)
    loo: list[dict] = field(default_factory=list)
    documents: int = 0
    validation: dict[str, Any] = field(default_factory=dict)
    version: str = CALIBRATION_VERSION
    measurement_version: str = MEASUREMENT_VERSION

    @property
    def reference(self) -> dict[str, list[float]]:
        """Unweighted per-dimension values, for descriptive display."""
        out: dict[str, list[float]] = {name: [] for name in DIMENSIONS}
        for doc in self.reference_docs:
            for name in DIMENSIONS:
                if (doc.get("applicable") or {}).get(name):
                    out[name].append(float(doc["values"][name]))
        return out

    @property
    def loo_indices(self) -> list[float]:
        return [float(item["index"]) for item in self.loo]

    @property
    def usable(self) -> bool:
        return self.documents >= MIN_REFERENCE_DOCUMENTS and len(self.loo) >= MIN_REFERENCE_DOCUMENTS

    def effective_reference(self, words: int) -> float:
        """Kernel-weighted count of reference documents comparable in length."""
        return sum(_kernel(words, int(item["words"])) for item in self.loo)

    def score_index(self, index: float, words: int) -> float:
        pairs = [(float(item["index"]), _kernel(words, int(item["words"]))) for item in self.loo]
        return 100.0 * _weighted_rank(index, pairs)

    def to_dict(self) -> dict:
        return {
            "context": self.context,
            "source": self.source,
            "reference_docs": [
                {
                    "words": int(doc["words"]),
                    "values": {k: round(float(v), 5) for k, v in doc["values"].items()},
                    "applicable": dict(doc.get("applicable") or {}),
                }
                for doc in self.reference_docs
            ],
            "loo": [{"words": int(i["words"]), "index": round(float(i["index"]), 5)} for i in self.loo],
            "documents": self.documents,
            "length_bandwidth": LENGTH_BANDWIDTH,
            "validation": self.validation,
            "version": self.version,
            "measurement_version": self.measurement_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NaturalnessCalibration":
        return cls(
            context=str(data.get("context", "")),
            source=str(data.get("source", "")),
            reference_docs=list(data.get("reference_docs") or []),
            loo=list(data.get("loo") or []),
            documents=int(data.get("documents", 0)),
            validation=dict(data.get("validation") or {}),
            version=str(data.get("version", CALIBRATION_VERSION)),
            measurement_version=str(data.get("measurement_version", MEASUREMENT_VERSION)),
        )


def _doc_record(measurement: NaturalnessMeasurement) -> dict:
    return {
        "words": measurement.words,
        "values": dict(measurement.values),
        "applicable": dict(measurement.applicable),
    }


def build_calibration(
    measurements: list[NaturalnessMeasurement],
    *,
    context: str,
    source: str,
    controls: dict[str, list[NaturalnessMeasurement]] | None = None,
) -> NaturalnessCalibration:
    """Calibrate against reference documents, and validate against controls.

    `controls` maps a control family name (a perturbation, or documents the
    user attested were AI-generated) to its measurements. Each family is
    scored with the finished calibration and the separation from the
    reference's own leave-one-out scores is reported as an AUC.
    """
    usable = [m for m in measurements if m.sufficient]
    reference = [_doc_record(m) for m in usable]
    loo = [
        {"words": item.words, "index": _index(item, reference, skip=i)[0]}
        for i, item in enumerate(usable)
    ]
    calibration = NaturalnessCalibration(
        context=context, source=source, reference_docs=reference, loo=loo, documents=len(usable),
    )

    # Each reference document's own score, leave-one-out: its index ranked
    # against the other documents' LOO indices.
    reference_scores = []
    for position, item in enumerate(loo):
        others = [o for i, o in enumerate(loo) if i != position]
        pairs = [(float(o["index"]), _kernel(int(item["words"]), int(o["words"]))) for o in others]
        reference_scores.append(100.0 * _weighted_rank(float(item["index"]), pairs))
    words = [m.words for m in usable]
    validation: dict[str, Any] = {
        "reference_scores": describe(reference_scores),
        "length_bandwidth": LENGTH_BANDWIDTH,
        "length_correlation": _spearman(words, reference_scores) if len(words) >= 5 else None,
        "controls": {},
    }
    pooled: list[float] = []
    for family, items in sorted((controls or {}).items()):
        scores = [
            calibration.score_index(_index(item, reference)[0], item.words)
            for item in items if item.sufficient
        ]
        pooled.extend(scores)
        validation["controls"][family] = {
            "scores": describe(scores),
            "separation": separation(reference_scores, scores).to_dict(),
        }
    pooled_separation = separation(reference_scores, pooled)
    validation["pooled_separation"] = pooled_separation.to_dict()
    interval = pooled_separation.interval
    validation["validated"] = bool(interval and interval[0] >= VALIDATED_AUC_FLOOR)
    calibration.validation = validation
    return calibration


def _spearman(x: list[float], y: list[float]) -> float | None:
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    try:
        return round(statistics.correlation(ranks(list(x)), ranks(list(y))), 3)
    except statistics.StatisticsError:
        return None


# --- scoring ---------------------------------------------------------------


@dataclass
class DimensionScore:
    name: str
    label: str
    value: float
    reference_median: float | None
    reference_p10: float | None
    reference_p90: float | None
    score: float | None
    direction: str
    measures: str

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("value", "reference_median", "reference_p10", "reference_p90", "score"):
            if isinstance(data[key], float):
                data[key] = round(data[key], 4 if key != "score" else 1)
        return data


@dataclass
class NaturalnessReport:
    status: str
    score: float | None
    context: str
    reason: str = ""
    calibration_version: str = CALIBRATION_VERSION
    calibration_source: str = ""
    reference_documents: int = 0
    evidence: str = "insufficient"
    confidence: str = "NONE"
    confidence_basis: str = ""
    dimensions: list[DimensionScore] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    words: int = 0
    #: Points one comparable reference document is worth: the score cannot be
    #: more precise than this, and small edits can move it by a few steps.
    resolution: float | None = None
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return {
            "metric": "human_naturalness",
            "resolution": None if self.resolution is None else round(self.resolution, 1),
            "status": self.status,
            "score": None if self.score is None else round(self.score, 1),
            "context": self.context,
            "reason": self.reason,
            "calibration_version": self.calibration_version,
            "calibration_source": self.calibration_source,
            "reference_documents": self.reference_documents,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "locations": [loc.to_dict() for loc in self.locations],
            "suggestions": list(self.suggestions),
            "words": self.words,
            "disclaimer": self.disclaimer,
        }


def score_naturalness(
    measurement: NaturalnessMeasurement,
    calibration: NaturalnessCalibration | None,
    *,
    context: str,
) -> NaturalnessReport:
    """Turn a measurement into a report, with a number only when supported."""
    report = NaturalnessReport(
        status=STATUS_UNAVAILABLE,
        score=None,
        context=context,
        words=measurement.words,
    )
    reference = calibration.reference if calibration else {}

    docs = calibration.reference_docs if calibration else []
    for name, spec in DIMENSIONS.items():
        if not measurement.applicable.get(name):
            continue
        values = reference.get(name) or []
        pairs = [
            (float(d["values"][name]), _kernel(measurement.words, int(d["words"])))
            for d in docs if (d.get("applicable") or {}).get(name)
        ]
        tail = _tail(name, measurement.values[name], pairs) if len(pairs) >= 3 else None
        report.dimensions.append(
            DimensionScore(
                name=name,
                label=spec.label,
                value=measurement.values[name],
                reference_median=quantile(values, 0.5) if values else None,
                reference_p10=quantile(values, 0.10) if values else None,
                reference_p90=quantile(values, 0.90) if values else None,
                score=None if tail is None else 100.0 * tail,
                direction=spec.direction,
                measures=spec.measures,
            )
        )
        if tail is None:
            continue
        if tail < 0.10:
            report.weaknesses.append(f"{spec.label}: {spec.weakness}")
            report.suggestions.append(spec.suggestion)
        elif tail >= 0.60:
            report.strengths.append(
                f"{spec.label}: at least as natural as most reference documents"
            )

    flagged = {d.name for d in report.dimensions if d.score is not None and d.score < 10.0}
    report.locations = [loc for loc in measurement.locations if loc.kind in flagged][:60]

    if not measurement.sufficient:
        report.reason = (
            f"document has {measurement.words} words and {measurement.sentences} sentences; "
            f"a score needs at least {MIN_WORDS} words and {MIN_SENTENCES} sentences, so "
            "only descriptive measurements are shown"
        )
        return report
    if calibration is None:
        report.reason = (
            "no naturalness calibration exists for this context; descriptive "
            "measurements are shown but there is no reference set to rank them against"
        )
        return report
    report.calibration_source = calibration.source
    report.reference_documents = calibration.documents
    report.calibration_version = calibration.version
    if not calibration.usable:
        report.reason = (
            f"the reference set has {calibration.documents} usable documents; a calibrated "
            f"score needs at least {MIN_REFERENCE_DOCUMENTS}"
        )
        report.evidence = "insufficient_reference"
        return report

    effective = calibration.effective_reference(measurement.words)
    if effective < MIN_EFFECTIVE_REFERENCE:
        report.reason = (
            f"the reference set has too few documents of comparable length ({effective:.1f} "
            f"comparable documents at {measurement.words} words; a score needs "
            f"{MIN_EFFECTIVE_REFERENCE:.0f})"
        )
        report.evidence = "insufficient_reference_at_length"
        return report
    index, _tails = _index(measurement, calibration.reference_docs)
    report.score = calibration.score_index(index, measurement.words)
    report.resolution = 100.0 / effective
    report.status = STATUS_SCORED
    report.evidence = "sufficient" if calibration.documents >= 25 else "limited"

    pooled = (calibration.validation or {}).get("pooled_separation") or {}
    interval = pooled.get("interval_95")
    if calibration.validation.get("validated"):
        report.confidence = "VALIDATED"
        report.confidence_basis = (
            f"statistical: separates reference writing from {pooled.get('control_n')} "
            f"mechanical controls with AUC {pooled.get('auc')} (95% interval {interval}); "
            f"reference n={calibration.documents}"
        )
    elif pooled.get("auc") is not None:
        report.confidence = "UNVALIDATED"
        report.confidence_basis = (
            f"statistical: control separation AUC {pooled.get('auc')} (95% interval "
            f"{interval}) does not clear the {VALIDATED_AUC_FLOOR} floor; treat the number "
            "as descriptive"
        )
    else:
        report.confidence = "UNVALIDATED"
        report.confidence_basis = (
            "heuristic: no controls were available to test whether this calibration "
            "separates mechanical prose from the reference"
        )
    return report
