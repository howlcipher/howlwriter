"""`howlwriter howl <file>` or `howlwriter howl --outline <outline.yaml>`.

With a file, the pipeline transforms prose that already exists:
INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW -> FINAL REVIEW -> OUTPUT.

With an outline, it writes that prose first and then runs the same chain, and
checks afterwards -- deterministically, not by asking the model -- that the
outline's verbatim passages, required points, and ordering survived.

Uses real HowlPlane model execution for Humanizer and independent Meaning Reviewer
when configured, or deterministic safe rewrites when opted in."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.modes import parse_mode
from howlwriter.domain.outline import load_outline
from howlwriter.pipeline.howl import run_howl_pipeline
from howlwriter.provenance.assemble import write_artifacts
from howlwriter.voice.corpus.resolve import resolve_voice_option


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "howl", help="Run the complete pipeline on a file."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to markdown document to process. Omit when using --outline.",
    )
    parser.add_argument(
        "--outline",
        default=None,
        help="Path to an authorship outline (YAML or JSON) to write from.",
    )
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
        "--voice",
        default=None,
        help="Name of a personal voice built with `howlwriter voice build`.",
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
    parser.add_argument(
        "--target-words",
        type=int,
        default=None,
        help="Optional target word count; final document is checked against it.",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=None,
        help="Optional hard word count ceiling (used with --target-words).",
    )
    parser.add_argument(
        "--provenance",
        action="store_true",
        help="Write a local provenance record and manifest beside the output.",
    )
    parser.add_argument(
        "--provenance-level",
        dest="provenance_level",
        choices=["summary", "full"],
        default="summary",
        help=(
            "summary records roles, providers, models and prompt hashes; "
            "full also records the exact prompts HowlWriter sent. Both stay "
            "local and are never published."
        ),
    )
    parser.add_argument(
        "--mask-paths",
        dest="mask_paths",
        action="store_true",
        help="Mask home directory paths in the provenance record.",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    if not args.path and not args.outline:
        raise ValueError(
            "provide a document path, or --outline to write from an outline"
        )
    if args.path and args.outline:
        raise ValueError(
            "use either a document path or --outline, not both: the outline "
            "would have nothing to add to a draft that already exists"
        )

    if args.outline and args.deterministic:
        raise ValueError(
            "--outline cannot be combined with --deterministic: an outline is "
            "not prose yet, so there is nothing for the deterministic path to "
            "transform. Writing from an outline requires a configured writer "
            "role. Use `howlwriter outline validate` to check an outline "
            "without running a model."
        )

    outline = load_outline(args.outline) if args.outline else None
    mode = parse_mode(args.mode or (outline.mode if outline else None))
    config = ConfigLoader().load(
        mode=mode, project_config_path=args.project_config_path
    )
    config.voice_profile = resolve_voice_option(
        voice=getattr(args, "voice", None),
        voice_profile=args.voice_profile,
    ) or config.voice_profile
    if outline is not None and outline.voice_profile and not args.voice and not args.voice_profile:
        config.voice_profile = resolve_voice_option(
            voice=outline.voice_profile, voice_profile=None
        ) or config.voice_profile

    result = run_howl_pipeline(
        args.path,
        config,
        deterministic_only=args.deterministic,
        writing_mode=mode,
        target_words=args.target_words or (outline.target_words if outline else None),
        max_words=args.max_words or (outline.max_words if outline else None),
        outline=outline,
        provenance_level=args.provenance_level,
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

    if result.coverage is not None:
        print("OUTLINE COVERAGE")
        print(f"  verdict: {result.coverage.status}")
        print(
            f"  required points: {result.coverage.required_represented}"
            f"/{result.coverage.required_supplied}"
        )
        print(
            f"  preserved text:  {result.coverage.preserved_retained}"
            f"/{result.coverage.preserved_supplied}"
        )
        if result.coverage.order_enforced:
            print(f"  ordering:        {'satisfied' if result.coverage.order_satisfied else 'VIOLATED'}")
        for finding in result.coverage.findings:
            if finding.status != "PRESENT":
                print(f"  {finding.status} [{finding.node_id}] {finding.text[:70]}")
                if finding.detail:
                    print(f"      {finding.detail}")
        for note in result.coverage.notes:
            print(f"  note: {note}")
        print()

    if args.outline:
        default_out = Path(args.outline).with_suffix(".md")
    else:
        default_out = Path(args.path).with_suffix(".howled.md")
    out_path = Path(args.out) if args.out else default_out
    atomic_write_text(out_path, result.final_document.text)
    print(f"Wrote {out_path}")

    if args.provenance and result.provenance is not None:
        written = write_artifacts(
            result.provenance,
            out_path,
            level=args.provenance_level,
            outline=outline,
            mask_paths=args.mask_paths,
        )
        for artifact in written.written():
            print(f"Wrote {artifact}")
        print(
            "These provenance files are local and private. Nothing publishes "
            "them, and they may contain your own text."
        )
    print()
    print(result.report.render_text())
    return 0
