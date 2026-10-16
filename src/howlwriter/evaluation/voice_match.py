"""Personal Voice Match: how close a document sits to one person's profile.

What the number means, exactly. The Voice Match Score is an empirical
percentile against the author's own unseen writing. A document scoring 40 is
at least as close to the profile as 40% of that author's held-out documents
were (each training document measured leave-one-out, each holdout document
against the full profile). 50 is a typical document by that author; a
genuine document is as likely to score 20 as 80, because that is how much one
person's documents differ from each other.

The bands make that usable:

* WITHIN_RANGE   score >= 25: as close as most of the author's own writing
* EDGE_OF_RANGE  10 <= score < 25: further than most, still inside the range
* ATYPICAL       score < 10: further than 90% of the author's own documents

What it does not mean. It is not authorship detection and never the
probability that this person wrote the document. Separately, the report says
what share of comparison-author documents were at least as close, which is
how a reader can see whether the profile discriminates at all.

When there is no number:

* the profile has fewer than `MIN_CALIBRATION_DOCUMENTS` genuine calibration
  distances;
* the document is shorter than `MIN_WORDS`;
* the document is one the profile was trained on, or a near-duplicate of one
  (scoring it would measure the profile's memory, not its fit);
* the profile was validated against comparison documents and failed to
  separate them (upper bound of the AUC interval below `FAILED_AUC_CEILING`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import statistics
from typing import Any, Iterable

from howlwriter.evaluation.empirical import (
    RobustCentre,
    describe,
    midrank_percentile,
    robust_centre,
    separation,
    survival,
)
from howlwriter.voice.corpus.dedup import content_hash, hamming, shingles, simhash
from howlwriter.voice.corpus.features import DocumentFeatures, extract_features

MEASUREMENT_VERSION = "voice-match-measure/v1"
CALIBRATION_VERSION = "voice-match-calibration/v1"

MIN_WORDS = 300
MIN_CALIBRATION_DOCUMENTS = 8
#: Validation outcome thresholds on the AUC of genuine vs comparison documents.
VALIDATED_AUC_FLOOR = 0.70
FAILED_AUC_CEILING = 0.60
#: SimHash distance at or below which an evaluated document counts as a
#: near-duplicate of a training document. Tighter than dedup's revision
#: threshold because a false "contaminated" only withholds a number.
NEAR_DUPLICATE_BITS = 8

STATUS_SCORED = "SCORED"
STATUS_UNAVAILABLE = "UNAVAILABLE"

WITHIN_RANGE = "WITHIN_RANGE"
EDGE_OF_RANGE = "EDGE_OF_RANGE"
ATYPICAL = "ATYPICAL"

DISCLAIMER = (
    "Voice Match ranks how close the document is to this profile against the "
    "author's own held-out writing. It is a similarity measure, not authorship "
    "detection, and not the probability that the author wrote the document."
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_HEDGES = re.compile(
    r"\b(?:may|might|could|likely|unlikely|possibly|perhaps|probably|appears?|"
    r"seems?|suggests?|generally|typically|tends? to|somewhat|relatively|"
    r"arguably|approximately|roughly)\b",
    re.IGNORECASE,
)
#: Technical tokens: acronyms, identifiers with digits, CamelCase, paths,
#: versions, dotted names. A proxy for technical specificity, not a lexicon.
_TECHNICAL = re.compile(
    r"(?<![\w/])(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Za-z]+\d+[A-Za-z0-9.]*|"
    r"[a-z]+[A-Z][A-Za-z]+|[\w.-]*/[\w./-]+|v?\d+\.\d+(?:\.\d+)*|"
    r"[a-z_]+\.[a-z_]+(?:\.[a-z_]+)*)(?![\w/])"
)

#: Dimensions reported to the user, and the features behind each. Each
#: dimension weighs equally in the overall distance, so a family measured by
#: many features does not dominate one measured by a single feature.
DIMENSIONS: dict[str, tuple[str, ...]] = {
    "sentence_cadence": ("sentence_length_mean", "sentence_length_stdev"),
    "sentence_distribution": (
        "sentence_length_median",
        "sentence_length_p10",
        "sentence_length_p90",
        "short_sentence_rate",
        "long_sentence_rate",
    ),
    "paragraph_structure": (
        "paragraph_words_mean",
        "paragraph_sentences_mean",
        "single_sentence_paragraph_rate",
    ),
    "punctuation": (
        "comma_rate",
        "semicolon_rate",
        "colon_rate",
        "em_dash_rate",
        "parenthetical_rate",
        "question_rate",
    ),
    "lexical": ("lexical_diversity", "mean_word_length", "long_word_rate"),
    "technical_vocabulary": ("technical_token_rate",),
    "register": ("contraction_rate", "first_person_rate", "second_person_rate", "passive_rate"),
    "hedging_and_directness": (
        "hedging_rate",
        "sentence_initial_conjunction_rate",
        "fragment_rate",
    ),
    "transitions": ("transition_rate",),
    "structure": ("list_rate", "heading_rate"),
    "readability": ("readability_grade",),
}

DIMENSION_LABELS = {
    "sentence_cadence": "Sentence cadence",
    "sentence_distribution": "Sentence-length distribution",
    "paragraph_structure": "Paragraph structure",
    "punctuation": "Punctuation habits",
    "lexical": "Word choice and diversity",
    "technical_vocabulary": "Technical vocabulary",
    "register": "Register and person",
    "hedging_and_directness": "Hedging and directness",
    "transitions": "Transitions",
    "structure": "Lists and headings",
    "readability": "Reading level",
}

#: Minimum robust scale per feature. Small corpora and near-zero rates would
#: otherwise produce near-zero scales, and one semicolon would read as a
#: dramatic departure.
SCALE_FLOORS: dict[str, float] = {
    "sentence_length_mean": 1.5,
    "sentence_length_stdev": 1.0,
    "sentence_length_median": 1.5,
    "sentence_length_p10": 1.0,
    "sentence_length_p90": 2.0,
    "short_sentence_rate": 0.03,
    "long_sentence_rate": 0.03,
    "paragraph_words_mean": 8.0,
    "paragraph_sentences_mean": 0.4,
    "single_sentence_paragraph_rate": 0.05,
    "comma_rate": 0.4,
    "semicolon_rate": 0.05,
    "colon_rate": 0.1,
    "em_dash_rate": 0.05,
    "parenthetical_rate": 0.1,
    "question_rate": 0.01,
    "lexical_diversity": 0.015,
    "mean_word_length": 0.08,
    "long_word_rate": 0.01,
    "technical_token_rate": 0.3,
    "contraction_rate": 0.1,
    "first_person_rate": 0.2,
    "second_person_rate": 0.1,
    "passive_rate": 0.03,
    "hedging_rate": 0.1,
    "sentence_initial_conjunction_rate": 0.01,
    "fragment_rate": 0.01,
    "transition_rate": 0.02,
    "list_rate": 0.03,
    "heading_rate": 0.02,
    "readability_grade": 0.6,
}

FEATURES: tuple[str, ...] = tuple(f for features in DIMENSIONS.values() for f in features)


def extra_features(text: str) -> dict[str, float]:
    """Features the corpus pipeline does not already measure."""
    words = len(_WORD.findall(text))
    per_100 = 100.0 / words if words else 0.0
    return {
        "hedging_rate": len(_HEDGES.findall(text)) * per_100,
        "technical_token_rate": len(_TECHNICAL.findall(text)) * per_100,
    }


def vector_from(features: DocumentFeatures | dict, extras: dict[str, float]) -> dict[str, float]:
    base = features.to_dict() if isinstance(features, DocumentFeatures) else dict(features)
    merged = {**base, **extras}
    return {name: float(merged.get(name, 0.0) or 0.0) for name in FEATURES}


def measure_text(text: str) -> tuple[dict[str, float], int]:
    """Voice-match vector and word count for one cleaned document."""
    features = extract_features(text)
    return vector_from(features, extra_features(text)), features.words


@dataclass
class TextFingerprint:
    """Identity of a text for contamination checks. Hashes only."""

    content_hash: str
    simhash: int
    words: int

    def to_dict(self) -> dict:
        return {
            "content_hash": self.content_hash,
            "simhash": format(self.simhash, "016x"),
            "words": self.words,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TextFingerprint":
        return cls(
            content_hash=str(data.get("content_hash", "")),
            simhash=int(str(data.get("simhash", "0")), 16),
            words=int(data.get("words", 0)),
        )

    @classmethod
    def of(cls, text: str) -> "TextFingerprint":
        return cls(
            content_hash=content_hash(text),
            simhash=simhash(shingles(text)),
            words=len(_WORD.findall(text)),
        )


def _centres(vectors: list[dict[str, float]]) -> dict[str, RobustCentre]:
    return {
        name: robust_centre([v[name] for v in vectors], floor=SCALE_FLOORS.get(name, 0.01))
        for name in FEATURES
    }


def distance(
    vector: dict[str, float], centres: dict[str, RobustCentre]
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Overall distance, per-dimension distance, and per-feature signed z."""
    zs = {name: centres[name].z(vector.get(name, 0.0)) for name in FEATURES}
    dims = {
        dim: statistics.mean(abs(zs[f]) for f in features) for dim, features in DIMENSIONS.items()
    }
    return statistics.mean(dims.values()), dims, zs


