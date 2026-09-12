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
        "--target-words", type=int, default=None, dest="target_words",
        help="Target body-word count.",
    )
    parser.add_argument(
        "--max-words", type=int, default=None, dest="max_words",
        help="Hard maximum body-word count.",
    )
    parser.add_argument(
        "--target-pages", type=int, default=None, dest="target_pages",
        help="Target page count (approx. 275 words/page).",
    )
    parser.add_argument(
        "--max-pages", type=int, default=None, dest="max_pages",
        help="Hard maximum page count (approx. 275 words/page).",
    )
    parser.add_argument(
        "--require", action="append", default=[], dest="required_items",
        help="A required rubric item to preserve (can be repeated).",
    )
    parser.add_argument(
        "--prohibit", action="append", default=[], dest="prohibited_content",
        help="A prohibited content/identifier type (can be repeated).",
    )
    parser.add_argument(
        "--compression-note", default=None, dest="compression_note",
        help="Free-form guidance such as 'do not overdo this'.",
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
    if args.target_words is not None:
        config.target_words = args.target_words
    if args.max_words is not None:
        config.max_words = args.max_words
    if args.target_pages is not None:
        config.target_pages = args.target_pages
    if args.max_pages is not None:
        config.max_pages = args.max_pages
    if args.required_items:
        config.required_items = list(args.required_items)
    if args.prohibited_content:
        config.prohibited_content = list(args.prohibited_content)
    if args.compression_note:
        config.compression_notes = args.compression_note
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
