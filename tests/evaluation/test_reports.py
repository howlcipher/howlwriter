"""Unit tests for report generation, file writing, and regression tracking."""

from __future__ import annotations

from pathlib import Path
from howlwriter.evaluation.models import BenchmarkRun
from howlwriter.evaluation.reports import (
    compare_runs,
    generate_markdown_report,
    write_benchmark_reports,
)


def test_generate_markdown_report():
    run = BenchmarkRun(
        run_id="bench-test-1",
        suite_name="core",
        timestamp="2026-09-11T12:00:00Z",
        summary={
            "total_cases_evaluated": 5,
            "systems_evaluated": ["strong_prompt", "howlwriter_full"],
            "verdicts": {
                "howlwriter_full_vs_strong_prompt": {
                    "verdict": "HOWLWRITER WINS",
                    "reason": "Statistically significant improvement.",
                }
            },
            "pairwise_outcomes": {
                "howlwriter_full_vs_strong_prompt": {"hw_wins": 4, "baseline_wins": 0, "ties": 1}
            },
            "metric_statistics": {
                "howlwriter_full": {"citation_integrity": {"mean": 0.95}},
                "strong_prompt": {"citation_integrity": {"mean": 0.50}},
            },
            "telemetry": {
                "strong_prompt": {"latency": {"median": 2.0}, "total_tokens": {"median": 100}},
                "howlwriter_full": {"latency": {"median": 6.0}, "total_tokens": {"median": 250}},
            },
            "tradeoff_multipliers": {"latency_multiplier": 3.0, "token_multiplier": 2.5},
            "structural_diversity": {
                "howlwriter_full": {"details": {"verdict": "PASS", "mean_cv": 0.28}}
            },
        },
    )

    md = generate_markdown_report(run)
    assert "# HowlWriter Benchmark Report: CORE" in md
    assert "HOWLWRITER WINS" in md
    assert "3.0x" in md
    assert "2.5x" in md


def test_write_benchmark_reports(tmp_path: Path):
    run = BenchmarkRun(
        run_id="bench-write-1",
        suite_name="test",
        timestamp="2026-09-11T12:00:00Z",
        summary={"total_cases_evaluated": 0},
    )

    out_dir = tmp_path / "eval_out"
    paths = write_benchmark_reports(run, output_dir=out_dir)

    assert paths["markdown"].is_file()
    assert paths["json"].is_file()
    assert (out_dir / "cases").is_dir()


def test_compare_runs_detects_regressions():
    run_ref = BenchmarkRun(
        run_id="ref_run",
        suite_name="core",
        timestamp="2026-09-10T12:00:00Z",
        summary={
            "metric_statistics": {
                "howlwriter_full": {
                    "citation_integrity": {"mean": 0.95},
                    "factuality": {"mean": 0.90},
                }
            }
        },
    )

    # Current run has regressed on citation integrity
    run_curr = BenchmarkRun(
        run_id="curr_run",
        suite_name="core",
        timestamp="2026-09-11T12:00:00Z",
        summary={
            "metric_statistics": {
                "howlwriter_full": {
                    "citation_integrity": {"mean": 0.70},  # Regressed
                    "factuality": {"mean": 0.92},
                }
            }
        },
    )

    comp = compare_runs(run_curr, run_ref)
    assert comp["status"] == "REGRESSION_DETECTED"
    assert len(comp["regressions"]) == 1
    assert comp["regressions"][0]["metric"] == "citation_integrity"


def test_generate_markdown_report_separated_quality_assurance_and_denominators():
    run = BenchmarkRun(
        run_id="bench-cal-1",
        suite_name="core",
        timestamp="2026-09-11T12:00:00Z",
        summary={
            "total_cases_evaluated": 11,
            "systems_evaluated": ["strong_prompt", "howlwriter_full"],
            "denominators": {
                "suite_total_cases": 36,
                "evaluated_cases": 11,
                "failed_evaluations_count": 0,
            },
            "metric_statistics": {
                "howlwriter_full": {
                    "factuality": {"mean": 0.88},
                    "voice_fidelity": {"mean": 0.79},
                    "citation_integrity": {"mean": 0.98},
                    "red_pen": {"mean": 0.95},
                },
                "strong_prompt": {
                    "factuality": {"mean": 0.85},
                    "voice_fidelity": {"mean": 0.52},
                    "citation_integrity": {"mean": 0.60},
                    "red_pen": {"mean": 0.70},
                },
            },
            "telemetry": {
                "howlwriter_full": {
                    "latency": {"median": 4.5},
                    "total_tokens": {"median": 1200},
                    "cost_provenance": "measured",
                    "stage_timings": {"draft": 1.8, "verification": 0.9, "red_pen": 0.9},
                },
                "strong_prompt": {
                    "latency": {"median": 1.5},
                    "total_tokens": {"median": 500},
                    "cost_provenance": "estimated",
                    "stage_timings": {"writer": 1.5},
                },
            },
        },
    )

    md = generate_markdown_report(run)
    # Check denominator disclosure
    assert "suite total: 36" in md
    assert "11 (suite total: 36, failures: 0)" in md

    # Check separation of quality vs assurance
    assert "3.1 Final Output Quality" in md
    assert "3.2 Assurance & Verification Coverage" in md
    assert "MEASURED" in md
    assert "ESTIMATED" in md
    assert "Stage Latency Breakdown" in md

