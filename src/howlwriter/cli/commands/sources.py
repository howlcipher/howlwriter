"""`howlwriter sources <sources.json>` or `howlwriter sources verify <file>` -- source inspection & verification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.domain.source import Source, SourceType, source_from_dict
from howlwriter.research.integrity import SourceIntegrityVerifier


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("sources", help="Inspect and verify collected source metadata and links.")
    parser.add_argument("first_arg", metavar="path_or_subcommand", help="Path to sources file/markdown, or 'verify'.")
    parser.add_argument("target_path", nargs="?", default=None, help="Target file when using 'verify'.")
    parser.add_argument("--verify", action="store_true", help="Run operational integrity verification on sources.")
    parser.add_argument("--json", dest="output_json", action="store_true", help="Output machine-readable JSON verification report.")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout in seconds for source integrity verification.")
    parser.set_defaults(handler=run)
    return parser


def add_verify_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("verify-sources", help="Verify operational integrity of sources in a file.")
    parser.add_argument("target_path", help="Path to sources file or markdown.")
    parser.add_argument("--json", dest="output_json", action="store_true", help="Output machine-readable JSON verification report.")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout in seconds for source integrity verification.")

    def _verify_handler(args: argparse.Namespace) -> int:
        args.first_arg = "verify"
        return run(args)

    parser.set_defaults(handler=_verify_handler)
    return parser


def extract_sources_from_path(path: Path) -> list[Source]:
    """Extracts Source objects from a sources.json, assignment YAML, or Markdown paper."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    text = path.read_text(encoding="utf-8")

    # 1. JSON file
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [source_from_dict(e) for e in data if isinstance(e, dict)]
            if isinstance(data, dict):
                if "sources" in data and isinstance(data["sources"], list):
                    return [source_from_dict(e) for e in data["sources"] if isinstance(e, dict)]
        except Exception:
            pass

    # 2. Markdown or plain text with URLs and DOIs
    sources: list[Source] = []
    # Find DOIs
    dois = re.findall(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b", text)
    seen_dois = set()
    for doi in dois:
        clean_doi = doi.rstrip(".,;)")
        if clean_doi.lower() not in seen_dois:
            seen_dois.add(clean_doi.lower())
            sources.append(
                Source(
                    id=f"S{len(sources)+1:03d}",
                    title=f"DOI Reference {clean_doi}",
                    authors=["Unknown"],
                    doi=clean_doi,
                    source_type=SourceType.JOURNAL_ARTICLE,
                )
            )

    # Find Markdown links [text](url)
    md_links = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", text)
    seen_urls = set()
    for title, url in md_links:
        clean_url = url.strip()
        if clean_url.lower() not in seen_urls:
            seen_urls.add(clean_url.lower())
            sources.append(
                Source(
                    id=f"S{len(sources)+1:03d}",
                    title=title.strip() or "Web Source",
                    authors=["Unknown"],
                    url=clean_url,
                    source_type=SourceType.WEBSITE,
                )
            )

    # Find raw URLs
    raw_urls = re.findall(r"\b(https?://[^\s()<>\[\]]+)\b", text)
    for raw_url in raw_urls:
        clean_url = raw_url.rstrip(".,;)")
        if clean_url.lower() not in seen_urls:
            seen_urls.add(clean_url.lower())
            sources.append(
                Source(
                    id=f"S{len(sources)+1:03d}",
                    title=f"Web Source {clean_url}",
                    authors=["Unknown"],
                    url=clean_url,
                    source_type=SourceType.WEBSITE,
                )
            )

    return sources


def run(args: argparse.Namespace) -> int:
    is_verify = False
    file_arg: str

    if args.first_arg == "verify":
        is_verify = True
        if not args.target_path:
            print("error: 'howlwriter sources verify' requires a target file path", file=sys.stderr)
            return 1
        file_arg = args.target_path
    else:
        file_arg = args.first_arg
        if getattr(args, "verify", False):
            is_verify = True

    target_p = Path(file_arg)
    if not target_p.is_file():
        print(f"error: file not found: '{file_arg}'", file=sys.stderr)
        return 1

    try:
        sources = extract_sources_from_path(target_p)
    except Exception as exc:
        print(f"error: failed to load sources from '{file_arg}': {exc}", file=sys.stderr)
        return 1

    if is_verify:
        verifier = SourceIntegrityVerifier(timeout_seconds=args.timeout)
        report = verifier.verify_all(sources)

        if getattr(args, "output_json", False):
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.render_text())

        return 0 if report.status == "PASS" else (1 if report.status == "BLOCKED" else 0)

    # Default inspection mode
    graph = ProvenanceGraph()
    for s in sources:
        graph.add_source(s)

    print(f"{len(graph.sources)} source(s) loaded.")
    unaccessed = graph.unaccessed_sources()
    if unaccessed:
        print("\nNever actually retrieved:")
        for source in unaccessed:
            print(f"  - [{source.id}] {source.title}")
    else:
        print("All sources were retrieved.")
    return 0
