"""`howlwriter paper <assignment.yaml>` -- complete researched academic paper workflow."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from howlwriter.academic.length import resolve_length_bounds
from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.research import load_sources_file, save_sources_file
from howlwriter.academic.spec import AssignmentSpec, load_assignment_spec
from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.outline import load_outline
from howlwriter.output.naming import OutputCollisionError, safe_filename
from howlwriter.provenance.assemble import write_artifacts
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
        help="Explicit output markdown file path (default: output/<safe_title>.md).",
    )
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        default=None,
        help="Deliverable format to generate (md, docx, pdf). May be specified multiple times or comma-separated.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="output",
        help="Directory for local generated deliverables (default: output/).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files if they already exist.",
    )
    parser.add_argument(
        "--publish",
        dest="publish_destination",
        default=None,
        help="Destination to publish authorized paper (e.g. 'google-docs').",
    )
    parser.add_argument(
        "--publish-title",
        dest="publish_title",
        default=None,
        help="Title of document in destination (default: assignment title).",
    )
    parser.add_argument(
        "--publish-folder",
        dest="publish_folder",
        default=None,
        help="Destination folder name or ID (e.g. cloud folder or drive ID).",
    )
    parser.add_argument(
        "--update-doc",
        dest="publish_update_doc_id",
        default=None,
        help="Existing document ID to update rather than creating a new one.",
    )
    parser.add_argument(
        "--update-mode",
        dest="publish_update_mode",
        choices=["replace", "append"],
        default="replace",
        help="Mode for updating existing document ('replace' or 'append').",
    )
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Allow publication even if artifact verification status is not READY.",
    )
    parser.add_argument(
        "--verify-sources",
        action="store_true",
        help="Run operational source integrity verification on all retrieved sources.",
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
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed for deterministic structural realization selection.",
    )
    parser.set_defaults(handler=run)
    return parser


def _source_dir(args: argparse.Namespace) -> Path | None:
    """Directory a provider should run in."""
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
        spec = AssignmentSpec(title=outline.title or outline.topic, topic=outline.topic)

    config = ConfigLoader().load(project_config_path=args.project_config_path)

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

    # Resolve output formats
    raw_formats: list[str] = []
    if args.formats:
        for f in args.formats:
            raw_formats.extend(part.strip() for part in f.split(","))
    elif spec.output and spec.output.local and spec.output.local.formats:
        raw_formats = spec.output.local.formats
    elif not args.out:
        raw_formats = ["md"]

    output_formats = [f.lower().lstrip(".") for f in raw_formats if f.strip()]

    # Output directory and safe paths
    out_dir = Path(args.output_dir)
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = out_dir / safe_filename(spec.title, "md")

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
    print(f"  Formats:       {', '.join(output_formats)}")
    print("  Running research and evidence collection...")

    try:
        result = run_academic_pipeline(
            spec,
            config=config,
            existing_sources=existing_sources,
            outline=outline,
            deterministic_only=args.deterministic,
            cwd=_source_dir(args),
            seed=args.seed,
            verify_sources=args.verify_sources,
            output_dir=out_dir,
            output_formats=output_formats,
            publish_destination=args.publish_destination,
            publish_title=args.publish_title,
            publish_folder=args.publish_folder,
            publish_update_doc_id=args.publish_update_doc_id,
            publish_update_mode=args.publish_update_mode,
            overwrite=args.overwrite,
            allow_unverified_publish=args.allow_unverified,
        )
    except OutputCollisionError as coll_exc:
        print(f"error: {coll_exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: academic paper generation failed: {exc}", file=sys.stderr)
        return 1

    # Atomic write of final paper to explicit --out if supplied and not already in deliverables
    if args.out:
        atomic_write_text(out_path, result.final_document.text)
        print(f"Wrote {out_path}")

    # Report generated local deliverables
    if result.local_deliverables:
        print("\nLOCAL DELIVERABLES")
        for deliv in result.local_deliverables:
            print(f"  [{deliv.format.upper()}] {deliv.path} (SHA256: {deliv.sha256[:12]}...)")

    # Report publication result
    if result.publish_result:
        print("\nPUBLICATION")
        pub = result.publish_result
        if pub.is_success:
            print(f"  Destination: {pub.destination_type}")
            print(f"  Title:       {pub.artifact_title}")
            if pub.artifact_id:
                print(f"  Document ID: {pub.artifact_id}")
            if pub.url:
                print(f"  URL:         {pub.url}")
        else:
            print(f"  Status: FAILED")
            for diag in pub.diagnostics:
                print(f"  - {diag}")

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
        report_path = out_path.with_suffix(".report.json")
        atomic_write_text(report_path, result.report.to_json() + "\n")
        print(f"Wrote {report_path}")

    print()
    print(result.report.render_text())

    return 0 if result.report.status == "READY" else 0
