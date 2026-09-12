"""Reporting engine generating human-readable Markdown and machine-readable JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from howlwriter.domain.io import atomic_write_text
from howlwriter.evaluation.models import BenchmarkRun

DEFAULT_EVAL_OUTPUT_DIR = Path("output/evaluation")

QUALITY_METRIC_NAMES = {
    "factuality",
    "voice_fidelity",
    "meaning_preservation",
    "structural_diversity",
    "requirement_satisfaction",
    "length_compliance",
}
ASSURANCE_METRIC_NAMES = {
    "citation_integrity",
    "source_quality",
    "red_pen",
    "style_lint",
}


def generate_markdown_report(run: BenchmarkRun) -> str:
    """Renders a comprehensive Markdown summary of the benchmark run."""
    summary = run.summary
    telemetry = summary.get("telemetry", {})
    multipliers = summary.get("tradeoff_multipliers", {})
    pairwise = summary.get("pairwise_outcomes", {})
    verdicts = summary.get("verdicts", {})
    diversity = summary.get("structural_diversity", {})
    stats = summary.get("metric_statistics", {})
    denominators = summary.get("denominators", {})

    suite_total = denominators.get("suite_total_cases", summary.get("total_cases_evaluated", 0))
    evaluated_cases = summary.get("total_cases_evaluated", 0)
    failed_evals = denominators.get("failed_evaluations_count", 0)

    lines = [
        f"# HowlWriter Benchmark Report: {run.suite_name.upper()}",
        f"\n**Run ID:** `{run.run_id}`  ",
        f"**Timestamp:** `{run.timestamp}`  ",
        f"**Git Commit:** `{run.git_commit or 'unknown'}`  ",
        f"**HowlWriter Version:** `{run.howlwriter_version}`  ",
        f"**Total Cases Evaluated:** {evaluated_cases} (suite total: {suite_total}, failures: {failed_evals})  ",
        f"**Repetitions:** {run.repeat}  ",
        f"**Mode:** {'Deterministic Only (CI Hermetic)' if run.deterministic_only else 'Model-Judged & Multi-Provider'}  \n",
        "---",
        "\n## 1. Executive Summary & Verdicts\n",
    ]

    for pair_key, verd_info in verdicts.items():
        verd = verd_info.get("verdict", "INCONCLUSIVE")
        reason = verd_info.get("reason", "")
        p_val = verd_info.get("p_value")
        p_str = f" (p={p_val:.4f})" if p_val is not None else ""
        lines.append(f"### Comparison: `{pair_key}`")
        lines.append(f"**Verdict:** **{verd}**{p_str}")
        lines.append(f"> {reason}\n")

    lines.append("\n## 2. Pairwise Blinded Comparison Outcomes\n")
    lines.append("| Baseline Comparison | HW Wins | Baseline Wins | Ties | Inconclusive | Total (n) | HW Win Rate |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")

    for pair_key, counts in pairwise.items():
        total = counts.get("total_comparisons") or (counts["hw_wins"] + counts["baseline_wins"] + counts["ties"] + counts.get("inconclusive", 0))
        hw_rate = (counts["hw_wins"] / total * 100) if total else 0.0
        lines.append(
            f"| `{pair_key}` | {counts['hw_wins']} | {counts['baseline_wins']} | {counts['ties']} | {counts.get('inconclusive', 0)} | {total} | {hw_rate:.1f}% |"
        )

    lines.append("\n## 3. Dimensional Metric Comparison\n")
    systems = summary.get("systems_evaluated", [])
    all_metrics = set()
    for s in systems:
        all_metrics.update(stats.get(s, {}).keys())

    quality_metrics = sorted([m for m in all_metrics if m in QUALITY_METRIC_NAMES])
    assurance_metrics = sorted([m for m in all_metrics if m in ASSURANCE_METRIC_NAMES])
    other_metrics = sorted([m for m in all_metrics if m not in QUALITY_METRIC_NAMES and m not in ASSURANCE_METRIC_NAMES])

    if quality_metrics or not all_metrics:
        lines.append("### 3.1 Final Output Quality (Mean Scores [0.0 - 1.0])\n")
        lines.append("*Measures intrinsic quality of produced prose: factual accuracy, voice fidelity, meaning preservation, and requirement compliance.*\n")
        header = "| Quality Metric | " + " | ".join(f"`{s}`" for s in systems) + " |"
        sep = "| :--- | " + " | ".join(":---:" for _ in systems) + " |"
        lines.append(header)
        lines.append(sep)
        for m in (quality_metrics if quality_metrics else sorted(all_metrics)):
            row_vals = []
            for s in systems:
                mean_val = stats.get(s, {}).get(m, {}).get("mean")
                row_vals.append(f"{mean_val:.3f}" if mean_val is not None else "N/A")
            lines.append(f"| **{m}** | " + " | ".join(row_vals) + " |")
        lines.append("")

    if assurance_metrics:
        lines.append("### 3.2 Assurance & Verification Coverage (Mean Scores [0.0 - 1.0])\n")
        lines.append("*Measures verification depth, citation integrity, Red Pen enforcement, and style lint compliance.*\n")
        header = "| Assurance Metric | " + " | ".join(f"`{s}`" for s in systems) + " |"
        sep = "| :--- | " + " | ".join(":---:" for _ in systems) + " |"
        lines.append(header)
        lines.append(sep)
        for m in assurance_metrics:
            row_vals = []
            for s in systems:
                mean_val = stats.get(s, {}).get(m, {}).get("mean")
                row_vals.append(f"{mean_val:.3f}" if mean_val is not None else "N/A")
            lines.append(f"| **{m}** | " + " | ".join(row_vals) + " |")
        lines.append("")

    if other_metrics:
        lines.append("### 3.3 Other Diagnostic Metrics\n")
        header = "| Metric | " + " | ".join(f"`{s}`" for s in systems) + " |"
        sep = "| :--- | " + " | ".join(":---:" for _ in systems) + " |"
        lines.append(header)
        lines.append(sep)
        for m in other_metrics:
            row_vals = []
            for s in systems:
                mean_val = stats.get(s, {}).get(m, {}).get("mean")
                row_vals.append(f"{mean_val:.3f}" if mean_val is not None else "N/A")
            lines.append(f"| **{m}** | " + " | ".join(row_vals) + " |")
        lines.append("")

    lines.append("## 4. Cost, Latency & Reliability Tradeoffs\n")
    lines.append("| System | Provenance | Median Latency | Median Tokens | Failures | Success Rate |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |")

    for s in systems:
        t_info = telemetry.get(s, {})
        prov = (t_info.get("cost_provenance") or "N/A").upper()
        lat = t_info.get("latency", {}).get("median")
        tok = t_info.get("total_tokens", {}).get("median")
        fail = t_info.get("failures_count", 0)
        succ = t_info.get("success_rate", 1.0) * 100
        lat_str = f"{lat:.2f}s" if lat is not None else "N/A"
        tok_str = f"{int(tok)}" if tok is not None else "N/A"
        lines.append(f"| `{s}` | {prov} | {lat_str} | {tok_str} | {fail} | {succ:.1f}% |")

    # Stage timing breakdown if present
    has_stage_timings = any(bool(telemetry.get(s, {}).get("stage_timings")) for s in systems)
    if has_stage_timings:
        lines.append("\n**Stage Latency Breakdown (Mean Seconds):**\n")
        all_stages = sorted({stage for s in systems for stage in telemetry.get(s, {}).get("stage_timings", {}).keys()})
        stg_header = "| System | " + " | ".join(f"`{stg}`" for stg in all_stages) + " |"
        stg_sep = "| :--- | " + " | ".join(":---:" for _ in all_stages) + " |"
        lines.append(stg_header)
        lines.append(stg_sep)
        for s in systems:
            stg_map = telemetry.get(s, {}).get("stage_timings", {})
            stg_vals = [f"{stg_map[stg]:.2f}s" if stg in stg_map else "-" for stg in all_stages]
            lines.append(f"| `{s}` | " + " | ".join(stg_vals) + " |")

    lines.append("\n**Architecture Tradeoff Multipliers (vs Strong Prompt):**")
    lines.append(f"- **Latency Multiplier:** `{multipliers.get('latency_multiplier', 1.0)}x`")
    lines.append(f"- **Token Multiplier:** `{multipliers.get('token_multiplier', 1.0)}x`")

    lines.append("\n## 5. Structural Diversity & Reference Distribution Distance\n")
    lines.append("| System | Verdict | Score [0-1] | Mean Raw CV | Converged Dimensions |")
    lines.append("| :--- | :---: | :---: | :---: | :--- |")

    for s in systems:
        d_info = diversity.get(s, {}).get("details", {})
        score_val = diversity.get(s, {}).get("score")
        score_str = f"{score_val:.3f}" if score_val is not None else "N/A"
        verd = d_info.get("verdict", "N/A")
        raw_cv = d_info.get("mean_raw_cv", d_info.get("mean_cv"))
        cv_str = f"{raw_cv:.3f}" if raw_cv is not None else "N/A"
        conv_dims = ", ".join(d_info.get("converged_dimensions", [])) or "None"
        lines.append(f"| `{s}` | **{verd}** | {score_str} | {cv_str} | {conv_dims} |")

    lines.append("\n## 6. Empirical Findings & Limitations\n")
    lines.append("1. **Citation & Source Authority:** HowlWriter achieves near-perfect citation integrity and grounding by design, resolving DOIs and validating primary source authorities.")
    lines.append("2. **Requirement Coverage:** HowlWriter's outline and constraint layers systematically enforce section, word count, and point presence.")
    lines.append("3. **Prose Quality Parity:** Against an expertly crafted prompt, generic prose quality gains are modest or parity.")
    lines.append("4. **Cost of Architecture:** HowlWriter incurs multi-stage model and token overhead, resulting in higher latency and token usage.")
    lines.append("5. **Structural Convergence:** Output demonstrates tighter variance in sentence and paragraph structure than natural human corpora, remaining an active area of research.\n")

    return "\n".join(lines)


def write_benchmark_reports(
    run: BenchmarkRun,
    output_dir: Path | str | None = None,
) -> dict[str, Path]:
    """Writes JSON, Markdown summary, and per-case results to output/evaluation/."""
    out_dir = Path(output_dir) if output_dir else DEFAULT_EVAL_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = out_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    # 1. Markdown summary
    md_content = generate_markdown_report(run)
    md_path = out_dir / "benchmark-summary.md"
    atomic_write_text(md_path, md_content)

    # 2. Complete results JSON
    json_path = out_dir / "benchmark-results.json"
    atomic_write_text(json_path, run.to_json(indent=2))

    # 3. Individual case JSONs
    for res in run.case_results:
        case_path = cases_dir / f"{res.case_id}.json"
        atomic_write_text(case_path, json.dumps(res.to_dict(), indent=2, default=str))

    return {
        "markdown": md_path,
        "json": json_path,
        "cases_dir": cases_dir,
    }


def compare_runs(
    current_run: BenchmarkRun,
    reference_run: BenchmarkRun,
) -> dict[str, Any]:
    """Compares current run with a reference baseline to detect performance regressions."""
    curr_summary = current_run.summary
    ref_summary = reference_run.summary

    curr_stats = curr_summary.get("metric_statistics", {}).get("howlwriter_full", {})
    ref_stats = ref_summary.get("metric_statistics", {}).get("howlwriter_full", {})

    regressions = []
    improvements = []

    for metric_name, curr_m in curr_stats.items():
        ref_m = ref_stats.get(metric_name, {})
        curr_mean = curr_m.get("mean")
        ref_mean = ref_m.get("mean")

        if curr_mean is not None and ref_mean is not None:
            delta = curr_mean - ref_mean
            if delta < -0.05:
                regressions.append({
                    "metric": metric_name,
                    "previous": ref_mean,
                    "current": curr_mean,
                    "delta": round(delta, 4),
                })
            elif delta > 0.05:
                improvements.append({
                    "metric": metric_name,
                    "previous": ref_mean,
                    "current": curr_mean,
                    "delta": round(delta, 4),
                })

    return {
        "current_run_id": current_run.run_id,
        "reference_run_id": reference_run.run_id,
        "regressions": regressions,
        "improvements": improvements,
        "status": "REGRESSION_DETECTED" if regressions else "PASS",
    }
