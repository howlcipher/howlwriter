"""`howlwriter howl <file>` -- the complete pipeline:
INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW -> FINAL REVIEW -> OUTPUT.

Uses real HowlPlane model execution for Humanizer and independent Meaning Reviewer
when configured, or deterministic safe rewrites when opted in."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.modes import parse_mode
from howlwriter.pipeline.howl import run_howl_pipeline


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "howl", help="Run the complete pipeline on a file."
    )
    parser.add_argument("path", help="Path to markdown document to process.")
    parser.add_argument(
        "--config", dest="project_config_path", default=None,
        help="Path to project configuration YAML/TOML.",
    )
    parser.add_argument(
        "--mode",
        default=None,
        help="Writing mode (linkedin, academic, technical, casual, ...).",
    )
    parser.add_argument(
        "--voice-profile",
        dest="voice_profile",
        default=None,
        help="Path to a VoiceProfile JSON, or an author label.",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Force deterministic-only execution without model calls.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path (default: <path>.howled.md).",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    mode = parse_mode(args.mode)
    config = ConfigLoader().load(
        mode=mode, project_config_path=args.project_config_path
    )
    if args.voice_profile:
        config.voice_profile = args.voice_profile
    result = run_howl_pipeline(
        args.path,
        config,
        deterministic_only=args.deterministic,
        writing_mode=mode,
    )

    if result.lint_matches:
        print("LINT FINDINGS")
        for match in result.lint_matches:
            location = (
                "document"
                if match.paragraph_index is None
                else f"paragraph {match.paragraph_index}"
            )
            print(f"  {match.rule_code} ({location}): {match.message}")
        print()

    if result.red_pen_findings:
        print("RED PEN FINDINGS")
        for finding in result.red_pen_findings:
            print(
                f"  {finding.id}: {finding.reason} ({finding.recommendation})"
            )
        print()

    out_path = (
        Path(args.out)
        if args.out
        else Path(args.path).with_suffix(".howled.md")
    )
    atomic_write_text(out_path, result.final_document.text)
    print(f"Wrote {out_path}")
    print()
    print(result.report.render_text())
    return 0