@dataclass
class VoiceMatchCalibration:
    """A profile's reference distribution, reduced to numbers and hashes."""

    profile: str
    context: str
    centres: dict[str, tuple[float, float]] = field(default_factory=dict)
    genuine_distances: list[float] = field(default_factory=list)
    control_distances: dict[str, list[float]] = field(default_factory=dict)
    training_fingerprints: list[TextFingerprint] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    training_documents: int = 0
    holdout_documents: int = 0
    version: str = CALIBRATION_VERSION
    measurement_version: str = MEASUREMENT_VERSION

    @property
    def robust_centres(self) -> dict[str, RobustCentre]:
        return {k: RobustCentre(m, s) for k, (m, s) in self.centres.items()}

    @property
    def usable(self) -> bool:
        return len(self.genuine_distances) >= MIN_CALIBRATION_DOCUMENTS and bool(self.centres)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "context": self.context,
            "centres": {k: [round(m, 5), round(s, 5)] for k, (m, s) in self.centres.items()},
            "genuine_distances": [round(v, 5) for v in self.genuine_distances],
            "control_distances": {
                k: [round(v, 5) for v in vals] for k, vals in self.control_distances.items()
            },
            "training_fingerprints": [fp.to_dict() for fp in self.training_fingerprints],
            "validation": self.validation,
            "training_documents": self.training_documents,
            "holdout_documents": self.holdout_documents,
            "version": self.version,
            "measurement_version": self.measurement_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceMatchCalibration":
        return cls(
            profile=str(data.get("profile", "")),
            context=str(data.get("context", "")),
            centres={k: (float(v[0]), float(v[1])) for k, v in (data.get("centres") or {}).items()},
            genuine_distances=[float(v) for v in data.get("genuine_distances") or []],
            control_distances={
                k: [float(v) for v in vals]
                for k, vals in (data.get("control_distances") or {}).items()
            },
            training_fingerprints=[
                TextFingerprint.from_dict(fp) for fp in data.get("training_fingerprints") or []
            ],
            validation=dict(data.get("validation") or {}),
            training_documents=int(data.get("training_documents", 0)),
            holdout_documents=int(data.get("holdout_documents", 0)),
            version=str(data.get("version", CALIBRATION_VERSION)),
            measurement_version=str(data.get("measurement_version", MEASUREMENT_VERSION)),
        )

    def score_distance(self, value: float) -> float:
        """Share of genuine calibration distances at least as large, x100."""
        return _score(value, self.genuine_distances)

    def validation_failed(self) -> bool:
        interval = (self.validation.get("pooled_separation") or {}).get("interval_95")
        return bool(interval and interval[1] < FAILED_AUC_CEILING)

    def validated(self) -> bool:
        return bool(self.validation.get("validated"))


