"""`howlwriter paper <assignment.yaml>` -- complete researched academic paper workflow."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.research import load_sources_file, save_sources_file
from howlwriter.academic.spec import load_assignment_spec
from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.io import atomic_write_text


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "paper",
        help="Draft and review a researched academic paper from an assignment spec.",
    )
    parser.add_argument(
        "assignment",
        help="Path to assignment YAML or JSON specification file.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output markdown file path (default: <assignment_slug>.md).",
    )
    parser.add_argument(
        "--config",
        dest="project_config_path",
        default=None,
        help="Path to project configuration YAML/TOML.",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="Path to pre-collected sources.json file to use for research context.",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Run in deterministic-only mode without invoking model providers.",
    )
    parser.add_argument(
        "--save-artifacts",
        action="store_true",
        help="Save auxiliary <out>.sources.json and <out>.report.json artifacts.",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    try:
        spec = load_assignment_spec(args.assignment)
    except Exception as exc:
        print(f"error: invalid assignment spec '{args.assignment}': {exc}", file=sys.stderr)
        return 1

    config = ConfigLoader().load(project_config_path=args.project_config_path)

    existing_sources = None
    if args.sources:
        try:
            existing_sources = load_sources_file(args.sources)
        except Exception as exc:
            print(f"error: failed to load sources from '{args.sources}': {exc}", file=sys.stderr)
            return 1

    # Derive default output path if not specified
    if args.out:
        out_path = Path(args.out)
    else:
        slug = re.sub(r"[^\w\s-]", "", spec.title.lower()).strip()
        slug = re.sub(r"[\s_-]+", "_", slug)[:40] or "academic_paper"
        out_path = Path(f"{slug}.md")

    print(f"Executing academic paper workflow for: {spec.title}")
    print(f"  Target Words:  {spec.target_words} (±{spec.word_tolerance_percent:.0f}%)")
    print(f"  Style:         {spec.citation_style.upper()}")
    print("  Running research and evidence collection...")

    try:
        result = run_academic_pipeline(
            spec,
            config=config,
            existing_sources=existing_sources,
            deterministic_only=args.deterministic,
            cwd=Path(args.assignment).parent if Path(args.assignment).exists() else None,
        )
    except Exception as exc:
        print(f"error: academic paper generation failed: {exc}", file=sys.stderr)
        return 1

    # Atomic write of final paper
    atomic_write_text(out_path, result.final_document.text)
    print(f"Wrote {out_path}")

    # Optional auxiliary artifacts
    if args.save_artifacts:
        sources_path = out_path.with_suffix(".sources.json")
        save_sources_file(sources_path, result.sources)
        print(f"Wrote {sources_path}")

    print()
    print(result.report.render_text())

    return 0 if result.report.status == "READY" else 0
