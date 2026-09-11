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


@dataclass
class MetricScore(DataClassSerializationMixin):
    """Score on a specific evaluation dimension for one candidate."""

    metric_name: str
    score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    deterministic: bool = True


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
