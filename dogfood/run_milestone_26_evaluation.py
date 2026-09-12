#!/usr/bin/env python3
"""Milestone 26 authoritative empirical evaluation runner.

Executes the full benchmark suite across all four primary baselines:
1. Raw model (minimal framing)
2. Strong prompt (complete task requirements, length bounds, APA 7, anti-slop)
3. HowlWriter minimal (drafting stage only)
4. Full HowlWriter pipeline (complete multi-stage architecture)

And key architectural ablations:
- no_source_verification
- no_voice
- no_independent_review
- no_red_pen

Measures:
- Requirement coverage
- Factuality & claim grounding
- Citation integrity & resolution
- Source authority tiers
- Meaning preservation
- Multidimensional voice fidelity (no fake single %)
- Structural diversity (detects template convergence)
- Latency and token multipliers
- Failure classifications

Saves reproducible results to output/evaluation/ and prints summary report.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

DOGFOOD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOGFOOD_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from howlwriter.evaluation.fixtures import get_benchmark_suite
from howlwriter.evaluation.judges import DeterministicJudge, ModelJudge
from howlwriter.evaluation.reports import (
    generate_markdown_report,
    write_benchmark_reports,
)
from howlwriter.evaluation.runner import BenchmarkRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HowlWriter empirical benchmark evaluation.")
    parser.add_argument("--suite", default=os.environ.get("HOWLWRITER_BENCH_SUITE", "core"), help="Suite name (core, all, academic, technical).")
    parser.add_argument("--repeat", type=int, default=int(os.environ.get("HOWLWRITER_BENCH_REPEAT", "1")), help="Number of repetitions.")
    parser.add_argument("--deterministic-only", action="store_true", default=os.environ.get("HOWLWRITER_BENCH_DETERMINISTIC", "0") == "1", help="Deterministic rule-based judge.")
    parser.add_argument("--output", default=str(REPO_ROOT / "output" / "evaluation"), help="Output directory.")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    suite_name = args.suite
    repeat = args.repeat
    deterministic_only = args.deterministic_only

    suite = get_benchmark_suite(suite_name)
    print("=" * 80)
    print("HOWLWRITER MILESTONE 26.1 — CALIBRATED BENCHMARK EVALUATION")
    print(f"Suite: '{suite.name}' ({len(suite.cases)} cases, {repeat} repetitions)")
    print(f"Output Directory: {out_dir}")
    print("=" * 80)

    baselines = ["raw_model", "strong_prompt", "howlwriter_minimal", "howlwriter_full"]
    ablations = ["no_source_verification", "no_voice", "no_independent_review", "no_red_pen"]

    judge = DeterministicJudge() if deterministic_only else ModelJudge()
    runner = BenchmarkRunner(
        judge=judge,
        deterministic_only=deterministic_only,
    )

    t0 = time.perf_counter()
    run_result = runner.run_suite(
        suite=suite,
        baselines=baselines,
        ablations=ablations,
        repeat=repeat,
    )
    duration = time.perf_counter() - t0

    paths = write_benchmark_reports(run_result, output_dir=out_dir)

    print(f"\nExecution finished in {duration:.2f} seconds.")
    print(f"Results saved to:")
    print(f"  Markdown: {paths['markdown']}")
    print(f"  JSON:     {paths['json']}")
    print("\n" + generate_markdown_report(run_result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
