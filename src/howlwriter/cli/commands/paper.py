"""`howlwriter paper <assignment.yaml>` -- complete researched academic paper workflow."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from howlwriter.academic.length import resolve_length_bounds
from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.research import load_sources_file, save_sources_file
from howlwriter.academic.spec import AssignmentSpec, load_assignment_spec
from howlwriter.domain.outline import load_outline
from howlwriter.provenance.assemble import write_artifacts
from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.io import atomic_write_text
from howlwriter.voice.corpus.resolve import resolve_voice_option


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "paper",
        help="Draft and review a researched academic paper from an assignment spec.",
    )
    parser.add_argument(
        "assignment",
        nargs="?",
        default=None,
        help="Path to assignment YAML or JSON specification file.",
    )
    parser.add_argument(
        "--outline",
        default=None,
        help=(
            "Path to an authorship outline (YAML or JSON). It is translated "
            "into the assignment spec rather than routed around it, so every "
            "research, citation and verification check still runs."
        ),
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
        "--voice",
        default=None,
        help="Name of a personal voice built with `howlwriter voice build`. The "
             "academic context is applied inside the assignment's own constraints.",
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
        help="Run in deterministic-only mode without invoking model providers.",
    )
    parser.add_argument(
        "--save-artifacts",
        action="store_true",
        help="Save auxiliary <out>.sources.json and <out>.report.json artifacts.",
    )
    parser.add_argument(
        "--provenance",
        action="store_true",
        help="Write a local provenance record, manifest and AI-use statement.",
    )
    parser.add_argument(
        "--provenance-level",
        dest="provenance_level",
        choices=["summary", "full"],
        default="summary",
        help="full also records the exact prompts HowlWriter sent.",
    )
    parser.set_defaults(handler=run)
    return parser


def _source_dir(args: argparse.Namespace) -> Path | None:
    """Directory a provider should run in.

    An outline-only run has no assignment file, so the outline's own directory
    stands in rather than passing a path that does not exist.
    """
    for candidate in (getattr(args, "assignment", None), getattr(args, "outline", None)):
        if candidate and Path(candidate).exists():
            return Path(candidate).parent
    return None


def run(args: argparse.Namespace) -> int:
    outline = None
    if getattr(args, "outline", None):
        try:
            outline = load_outline(args.outline)
        except Exception as exc:
            print(f"error: invalid outline '{args.outline}': {exc}", file=sys.stderr)
            return 1

    if not args.assignment and outline is None:
        print(
            "error: provide an assignment spec, or --outline to write from an "
            "authorship outline",
            file=sys.stderr,
        )
        return 1

    if args.assignment:
        try:
            spec = load_assignment_spec(args.assignment)
        except Exception as exc:
            print(f"error: invalid assignment spec '{args.assignment}': {exc}", file=sys.stderr)
            return 1
    else:
        # The outline carries the title, topic, length and requirements; the
        # bridge fills the spec from it inside the pipeline.
        spec = AssignmentSpec(title=outline.title or outline.topic, topic=outline.topic)

    config = ConfigLoader().load(project_config_path=args.project_config_path)

    # The assignment spec may name a profile; an explicit flag wins over it,
    # and both are subordinate to the spec's own requirements and limits.
    resolved_voice = resolve_voice_option(
        voice=getattr(args, "voice", None),
        voice_profile=getattr(args, "voice_profile", None),
    )
    config.voice_profile = resolved_voice or spec.voice_profile or config.voice_profile

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

    bounds = resolve_length_bounds(spec)
    lc = spec.length_constraints

    print(f"Executing academic paper workflow for: {spec.title}")
    if lc.target_page_min is not None and lc.target_page_max is not None:
        print(f"  Target Pages:  {lc.target_page_min:g}–{lc.target_page_max:g}")
        if lc.max_pages is not None:
            print(f"  Maximum Pages: {lc.max_pages:g}")
    print(f"  Target Words:  {bounds.target_words} (range: {bounds.min_words}–{bounds.max_words})")
    if spec.requirements:
        print(f"  Required Criteria: {len(spec.requirements)}")
    print(f"  Style:         {spec.citation_style.upper()}")
    print("  Running research and evidence collection...")

    try:
        result = run_academic_pipeline(
            spec,
            config=config,
            existing_sources=existing_sources,
            outline=outline,
            deterministic_only=args.deterministic,
            cwd=_source_dir(args),
        )
    except Exception as exc:
        print(f"error: academic paper generation failed: {exc}", file=sys.stderr)
        return 1

    # Atomic write of final paper
    atomic_write_text(out_path, result.final_document.text)
    print(f"Wrote {out_path}")

    if getattr(result, "authorship_coverage", None) is not None:
        coverage = result.authorship_coverage
        print()
        print("OUTLINE COVERAGE")
        print(f"  verdict: {coverage.status}")
        print(
            f"  required points: {coverage.required_represented}"
            f"/{coverage.required_supplied}"
        )
        print(
            f"  preserved text:  {coverage.preserved_retained}"
            f"/{coverage.preserved_supplied}"
        )
        for finding in coverage.findings:
            if finding.status != "PRESENT":
                print(f"  {finding.status} [{finding.node_id}] {finding.text[:70]}")

    if getattr(args, "provenance", False) and getattr(result, "provenance", None):
        written = write_artifacts(
            result.provenance,
            out_path,
            level=args.provenance_level,
            outline=outline,
            sources=[s.to_dict() for s in result.sources] if result.sources else None,
        )
        statement_path = out_path.with_suffix(".ai-use.txt")
        atomic_write_text(statement_path, result.ai_use_statement.render() + "\n")
        for artifact in [*written.written(), statement_path]:
            print(f"Wrote {artifact}")
        print(
            "Provenance and disclosure files are local and private. The "
            "scholarly References page is unaffected: nothing from these files "
            "belongs there."
        )

    # Optional auxiliary artifacts
    if args.save_artifacts:
        sources_path = out_path.with_suffix(".sources.json")
        save_sources_file(sources_path, result.sources)
        print(f"Wrote {sources_path}")

    print()
    print(result.report.render_text())

    return 0 if result.report.status == "READY" else 0
