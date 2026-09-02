"""`howlwriter voice ...` -- build, inspect, rebuild and manage personal voices.

`voice learn` is the original deterministic corpus-stats command and is left
exactly as it was: it takes plain text files and prints a profile.

`voice build` is the corpus pipeline. It walks real source roots, extracts
prose from real document formats, works out what the user actually wrote,
deduplicates, measures, analyzes, validates against a holdout, and saves a
private profile outside the repository.

Inspection is summaries by default. A voice is built from someone's own
writing, so `voice inspect` reports counts, tendencies, and confidence but
never a passage and never a list of filenames. `--sources` exists for when the
user explicitly asks to see which local files were used.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from howlwriter.domain.voice import VoiceProfile
from howlwriter.voice.corpus.build import build_voice
from howlwriter.voice.corpus.store import VoiceStore, validate_name
from howlwriter.voice.learner import CorpusStatsLearner


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("voice", help="Voice profile operations.")
    voice_subparsers = parser.add_subparsers(dest="voice_command", required=True)

    # --- legacy: voice learn ---
    learn_parser = voice_subparsers.add_parser(
        "learn", help="Learn a voice profile from a corpus of text files."
    )
    learn_parser.add_argument("paths", nargs="+", help="One or more text files making up the corpus.")
    learn_parser.add_argument("--author", default="", help="Author name to label the profile with.")
    learn_parser.add_argument("--out", default=None, help="Write the learned profile as JSON to this path.")
    learn_parser.set_defaults(handler=run_learn)

    # --- voice build ---
    build_parser = voice_subparsers.add_parser(
        "build",
        help="Build a private personal voice from a corpus of your own writing.",
    )
    build_parser.add_argument("--name", required=True, help="Name for the voice (e.g. 'jane').")
    build_parser.add_argument(
        "--source", dest="sources", action="append", required=True, metavar="PATH",
        help="A directory or file to read. Repeat for multiple roots; overlapping "
             "roots are canonicalized and deduplicated before anything is read.",
    )
    build_parser.add_argument(
        "--recursive", action="store_true", default=True,
        help="Walk source directories recursively (default).",
    )
    build_parser.add_argument(
        "--no-recursive", dest="recursive", action="store_false",
        help="Only read files directly inside each source directory.",
    )
    build_parser.add_argument(
        "--deterministic", action="store_true",
        help="Skip model-backed trait analysis; build from measurable features only.",
    )
    build_parser.add_argument(
        "--shared-style", action="store_true",
        help="Build a generic shared style rather than a personal voice. A shared "
             "style must not claim to imitate an individual.",
    )
    build_parser.add_argument(
        "--no-cache", dest="reuse_cache", action="store_false", default=True,
        help="Re-extract and re-measure every document instead of reusing cached "
             "derived features for unchanged files.",
    )
    build_parser.set_defaults(handler=run_build)

    # --- voice rebuild ---
    rebuild_parser = voice_subparsers.add_parser(
        "rebuild",
        help="Rebuild an existing voice from its stored source roots, preserving overrides.",
    )
    rebuild_parser.add_argument("name", help="Name of the voice to rebuild.")
    rebuild_parser.add_argument(
        "--source", dest="sources", action="append", metavar="PATH",
        help="Additional source root to include from now on.",
    )
    rebuild_parser.add_argument(
        "--deterministic", action="store_true",
        help="Skip model-backed trait analysis.",
    )
    rebuild_parser.add_argument(
        "--no-cache", dest="reuse_cache", action="store_false", default=True,
        help="Re-extract and re-measure every document.",
    )
    rebuild_parser.set_defaults(handler=run_rebuild)

    # --- voice inspect ---
    inspect_parser = voice_subparsers.add_parser(
        "inspect", help="Show what a voice learned, as summaries."
    )
    inspect_parser.add_argument("name", help="Name of the voice to inspect.")
    inspect_parser.add_argument(
        "--verbose", action="store_true",
        help="Include feature distributions, per-trait evidence and build metadata.",
    )
    inspect_parser.add_argument(
        "--sources", action="store_true",
        help="List the local files this voice was built from. Off by default because "
             "the file list is private.",
    )
    inspect_parser.set_defaults(handler=run_inspect)

    # --- voice list / remove ---
    list_parser = voice_subparsers.add_parser("list", help="List local personal voices.")
    list_parser.set_defaults(handler=run_list)

    remove_parser = voice_subparsers.add_parser("remove", help="Delete a local voice.")
    remove_parser.add_argument("name", help="Name of the voice to delete.")
    remove_parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt."
    )
    remove_parser.set_defaults(handler=run_remove)

    return parser


# --- legacy ------------------------------------------------------------

def run_learn(args: argparse.Namespace) -> int:
    corpus = [Path(p).read_text(encoding="utf-8") for p in args.paths]
    profile = CorpusStatsLearner().learn(corpus, author_name=args.author)
    rendered = profile.to_json()
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
        print(f"Wrote voice profile to {args.out}")
    else:
        print(rendered)
    return 0


# --- build / rebuild ---------------------------------------------------

def _stage_reporter() -> object:
    """Print each stage as it starts and finishes.

    Named stages, not a percentage: before extraction runs there is no honest
    basis for estimating how long it will take, and an invented progress bar
    is worse than none.
    """
    state: dict[str, object] = {"current": None}

    def report(stage_id: str, status: str, data: dict) -> None:
        label = data.get("label", stage_id)
        if status == "RUNNING":
            if state["current"] != stage_id:
                state["current"] = stage_id
                print(f"  {label}...", flush=True)
            elif "batch" in data:
                print(f"    batch {data['batch']}/{data['batches']}", flush=True)
        elif status == "DONE":
            details = ", ".join(
                f"{key}={value}" for key, value in data.items()
                if key != "label" and value not in (None, "", [], {})
            )
            print(f"  {label}: done{f' ({details})' if details else ''}", flush=True)

    return report


def _run_build(
    name: str,
    sources: list[str],
    *,
    deterministic: bool,
    recursive: bool,
    reuse_cache: bool,
    profile_type: str,
) -> int:
    print(f"Building voice '{name}' from {len(sources)} source root(s).")
    outcome = build_voice(
        name,
        list(sources),
        recursive=recursive,
        deterministic_only=deterministic,
        reuse_cache=reuse_cache,
        profile_type=profile_type,
        stage_callback=_stage_reporter(),
    )
    print()
    print(render_inspection(outcome.profile, VoiceStore(name)))
    print()
    print(f"Saved to {outcome.directory}")
    print("This is private local data. It is not tracked by Git and is not distributed.")
    if outcome.warnings:
        print()
        print("Notes:")
        for warning in outcome.warnings:
            print(f"  - {warning}")
    return 0


def run_build(args: argparse.Namespace) -> int:
    return _run_build(
        validate_name(args.name),
        args.sources,
        deterministic=args.deterministic,
        recursive=args.recursive,
        reuse_cache=args.reuse_cache,
        profile_type="shared_style" if args.shared_style else "personal_voice",
    )


def run_rebuild(args: argparse.Namespace) -> int:
    name = validate_name(args.name)
    store = VoiceStore(name)
    if not store.exists():
        raise FileNotFoundError(
            f"no voice named '{name}'. Build one with: "
            f"howlwriter voice build --name {name} --source <path>"
        )

    roots = store.load_roots()
    for extra in (args.sources or []):
        if extra not in roots:
            roots.append(extra)
    if not roots:
        raise ValueError(
            f"voice '{name}' has no stored source roots; pass --source to supply them"
        )

    profile = store.load_profile()
    return _run_build(
        name,
        roots,
        deterministic=args.deterministic,
        recursive=True,
        reuse_cache=args.reuse_cache,
        profile_type=profile.profile_type,
    )


# --- inspect -----------------------------------------------------------

def _band(confidence: float) -> str:
    if confidence >= 0.75:
        return "HIGH"
    if confidence >= 0.5:
        return "MEDIUM"
    if confidence >= 0.3:
        return "LOW"
    return "VERY LOW"


def render_inspection(
    profile: VoiceProfile,
    store: VoiceStore,
    *,
    verbose: bool = False,
) -> str:
    """Render a voice as a summary.

    Counts, tendencies, confidence and validation bands. No passages, no
    sentences, no filenames -- everything here is safe to read aloud.
    """
    lines: list[str] = []
    kind = "Shared style" if profile.profile_type == "shared_style" else "Voice"
    lines.append(f"{kind}: {profile.profile_name or store.name}")
    if profile.built_at:
        lines.append(f"Built: {profile.built_at}")

    summary = profile.corpus_summary
    if summary is not None:
        lines += [
            "",
            "Corpus",
            f"  Documents discovered:      {summary.documents_discovered}",
            f"  Unique canonical files:    {summary.unique_canonical_files}",
            f"  Candidate prose files:     {summary.candidate_prose_files}",
            f"  Included for profile:      {summary.included_documents}",
            f"  Holdout:                   {summary.holdout_documents}",
            f"  Excluded:                  {summary.excluded_documents}",
            f"  Held for review:           {summary.held_for_review_documents}",
            f"  Duplicate/revision groups: {summary.revision_groups}",
            f"  Exact duplicates:          {summary.exact_duplicates}",
            f"  Cross-format duplicates:   {summary.cross_format_duplicates}",
            f"  Extraction failures:       {summary.extraction_failures}",
            f"  Scanned / unreadable:      {summary.scanned_or_unreadable}",
            "",
            f"  Training words:            {summary.training_words:,}",
            f"  Holdout words:             {summary.holdout_words:,}",
            f"  Corpus sufficiency:        {summary.sufficiency.upper()}",
        ]
        if summary.documents_by_context:
            lines.append("")
            lines.append("Contexts")
            for context, count in sorted(summary.documents_by_context.items()):
                words = summary.words_by_context.get(context, 0)
                lines.append(f"  {context.title():14} {count:4} documents, {words:,} words")

    # --- traits, split by how well supported they are ---
    strong = {n: t for n, t in profile.traits.items() if t.confidence >= 0.5}
    weak = {n: t for n, t in profile.traits.items() if t.confidence < 0.5}

    if strong:
        lines += ["", "Strong global patterns"]
        for name, trait in sorted(strong.items(), key=lambda kv: -kv[1].confidence):
            detail = (
                f"  ({_band(trait.confidence)}, {trait.supporting_documents} docs, "
                f"{trait.agreement:.0%} agreement)"
                if verbose else f"  ({_band(trait.confidence)})"
            )
            lines.append(f"  - {name.replace('_', ' ')}: {trait.value}{detail}")

    for context_name, context in sorted(profile.contexts.items()):
        if not context.traits:
            continue
        lines += [
            "",
            f"{context_name.title()} "
            f"({context.document_count} docs, {context.word_count:,} words, "
            f"{context.sufficiency})",
        ]
        for name, trait in sorted(context.traits.items(), key=lambda kv: -kv[1].confidence):
            lines.append(
                f"  - {name.replace('_', ' ')}: {trait.value}  ({_band(trait.confidence)})"
            )

    if weak:
        lines += ["", "Lower-confidence traits"]
        for name, trait in sorted(weak.items(), key=lambda kv: -kv[1].confidence):
            lines.append(
                f"  - {name.replace('_', ' ')}: {trait.value}  "
                f"({_band(trait.confidence)}, {trait.agreement:.0%} agreement)"
            )

    validation = profile.validation
    if validation is not None:
        lines += ["", "Validation (holdout documents the profile never saw)"]
        if validation.alignment:
            for dimension, band in validation.alignment.items():
                lines.append(f"  {dimension.replace('_', ' ').title():32} {band}")
        else:
            lines.append("  Not performed -- the corpus was too small to hold documents back.")
        lines.append("")
        lines.append(f"  Overall profile confidence:   {validation.overall_confidence}")
        lines.append(f"  Voice diversity preservation: {validation.diversity_preservation}")
        lines.append(
            "  These are alignment bands, not an authorship probability. They say how "
            "well the profile"
        )
        lines.append(
            "  describes unseen writing from the same corpus, and nothing about who "
            "wrote anything."
        )

    overrides = profile.overrides
    if overrides is not None and (overrides.preserve or overrides.avoid or overrides.traits):
        lines += ["", "Your overrides (these outrank the generated traits)"]
        for item in overrides.preserve:
            lines.append(f"  preserve: {item}")
        for item in overrides.avoid:
            lines.append(f"  avoid:    {item}")
        for name, value in sorted(overrides.traits.items()):
            lines.append(f"  {name}: {value}")

    if verbose:
        lines += _verbose_sections(profile, store)

    if profile.warnings:
        lines += ["", "Notes"]
        for warning in profile.warnings:
            lines.append(f"  - {warning}")

    return "\n".join(lines)


def _verbose_sections(profile: VoiceProfile, store: VoiceStore) -> list[str]:
    lines: list[str] = []
    distributions = profile.distributions
    if distributions is not None:
        lines += ["", "Measured distributions"]
        for name, value in sorted(distributions.to_dict().items()):
            if value is None:
                continue
            lines.append(f"  {name.replace('_', ' '):36} {value}")

    summary = profile.corpus_summary
    if summary is not None and summary.quality_classifications:
        lines += ["", "Document classifications"]
        for name, count in sorted(summary.quality_classifications.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name:44} {count}")
    if summary is not None and summary.exclusion_reasons:
        lines += ["", "Exclusion reasons"]
        for name, count in sorted(summary.exclusion_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name:44} {count}")
    if summary is not None and summary.sufficiency_warnings:
        lines += ["", "Sufficiency warnings"]
        for warning in summary.sufficiency_warnings:
            lines.append(f"  - {warning}")

    build = store.load_build()
    if build.built_at:
        lines += [
            "", "Build",
            f"  Duration:  {build.duration_seconds}s",
            f"  Status:    {build.status}",
            f"  Providers: {', '.join(build.providers) or 'none (deterministic only)'}",
        ]
        if build.stages:
            lines.append("  Stages:")
            for stage, seconds in build.stages.items():
                lines.append(f"    {stage:16} {seconds}s")
    return lines


def run_inspect(args: argparse.Namespace) -> int:
    store = VoiceStore(validate_name(args.name))
    profile = store.load_profile()
    profile.overrides = store.load_overrides()
    print(render_inspection(profile, store, verbose=args.verbose))

    if args.sources:
        # Only on explicit request: the file list is private, and dumping it
        # by default would leak a map of someone's drive into any terminal
        # they happened to share.
        print()
        print("Source files (private; shown because you asked with --sources)")
        for key, record in sorted(store.load_sources().items()):
            state = record.inclusion or record.classification
            print(f"  [{state:18}] {record.words:6} words  {record.context:12}  {key}")
    else:
        print()
        print("Run with --sources to list the local files this voice was built from.")
    return 0


# --- list / remove -----------------------------------------------------

def run_list(args: argparse.Namespace) -> int:
    names = VoiceStore.list_names()
    if not names:
        print("No local voices yet.")
        print("Build one with: howlwriter voice build --name <name> --source <path>")
        return 0
    print(f"Local voices (in {VoiceStore(names[0]).root}):")
    for name in names:
        store = VoiceStore(name)
        try:
            profile = store.load_profile()
        except (OSError, ValueError):
            print(f"  {name:20} (unreadable profile)")
            continue
        summary = profile.corpus_summary
        confidence = profile.validation.overall_confidence if profile.validation else "UNKNOWN"
        documents = summary.included_documents if summary else 0
        words = summary.training_words if summary else 0
        print(
            f"  {name:20} {profile.profile_type:14} "
            f"{documents:3} docs  {words:>8,} words  confidence {confidence}"
        )
    return 0


def run_remove(args: argparse.Namespace) -> int:
    name = validate_name(args.name)
    store = VoiceStore(name)
    if not store.exists():
        print(f"No voice named '{name}'.", file=sys.stderr)
        return 1
    if not args.yes:
        answer = input(f"Delete voice '{name}' and everything in {store.directory}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 0
    store.delete()
    print(f"Deleted voice '{name}'.")
    return 0