def build_calibration(
    *,
    profile: str,
    context: str,
    training: list[dict[str, float]],
    holdout: Iterable[dict[str, float]] = (),
    controls: dict[str, list[dict[str, float]]] | None = None,
    training_fingerprints: Iterable[TextFingerprint] = (),
    diagnostic_controls: dict[str, list[dict[str, float]]] | None = None,
) -> VoiceMatchCalibration:
    """Calibrate a profile from its own documents and validate on controls.

    Training documents are measured leave-one-out (each against centres
    computed without it); holdout documents against the full centres. That is
    the genuine distribution the score is a percentile of. Controls are other
    authors' documents, documents the user attested were AI-generated, and the
    same author's documents from a different context; their distances say
    whether the profile discriminates at all.
    """
    holdout = list(holdout)
    centres = _centres(training) if training else {}
    genuine: list[float] = []
    if len(training) >= 3:
        for position in range(len(training)):
            rest = training[:position] + training[position + 1:]
            genuine.append(distance(training[position], _centres(rest))[0])
    for vector in holdout:
        if centres:
            genuine.append(distance(vector, centres)[0])

    calibration = VoiceMatchCalibration(
        profile=profile,
        context=context,
        centres={k: (c.median, c.scale) for k, c in centres.items()},
        genuine_distances=genuine,
        training_fingerprints=list(training_fingerprints),
        training_documents=len(training),
        holdout_documents=len(holdout),
    )

    genuine_scores = [calibration.score_distance(d) for d in genuine]
    validation: dict[str, Any] = {
        "genuine_distances": describe(genuine),
        "genuine_holdout_n": len(holdout),
        "genuine_loo_n": len(training) if len(training) >= 3 else 0,
        "controls": {},
    }
    pooled: list[float] = []
    for family, vectors in sorted((controls or {}).items()):
        if not centres:
            break
        distances = [distance(v, centres)[0] for v in vectors]
        calibration.control_distances[family] = distances
        scores = [calibration.score_distance(d) for d in distances]
        pooled.extend(scores)
        validation["controls"][family] = {
            "distances": describe(distances),
            "separation": separation(genuine_scores, scores).to_dict(),
        }
    # Diagnostics (e.g. mechanically altered copies of the author's own
    # held-out documents) test sensitivity to style change. They are reported
    # but never pooled: separating a person from a damaged copy of themselves
    # says nothing about separating them from someone else.
    validation["diagnostics"] = {}
    for family, vectors in sorted((diagnostic_controls or {}).items()):
        if not centres or not vectors:
            continue
        scores = [calibration.score_distance(distance(v, centres)[0]) for v in vectors]
        validation["diagnostics"][family] = {
            "scores": describe(scores),
            "separation": separation(genuine_scores, scores).to_dict(),
        }
    pooled_sep = separation(genuine_scores, pooled)
    validation["pooled_separation"] = pooled_sep.to_dict()
    interval = pooled_sep.interval
    validation["validated"] = bool(
        interval and interval[0] >= VALIDATED_AUC_FLOOR and pooled_sep.control_n >= 5
    )
    calibration.validation = validation
    return calibration


