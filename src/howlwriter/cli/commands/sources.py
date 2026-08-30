"""`howlwriter sources <sources.json>` -- inspects collected source
metadata through the provenance graph, honestly reporting which sources
were never actually retrieved."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.domain.source import source_from_dict


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("sources", help="Inspect collected source metadata.")
    parser.add_argument("sources_path")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.sources_path).read_text(encoding="utf-8"))
    graph = ProvenanceGraph()
    for entry in raw:
        graph.add_source(source_from_dict(entry))

    print(f"{len(graph.sources)} source(s) loaded.")
    unaccessed = graph.unaccessed_sources()
    if unaccessed:
        print("Never actually retrieved:")
        for source in unaccessed:
            print(f"  - [{source.id}] {source.title}")
    else:
        print("All sources were retrieved.")
    return 0
