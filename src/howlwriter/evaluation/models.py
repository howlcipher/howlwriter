"""Typed concepts and data models for HowlWriter empirical evaluation.

Provides serializable domain representations for:
- BenchmarkCase
- CandidateOutput
- BaselineType
- MetricScore
- PairwiseComparison
- CaseEvaluationResult
- BenchmarkSuite
- BenchmarkRun
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
from typing import Any

from howlwriter.domain.modes import WritingMode, parse_mode
from howlwriter.domain.serialization import DataClassSerializationMixin


class BaselineType(str, enum.Enum):
    """Fair benchmark comparison baselines and variants."""

    RAW_MODEL = "raw_model"
    STRONG_PROMPT = "strong_prompt"
    HOWLWRITER_MINIMAL = "howlwriter_minimal"
    HOWLWRITER_FULL = "howlwriter_full"
    ABLATION = "ablation"


class IndependenceStatus(str, enum.Enum):
    """Recorded status of reviewer/judge independence."""

    INDEPENDENT = "INDEPENDENT"
    SAME_PROVIDER = "SAME_PROVIDER"
    NOT_REVIEWED = "NOT_REVIEWED"
    INDEPENDENCE_NOT_VERIFIABLE = "INDEPENDENCE_NOT_VERIFIABLE"


class EvaluatorHealth(str, enum.Enum):
    """Health classification for evaluation metrics based on calibration tests."""

    CALIBRATED = "CALIBRATED"
    PARTIALLY_CALIBRATED = "PARTIALLY_CALIBRATED"
    UNRELIABLE = "UNRELIABLE"


class EntailmentVerdict(str, enum.Enum):
    """Verdicts for semantic entailment and claim-evidence grounding."""

    ENTAILED = "ENTAILED"
    PARTIALLY_ENTAILED = "PARTIALLY_ENTAILED"
    NOT_ENTAILED = "NOT_ENTAILED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNAVAILABLE = "UNAVAILABLE"


class CostProvenance(str, enum.Enum):
    """Provenance category for cost and token telemetry."""

    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class ExecutionManifest(DataClassSerializationMixin):
    """Record proving which pipeline stages ran and which were genuinely bypassed."""

    system_id: str = ""
    writer: bool = True
    outline_enforcement: bool = True
    source_integrity: bool = True
    source_authority: bool = True
    voice: bool = True
    red_pen: bool = True
    meaning_review: bool = True
    independent_review: bool = True
    humanizer: bool = True
    provenance: bool = True
    bypassed_stages: list[str] = field(default_factory=list)


@dataclass
class EntailmentResult(DataClassSerializationMixin):
    """Detailed result of semantic entailment evaluation for a single claim."""

    verdict: EntailmentVerdict = EntailmentVerdict.UNAVAILABLE
    confidence: float = 1.0
    rationale: str = ""
    extracted_claim: str = ""
    matched_evidence: str = ""


@dataclass
class PositiveControl(DataClassSerializationMixin):
    """Known high-quality example that must score highly on a calibrated metric."""

    description: str = ""
    input_text: str = ""
    reference: str = ""
    expected_min_score: float = 0.7


@dataclass
class NegativeControl(DataClassSerializationMixin):
    """Known degraded/flawed example that must score poorly on a calibrated metric."""

    description: str = ""
    input_text: str = ""
    reference: str = ""
    expected_max_score: float = 0.4


@dataclass
class MetricCalibrationCase(DataClassSerializationMixin):
    """Pair of positive and negative controls for validating metric sensitivity."""

    metric_name: str
    positive_controls: list[PositiveControl] = field(default_factory=list)
    negative_controls: list[NegativeControl] = field(default_factory=list)


@dataclass
class MetricSensitivityResult(DataClassSerializationMixin):
    """Evaluator health diagnostic certifying whether a metric reliably discriminates."""

    metric_name: str
    health: EvaluatorHealth = EvaluatorHealth.UNRELIABLE
    positive_controls_passed: int = 0
    positive_controls_total: int = 0
    negative_controls_passed: int = 0
    negative_controls_total: int = 0
    sensitivity_gap: float = 0.0  # Mean positive score minus mean negative score
    notes: str = ""

    def is_healthy(self) -> bool:
        return self.health == EvaluatorHealth.CALIBRATED


@dataclass
class BenchmarkCase(DataClassSerializationMixin):
    """A single evaluation task with explicit, unmemorizable requirements."""

    id: str
    mode: str = "academic"
    category: str = "academic/research"
    task: str = ""
    input_text: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    outline: dict[str, Any] | None = None
    assignment_spec: dict[str, Any] | None = None
    source_corpus: list[dict[str, Any]] = field(default_factory=list)
    requirements: dict[str, Any] = field(default_factory=dict)
    metrics: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def resolved_mode(self) -> WritingMode:
        return parse_mode(self.mode)


@dataclass
class CandidateOutput(DataClassSerializationMixin):
    """The generated prose and execution telemetry from one system for a case."""

    candidate_id: str  # Blinded identifier (e.g. "Candidate A", "Candidate B")
    system_id: str  # Real system (e.g. "raw_model", "howlwriter_full")
    text: str = ""
    latency_seconds: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)  # prompt, completion, total
    model_calls: int = 0
    retrieval_calls: int = 0
    verification_calls: int = 0
    estimated_cost: float = 0.0
    provider: str | None = None
    model: str | None = None
    success: bool = True
    failure_classification: str | None = None
    extra_artifacts: dict[str, Any] = field(default_factory=dict)
    execution_manifest: ExecutionManifest | None = None
    stage_timings: dict[str, float] = field(default_factory=dict)
    cost_provenance: str = CostProvenance.ESTIMATED.value


@dataclass
class MetricScore(DataClassSerializationMixin):
    """Score on a specific evaluation dimension for one candidate."""

    metric_name: str
    score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    deterministic: bool = True
    metric_version: str = "v1"


@dataclass
class PairwiseComparison(DataClassSerializationMixin):
    """Blinded pairwise evaluation between two candidates on subjective quality."""

    case_id: str
    candidate_a_system: str
    candidate_b_system: str
    winner: str = "TIE"  # "A", "B", "TIE", "INCONCLUSIVE"
    winning_system: str = "TIE"  # system_id of winner or "TIE" / "INCONCLUSIVE"
    dimension_scores: dict[str, str] = field(default_factory=dict)
    rationale: str = ""
    judge_role: str = "final_reviewer"
    judge_provider: str = ""
    judge_model: str = ""
    independence_status: str = IndependenceStatus.INDEPENDENCE_NOT_VERIFIABLE.value
    position_order: list[str] = field(default_factory=list)  # [system_for_A, system_for_B]


@dataclass
class CaseEvaluationResult(DataClassSerializationMixin):
    """Complete evaluation outcome for one benchmark case in one repetition."""

    case_id: str
    repetition_index: int = 0
    candidate_outputs: dict[str, CandidateOutput] = field(default_factory=dict)
    metric_scores: dict[str, dict[str, MetricScore]] = field(default_factory=dict)
    pairwise_comparisons: list[PairwiseComparison] = field(default_factory=list)


@dataclass
class BenchmarkSuite(DataClassSerializationMixin):
    """A named collection of benchmark cases."""

    name: str
    description: str = ""
    cases: list[BenchmarkCase] = field(default_factory=list)


@dataclass
class BenchmarkRun(DataClassSerializationMixin):
    """Complete serializable record of a benchmark suite execution."""

    run_id: str
    suite_name: str
    timestamp: str
    git_commit: str | None = None
    howlwriter_version: str = "0.1.0"
    baselines: list[str] = field(default_factory=list)
    ablations: list[str] = field(default_factory=list)
    repeat: int = 1
    deterministic_only: bool = False
    case_results: list[CaseEvaluationResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
