"""HowlWriter empirical evaluation and benchmarking package."""

from howlwriter.evaluation.ablation import (
    AblationConfiguration,
    FULL_MINUS_HUMANIZER,
    FULL_MINUS_INDEPENDENT_REVIEW,
    FULL_MINUS_MEANING_PRESERVATION,
    FULL_MINUS_PROVENANCE,
    FULL_MINUS_RED_PEN,
    FULL_MINUS_SOURCE_VERIFICATION,
    FULL_MINUS_VOICE,
    get_ablation,
)
from howlwriter.evaluation.fixtures import (
    get_benchmark_suite,
    load_all_cases,
)
from howlwriter.evaluation.judges import (
    BenchmarkJudge,
    DeterministicJudge,
    ModelJudge,
    ScriptedJudge,
)
from howlwriter.evaluation.models import (
    BaselineType,
    BenchmarkCase,
    BenchmarkRun,
    BenchmarkSuite,
    CandidateOutput,
    CaseEvaluationResult,
    IndependenceStatus,
    MetricScore,
    PairwiseComparison,
)
from howlwriter.evaluation.reports import (
    compare_runs,
    generate_markdown_report,
    write_benchmark_reports,
)
from howlwriter.evaluation.runner import BenchmarkRunner

__all__ = [
    "AblationConfiguration",
    "BaselineType",
    "BenchmarkCase",
    "BenchmarkJudge",
    "BenchmarkRun",
    "BenchmarkRunner",
    "BenchmarkSuite",
    "CandidateOutput",
    "CaseEvaluationResult",
    "DeterministicJudge",
    "IndependenceStatus",
    "MetricScore",
    "ModelJudge",
    "PairwiseComparison",
    "ScriptedJudge",
    "compare_runs",
    "generate_markdown_report",
    "get_ablation",
    "get_benchmark_suite",
    "load_all_cases",
    "write_benchmark_reports",
    "FULL_MINUS_HUMANIZER",
    "FULL_MINUS_INDEPENDENT_REVIEW",
    "FULL_MINUS_MEANING_PRESERVATION",
    "FULL_MINUS_PROVENANCE",
    "FULL_MINUS_RED_PEN",
    "FULL_MINUS_SOURCE_VERIFICATION",
    "FULL_MINUS_VOICE",
]