def _score(distance_value: float, genuine: list[float]) -> float:
    return 100.0 * survival(distance_value, genuine)


def band_for(score: float) -> str:
    if score >= 25.0:
        return WITHIN_RANGE
    if score >= 10.0:
        return EDGE_OF_RANGE
    return ATYPICAL


@dataclass
class VoiceDimension:
    name: str
    label: str
    distance: float
    typical_distance: float | None
    features: dict[str, dict[str, float]]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VoiceMatchReport:
    status: str
    score: float | None
    profile: str
    context: str
    reason: str = ""
    band: str = ""
    calibration_version: str = CALIBRATION_VERSION
    calibration_status: str = "NOT_CALIBRATED"
    evidence: str = "insufficient"
    confidence: str = "NONE"
    confidence_basis: str = ""
    distance: float | None = None
    comparison_share_as_close: float | None = None
    dimensions: list[VoiceDimension] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)
    drift: list[dict] = field(default_factory=list)
    words: int = 0
    #: Points one genuine calibration document is worth (100 / n).
    resolution: float | None = None
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return {
            "metric": "personal_voice_match",
            "resolution": None if self.resolution is None else round(self.resolution, 1),
            "status": self.status,
            "score": None if self.score is None else round(self.score, 1),
            "band": self.band,
            "profile": self.profile,
            "context": self.context,
            "reason": self.reason,
            "calibration_version": self.calibration_version,
            "calibration_status": self.calibration_status,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "distance": None if self.distance is None else round(self.distance, 4),
            "comparison_share_as_close": (
                None
                if self.comparison_share_as_close is None
                else round(self.comparison_share_as_close, 1)
            ),
            "dimensions": [d.to_dict() for d in self.dimensions],
            "differences": list(self.differences),
            "drift": list(self.drift),
            "words": self.words,
            "disclaimer": self.disclaimer,
        }


def contamination(fingerprint: TextFingerprint, calibration: VoiceMatchCalibration) -> str | None:
    for known in calibration.training_fingerprints:
        if known.content_hash == fingerprint.content_hash:
            return "this document is one of the profile's training documents"
        if hamming(known.simhash, fingerprint.simhash) <= NEAR_DUPLICATE_BITS:
            return "this document is a near-duplicate of one of the profile's training documents"
    return None


