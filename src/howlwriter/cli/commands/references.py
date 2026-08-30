"""`howlwriter references <style> <sources.json>` -- generates a full
reference/bibliography page. A thin, named-per-spec sibling of `cite
... --form page`, kept separate since the spec lists /cite and
/references as distinct independently-callable commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from howlwriter.citations.styles import CitationStyle, get_formatter
from howlwriter.domain.source import source_from_dict


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("references", help="Generate a reference page from source metadata.")
    parser.add_argument("style", choices=[s.value for s in CitationStyle])
    parser.add_argument("sources_path")
    parser.add_argument("--out", default=None)
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    formatter = get_formatter(CitationStyle(args.style))
    raw = json.loads(Path(args.sources_path).read_text(encoding="utf-8"))
    sources = [source_from_dict(entry) for entry in raw]

    result = formatter.reference_page(sources)
    if args.out:
        Path(args.out).write_text(result.text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(result.text)
    for warning in result.warnings:
        print(f"{warning.code}: {warning.message}", file=sys.stderr)
    return 0
