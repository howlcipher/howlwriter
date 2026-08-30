"""`howlwriter cite <style> <sources.json> [--form ...]` -- formats
citations from collected source metadata. Never invents missing metadata;
CITATION_METADATA_MISSING warnings are printed to stderr."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from howlwriter.citations.apa7 import CitationResult
from howlwriter.citations.styles import CitationStyle, get_formatter
from howlwriter.domain.source import Source, SourceType


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("cite", help="Format citations from collected source metadata.")
    parser.add_argument("style", choices=[s.value for s in CitationStyle], help="Citation style.")
    parser.add_argument("sources_path", help="Path to a JSON file containing a list of source objects.")
    parser.add_argument(
        "--form",
        choices=["reference", "in-text", "narrative", "page"],
        default="page",
        help="Which citation form to render (default: a full reference page).",
    )
    parser.set_defaults(handler=run)
    return parser


def _load_sources(path: str) -> list[Source]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = []
    for entry in raw:
        entry = dict(entry)
        if entry.get("publication_date"):
            entry["publication_date"] = date.fromisoformat(entry["publication_date"])
        if entry.get("access_date"):
            entry["access_date"] = date.fromisoformat(entry["access_date"])
        if entry.get("source_type"):
            entry["source_type"] = SourceType(entry["source_type"])
        sources.append(Source.from_dict(entry))
    return sources


def _print_warnings(result: CitationResult) -> None:
    for warning in result.warnings:
        print(f"{warning.code}: {warning.message}", file=sys.stderr)


def run(args: argparse.Namespace) -> int:
    style = CitationStyle(args.style)
    formatter = get_formatter(style)
    sources = _load_sources(args.sources_path)

    if args.form == "page":
        result = formatter.reference_page(sources)
        print(result.text)
        _print_warnings(result)
        return 0

    method = {
        "reference": formatter.reference_entry,
        "in-text": formatter.in_text_parenthetical,
        "narrative": formatter.narrative,
    }[args.form]

    for source in sources:
        result = method(source)
        print(result.text)
        _print_warnings(result)
    return 0
