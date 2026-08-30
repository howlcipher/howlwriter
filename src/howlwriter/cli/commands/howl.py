"""`howlwriter howl <file>` -- the complete appropriate pipeline for the
MVP: INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> FINAL REVIEW ->
OUTPUT. Prints lint findings, red pen findings, and the transformation
report, and writes the transformed document alongside the input."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.config.loader import ConfigLoader
from howlwriter.pipeline.howl import run_howl_pipeline


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("howl", help="Run the complete MVP pipeline on a file.")
    parser.add_argument("path")
    parser.add_argument("--config", dest="project_config_path", default=None)
    parser.add_argument("--out", default=None, help="Output path (default: <path>.howled.md).")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    config = ConfigLoader().load(project_config_path=args.project_config_path)
    result = run_howl_pipeline(args.path, config)

    if result.lint_matches:
        print("LINT FINDINGS")
        for match in result.lint_matches:
            location = "document" if match.paragraph_index is None else f"paragraph {match.paragraph_index}"
            print(f"  {match.rule_code} ({location}): {match.message}")
        print()

    if result.red_pen_findings:
        print("RED PEN FINDINGS")
        for finding in result.red_pen_findings:
            print(f"  {finding.id}: {finding.reason} ({finding.recommendation})")
        print()

    out_path = Path(args.out) if args.out else Path(args.path).with_suffix(".howled.md")
    out_path.write_text(result.final_document.text, encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    print(result.report.render_text())
    return 0
