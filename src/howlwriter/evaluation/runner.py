"""Benchmark execution engine coordinating baselines, metrics, and judging."""

from __future__ import annotations

from datetime import datetime, timezone
import random
import time
from typing import Any, Callable, Sequence

from howlwriter.diagnostic.run_record import (
    compute_sha256,
    generate_run_id,
    get_git_revision,
    get_howlwriter_version,
)
from howlwriter.evaluation.ablation import get_ablation
from howlwriter.evaluation.baselines import BaselineRunner
from howlwriter.evaluation.judges import (
    BenchmarkJudge,
    DeterministicJudge,
    ModelJudge,
)
from howlwriter.evaluation.metrics import (
    EVALUATORS,
    StructuralDiversityEvaluator,
    get_evaluator,
)
from howlwriter.evaluation.models import (
    BaselineType,
    BenchmarkCase,
    BenchmarkRun,
    BenchmarkSuite,
    CandidateOutput,
    CaseEvaluationResult,
    MetricScore,
    PairwiseComparison,
)
from howlwriter.evaluation.statistics import (
    bootstrap_mean_diff_ci,
    cliffs_delta,
    cohens_d,
    compute_descriptive_stats,
    determine_verdict,
    wilson_score_interval,
)


class BenchmarkRunner:
    """Coordinates running a benchmark suite against baselines and judging results."""

    def __init__(
        self,
        judge: BenchmarkJudge | None = None,
        mock_generator: Callable[[str, str], str] | None = None,
        deterministic_only: bool = False,
    ) -> None:
        self.deterministic_only = deterministic_only
        if deterministic_only:
            self.judge = DeterministicJudge()
        else:
            self.judge = judge if judge is not None else ModelJudge()
        self.baseline_runner = BaselineRunner(mock_generator=mock_generator)

    def run_suite(
        self,
        suite: BenchmarkSuite,
        baselines: Sequence[str] = ("raw_model", "strong_prompt", "howlwriter_full"),
        ablations: Sequence[str] = (),
        repeat: int = 1,
        seed: int = 42,
    ) -> BenchmarkRun:
        """Executes the benchmark suite across all requested systems and repetitions."""
        run_id = generate_run_id().replace("hw-", "bench-")
        timestamp = datetime.now(timezone.utc).isoformat()
        git_commit = get_git_revision()
        hw_version = get_howlwriter_version()

        case_results: list[CaseEvaluationResult] = []
        outputs_by_system: dict[str, list[CandidateOutput]] = {b: [] for b in baselines}
        for a in ablations:
            outputs_by_system[f"ablation_{a}"] = []

        all_systems = list(baselines) + [f"ablation_{a}" for a in ablations]

        for rep in range(repeat):
            for case in suite.cases:
                cand_outputs: dict[str, CandidateOutput] = {}
                metric_scores: dict[str, dict[str, MetricScore]] = {}

                # 1. Execute each baseline / ablation
                for baseline_id in baselines:
                    cand = self._execute_candidate(case, baseline_id)
                    cand_outputs[baseline_id] = cand
                    outputs_by_system[baseline_id].append(cand)

                for ablation_name in ablations:
                    sys_id = f"ablation_{ablation_name}"
                    ab_cfg = get_ablation(ablation_name)
                    cand = self.baseline_runner.run_howlwriter_full(case, ablation=ab_cfg)
                    cand_outputs[sys_id] = cand
                    outputs_by_system[sys_id].append(cand)

                # 2. Evaluate deterministic metrics for all candidates
                for sys_id, cand in cand_outputs.items():
                    metric_scores[sys_id] = {}
                    metrics_to_run = case.metrics if case.metrics else list(EVALUATORS.keys())
                    for metric_name in metrics_to_run:
                        if metric_name == "structural_diversity":
                            continue  # Evaluated over batches
                        evaluator = get_evaluator(metric_name)
                        if evaluator is not None:
                            try:
                                score = evaluator.evaluate(case, cand)
                                metric_scores[sys_id][metric_name] = score
                            except Exception as err:
                                metric_scores[sys_id][metric_name] = MetricScore(
                                    metric_name=metric_name,
                                    score=0.0,
                                    details={"error": str(err)},
                                    deterministic=True,
                                )

                # 3. Blinded Pairwise Judging (Full HW vs Strong Prompt, Full HW vs Raw Model)
                pairwise_comps: list[PairwiseComparison] = []
                primary_hw = "howlwriter_full" if "howlwriter_full" in cand_outputs else None
                if primary_hw and cand_outputs[primary_hw].success:
                    for comp_sys in ("strong_prompt", "raw_model", "howlwriter_minimal"):
                        if comp_sys in cand_outputs and cand_outputs[comp_sys].success:
                            comp = self.judge.judge(
                                case=case,
                                cand_1=cand_outputs[primary_hw],
                                cand_2=cand_outputs[comp_sys],
                                seed=seed + rep + len(case_results),
                            )
                            pairwise_comps.append(comp)

                case_res = CaseEvaluationResult(
                    case_id=case.id,
                    repetition_index=rep,
                    candidate_outputs=cand_outputs,
                    metric_scores=metric_scores,
                    pairwise_comparisons=pairwise_comps,
                )
                case_results.append(case_res)

        # 4. Batch Structural Diversity Evaluation per system
        diversity_evaluator = StructuralDiversityEvaluator()
        structural_diversity_scores: dict[str, MetricScore] = {}
        for sys_id, outputs in outputs_by_system.items():
            structural_diversity_scores[sys_id] = diversity_evaluator.evaluate_batch(outputs)

        # 5. Statistical Aggregation & Summary
        summary = self._build_summary(
            case_results=case_results,
            systems=all_systems,
            diversity_scores=structural_diversity_scores,
            outputs_by_system=outputs_by_system,
        )

        return BenchmarkRun(
            run_id=run_id,
            suite_name=suite.name,
            timestamp=timestamp,
            git_commit=git_commit,
            howlwriter_version=hw_version,
            baselines=list(baselines),
            ablations=list(ablations),
            repeat=repeat,
            deterministic_only=self.deterministic_only,
            case_results=case_results,
            summary=summary,
        )

    def _execute_candidate(self, case: BenchmarkCase, baseline_id: str) -> CandidateOutput:
        norm = baseline_id.strip().lower()
        if norm == "raw_model":
            return self.baseline_runner.run_raw_model(case)
        if norm == "strong_prompt":
            return self.baseline_runner.run_strong_prompt(case)
        if norm == "howlwriter_minimal":
            return self.baseline_runner.run_howlwriter_minimal(case)
        if norm == "howlwriter_full":
            return self.baseline_runner.run_howlwriter_full(case)
        # Check if it is a named ablation
        ab_cfg = get_ablation(norm)
        if ab_cfg:
            return self.baseline_runner.run_howlwriter_full(case, ablation=ab_cfg)
        return self.baseline_runner.run_strong_prompt(case)

    def _build_summary(
        self,
        case_results: list[CaseEvaluationResult],
        systems: list[str],
        diversity_scores: dict[str, MetricScore],
        outputs_by_system: dict[str, list[CandidateOutput]],
    ) -> dict[str, Any]:
        """Aggregates win/loss/tie outcomes, statistics, cost/latency tradeoffs."""
        total_cases = len(case_results)

        # Metric averages per system
        metric_values_by_sys: dict[str, dict[str, list[float]]] = {s: {} for s in systems}
        for res in case_results:
            for s, metrics in res.metric_scores.items():
                for m_name, m_score in metrics.items():
                    metric_values_by_sys[s].setdefault(m_name, []).append(m_score.score)

        metric_stats_by_sys: dict[str, dict[str, Any]] = {s: {} for s in systems}
        for s in systems:
            for m_name, vals in metric_values_by_sys[s].items():
                metric_stats_by_sys[s][m_name] = compute_descriptive_stats(vals)

        # Pairwise win/loss/tie aggregation (Full HW vs Strong Prompt)
        pairwise_outcomes: dict[str, dict[str, int]] = {}
        for res in case_results:
            for comp in res.pairwise_comparisons:
                pair_key = f"{comp.candidate_a_system}_vs_{comp.candidate_b_system}"
                # Normalize pair key
                if "howlwriter_full" in (comp.candidate_a_system, comp.candidate_b_system):
                    other = comp.candidate_b_system if comp.candidate_a_system == "howlwriter_full" else comp.candidate_a_system
                    canonical_key = f"howlwriter_full_vs_{other}"
                else:
                    canonical_key = pair_key

                stats_bucket = pairwise_outcomes.setdefault(canonical_key, {"hw_wins": 0, "baseline_wins": 0, "ties": 0, "inconclusive": 0})
                if comp.winning_system == "howlwriter_full":
                    stats_bucket["hw_wins"] += 1
                elif comp.winning_system == "TIE":
                    stats_bucket["ties"] += 1
                elif comp.winning_system == "INCONCLUSIVE":
                    stats_bucket["inconclusive"] += 1
                else:
                    stats_bucket["baseline_wins"] += 1

        # Verdicts for primary comparisons
        verdicts: dict[str, Any] = {}
        for pair_key, counts in pairwise_outcomes.items():
            verdicts[pair_key] = determine_verdict(
                wins_hw=counts["hw_wins"],
                wins_baseline=counts["baseline_wins"],
                ties=counts["ties"],
            )

        # Latency & Cost Multipliers
        telemetry_by_sys: dict[str, dict[str, Any]] = {}
        for s, outputs in outputs_by_system.items():
            latencies = [o.latency_seconds for o in outputs if o.success]
            tokens = [o.token_usage.get("total_tokens", 0) for o in outputs if o.success]
            failures = sum(1 for o in outputs if not o.success)

            telemetry_by_sys[s] = {
                "latency": compute_descriptive_stats(latencies),
                "total_tokens": compute_descriptive_stats(tokens),
                "failures_count": failures,
                "success_rate": round(len(latencies) / len(outputs), 4) if outputs else 0.0,
            }

        # Calculate multipliers relative to strong_prompt
        sp_latency = telemetry_by_sys.get("strong_prompt", {}).get("latency", {}).get("median") or 1.0
        sp_tokens = telemetry_by_sys.get("strong_prompt", {}).get("total_tokens", {}).get("median") or 1.0
        hw_latency = telemetry_by_sys.get("howlwriter_full", {}).get("latency", {}).get("median") or 1.0
        hw_tokens = telemetry_by_sys.get("howlwriter_full", {}).get("total_tokens", {}).get("median") or 1.0

        multipliers = {
            "latency_multiplier": round(hw_latency / sp_latency, 2) if sp_latency > 0 else 1.0,
            "token_multiplier": round(hw_tokens / sp_tokens, 2) if sp_tokens > 0 else 1.0,
        }

        # Structural diversity comparisons
        diversity_summary = {
            s: score.to_dict() for s, score in diversity_scores.items()
        }

        return {
            "total_cases_evaluated": total_cases,
            "systems_evaluated": systems,
            "metric_statistics": metric_stats_by_sys,
            "pairwise_outcomes": pairwise_outcomes,
            "verdicts": verdicts,
            "telemetry": telemetry_by_sys,
            "tradeoff_multipliers": multipliers,
            "structural_diversity": diversity_summary,
        }
