"""CLI command for empirical evaluation and benchmarking: `howlwriter benchmark`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from howlwriter.evaluation.fixtures import get_benchmark_suite, load_all_cases
from howlwriter.evaluation.judges import DeterministicJudge, ModelJudge
from howlwriter.evaluation.models import BenchmarkCase, BenchmarkSuite
from howlwriter.evaluation.reports import (
    compare_runs,
    generate_markdown_report,
    write_benchmark_reports,
)
from howlwriter.evaluation.runner import BenchmarkRunner


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "benchmark",
        help="Run, inspect, and report empirical benchmarks against baselines and ablations.",
    )
    benchmark_subparsers = parser.add_subparsers(dest="benchmark_command")

    # 1. howlwriter benchmark run
    run_parser = benchmark_subparsers.add_parser("run", help="Execute benchmark suite.")
    _add_run_arguments(run_parser)
    run_parser.set_defaults(handler=handle_run)

    # 2. howlwriter benchmark list
    list_parser = benchmark_subparsers.add_parser("list", help="List available benchmark cases and suites.")
    list_parser.add_argument("--category", help="Filter by category.")
    list_parser.add_argument("--json", dest="output_json", action="store_true", help="Output machine-readable JSON.")
    list_parser.set_defaults(handler=handle_list)

    # 3. howlwriter benchmark report
    report_parser = benchmark_subparsers.add_parser("report", help="Render report from previous benchmark run.")
    report_parser.add_argument("--results-path", default="output/evaluation/benchmark-results.json", help="Path to benchmark-results.json.")
    report_parser.add_argument("--json", dest="output_json", action="store_true", help="Output JSON instead of Markdown.")
    report_parser.set_defaults(handler=handle_report)

    # 4. howlwriter benchmark compare
    compare_parser = benchmark_subparsers.add_parser("compare", help="Compare current run against reference baseline.")
    compare_parser.add_argument("--current", required=True, help="Path to current benchmark-results.json.")
    compare_parser.add_argument("--reference", required=True, help="Path to reference benchmark-results.json.")
    compare_parser.add_argument("--json", dest="output_json", action="store_true", help="Output JSON comparison.")
    compare_parser.set_defaults(handler=handle_compare)

    # Default if subcommand is omitted: run
    _add_run_arguments(parser)
    parser.set_defaults(handler=handle_run)
    return parser


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--suite", default="core", help="Suite to run: core, all, academic, technical, rewrite, professional.")
    parser.add_argument("--case", dest="case_id", help="Execute a single case by ID.")
    parser.add_argument(
        "--baseline",
        default="raw_model,strong_prompt,howlwriter_full",
        help="Comma-separated baselines: raw_model, strong_prompt, howlwriter_minimal, howlwriter_full.",
    )
    parser.add_argument(
        "--ablation",
        default="",
        help="Comma-separated ablations: no_source_verification, no_voice, no_independent_review, no_red_pen, no_humanizer.",
    )
    parser.add_argument("--repeat", type=int, default=1, help="Number of repetitions per case (default: 1).")
    parser.add_argument("--output", default="output/evaluation", help="Directory to save benchmark reports.")
    parser.add_argument("--deterministic-only", action="store_true", help="Run only deterministic metrics without LLM judges.")
    parser.add_argument("--mock-models", action="store_true", help="Use deterministic mock models for hermetic CI testing.")
    parser.add_argument("--json", dest="output_json", action="store_true", help="Output machine-readable JSON to stdout.")


def handle_run(args: argparse.Namespace) -> int:
    suite_name = getattr(args, "suite", "core")
    case_id = getattr(args, "case_id", None)
    baselines_arg = getattr(args, "baseline", "raw_model,strong_prompt,howlwriter_full")
    ablations_arg = getattr(args, "ablation", "")
    repeat = getattr(args, "repeat", 1)
    out_dir = getattr(args, "output", "output/evaluation")
    deterministic_only = getattr(args, "deterministic_only", False)
    mock_models = getattr(args, "mock_models", False)
    output_json = getattr(args, "output_json", False)

    baselines = [b.strip() for b in baselines_arg.split(",") if b.strip()]
    ablations = [a.strip() for a in ablations_arg.split(",") if a.strip()]

    if case_id:
        all_cases = load_all_cases()
        matching = [c for c in all_cases if c.id == case_id.strip()]
        if not matching:
            print(f"error: Case '{case_id}' not found.", file=sys.stderr)
            return 1
        suite = BenchmarkSuite(name=f"case_{case_id}", cases=matching)
    else:
        suite = get_benchmark_suite(suite_name)

    mock_gen = None
    if mock_models:
        mock_gen = lambda sys_id, prompt: f"Mock evaluation response for {sys_id}. Verifiable facts: 90 days, $45,000, 99.9% uptime SLA."

    judge = DeterministicJudge() if deterministic_only else ModelJudge()
    runner = BenchmarkRunner(
        judge=judge,
        mock_generator=mock_gen,
        deterministic_only=deterministic_only,
    )

    if not output_json:
        print(f"Running HowlWriter Benchmark Suite: '{suite.name}' ({len(suite.cases)} cases, {repeat} reps)...")

    run_result = runner.run_suite(
        suite=suite,
        baselines=baselines,
        ablations=ablations,
        repeat=repeat,
    )

    # Write deliverables to output directory
    saved_paths = write_benchmark_reports(run_result, output_dir=out_dir)

    if output_json:
        print(run_result.to_json(indent=2))
    else:
        md_content = generate_markdown_report(run_result)
        print("\n" + md_content)
        print(f"\nBenchmark artifacts written to: {out_dir}/")
        print(f"  Summary: {saved_paths['markdown']}")
        print(f"  Full JSON: {saved_paths['json']}")

    return 0


def handle_list(args: argparse.Namespace) -> int:
    cases = load_all_cases()
    category = getattr(args, "category", None)
    if category:
        cases = [c for c in cases if category.lower() in c.category.lower()]

    output_json = getattr(args, "output_json", False)
    if output_json:
        print(json.dumps([c.to_dict() for c in cases], indent=2))
        return 0

    print(f"Available Benchmark Cases ({len(cases)} total):\n")
    print(f"{'ID':<32} {'MODE':<12} {'CATEGORY':<28} {'REQUIREMENTS'}")
    print("-" * 95)
    for c in cases:
        req_keys = ", ".join(c.requirements.keys()) if c.requirements else "standard"
        print(f"{c.id:<32} {c.mode:<12} {c.category:<28} {req_keys}")
    return 0


def handle_report(args: argparse.Namespace) -> int:
    results_path = Path(args.results_path)
    if not results_path.is_file():
        print(f"error: Results file not found: {results_path}", file=sys.stderr)
        return 1

    from howlwriter.evaluation.models import BenchmarkRun
    data = json.loads(results_path.read_text(encoding="utf-8"))
    run = BenchmarkRun.from_dict(data)

    if getattr(args, "output_json", False):
        print(json.dumps(run.summary, indent=2))
    else:
        print(generate_markdown_report(run))
    return 0


def handle_compare(args: argparse.Namespace) -> int:
    curr_path = Path(args.current)
    ref_path = Path(args.reference)
    if not curr_path.is_file() or not ref_path.is_file():
        print(f"error: Current or reference results file not found.", file=sys.stderr)
        return 1

    from howlwriter.evaluation.models import BenchmarkRun
    curr_run = BenchmarkRun.from_dict(json.loads(curr_path.read_text(encoding="utf-8")))
    ref_run = BenchmarkRun.from_dict(json.loads(ref_path.read_text(encoding="utf-8")))

    comparison = compare_runs(curr_run, ref_run)
    if getattr(args, "output_json", False):
        print(json.dumps(comparison, indent=2))
    else:
        print(f"Regression Comparison: {comparison['status']}")
        if comparison["regressions"]:
            print("\nRegressions Detected:")
            for r in comparison["regressions"]:
                print(f"  - {r['metric']}: {r['previous']} -> {r['current']} (delta: {r['delta']})")
        else:
            print("No statistically meaningful regressions detected.")
    return 0 if comparison["status"] == "PASS" else 1