def score_voice_match(
    text: str,
    calibration: VoiceMatchCalibration | None,
    *,
    profile: str,
    context: str,
) -> VoiceMatchReport:
    vector, words = measure_text(text)
    report = VoiceMatchReport(
        status=STATUS_UNAVAILABLE,
        score=None,
        profile=profile,
        context=context,
        words=words,
    )
    if calibration is None or not calibration.centres:
        report.reason = (
            f"profile '{profile}' has no voice-match calibration; rebuild it with "
            "`howlwriter voice build-identity` to create one"
        )
        return report

    report.calibration_version = calibration.version
    overall, dims, zs = distance(vector, calibration.robust_centres)
    report.distance = overall
    typical = (
        statistics.median(calibration.genuine_distances) if calibration.genuine_distances else None
    )
    for dim, features in DIMENSIONS.items():
        report.dimensions.append(
            VoiceDimension(
                name=dim,
                label=DIMENSION_LABELS[dim],
                distance=round(dims[dim], 3),
                typical_distance=None if typical is None else round(typical, 3),
                features={
                    f: {
                        "value": round(vector[f], 4),
                        "profile_median": round(calibration.centres[f][0], 4),
                        "z": round(zs[f], 2),
                    }
                    for f in features
                },
            )
        )
        strongest = max(features, key=lambda f: abs(zs[f]))
        if dims[dim] >= 2.0:
            direction = "higher" if zs[strongest] > 0 else "lower"
            report.differences.append(
                f"{DIMENSION_LABELS[dim]}: {strongest.replace('_', ' ')} is markedly {direction} "
                f"than the profile ({vector[strongest]:.2f} vs typical "
                f"{calibration.centres[strongest][0]:.2f})"
            )

    if words < MIN_WORDS:
        report.reason = (
            f"document has {words} words; a voice-match score needs at least {MIN_WORDS} "
            "because shorter samples vary too much to rank"
        )
        return report
    leak = contamination(TextFingerprint.of(text), calibration)
    if leak:
        report.reason = f"{leak}; scoring it would measure the profile's memory, not its fit"
        report.calibration_status = "CONTAMINATED"
        return report
    if not calibration.usable:
        report.reason = (
            f"profile has {len(calibration.genuine_distances)} genuine calibration documents; "
            f"a calibrated score needs at least {MIN_CALIBRATION_DOCUMENTS}"
        )
        report.calibration_status = "INSUFFICIENT"
        return report
    if calibration.validation_failed():
        pooled = calibration.validation.get("pooled_separation") or {}
        report.reason = (
            "this profile did not separate the author's writing from comparison documents "
            f"(AUC {pooled.get('auc')}, 95% interval {pooled.get('interval_95')}), so a "
            "percentile would not mean anything"
        )
        report.calibration_status = "FAILED_VALIDATION"
        return report

    report.score = _score(overall, calibration.genuine_distances)
    report.resolution = 100.0 / len(calibration.genuine_distances)
    report.band = band_for(report.score)
    report.status = STATUS_SCORED
    n = len(calibration.genuine_distances)
    report.evidence = "sufficient" if n >= 20 else "limited"
    pooled_controls = [d for vals in calibration.control_distances.values() for d in vals]
    if pooled_controls:
        report.comparison_share_as_close = 100.0 * midrank_percentile(overall, pooled_controls)
    pooled = calibration.validation.get("pooled_separation") or {}
    if calibration.validated():
        report.calibration_status = "VALIDATED"
        report.confidence = "VALIDATED"
        report.confidence_basis = (
            f"statistical: {n} genuine calibration documents; separates the author's "
            f"held-out writing from {pooled.get('control_n')} comparison documents with "
            f"AUC {pooled.get('auc')} (95% interval {pooled.get('interval_95')})"
        )
    else:
        report.calibration_status = "CALIBRATED_UNVALIDATED"
        report.confidence = "UNVALIDATED"
        report.confidence_basis = (
            f"statistical percentile over {n} genuine calibration documents; "
            + (
                f"discrimination against comparison documents is not established "
                f"(AUC {pooled.get('auc')}, 95% interval {pooled.get('interval_95')}, "
                f"n={pooled.get('control_n')})"
                if pooled.get("auc") is not None
                else "no comparison documents were available, so discrimination is untested"
            )
        )
    return report
