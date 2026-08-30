"""`howlwriter finalize <original> <revised>` -- runs the meaning
preservation check standalone, outside the full `howl` pipeline, for
comparing an already-produced rewrite against its source."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.domain.document import Document
from howlwriter.review.meaning import MeaningPreservationReviewer


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("finalize", help="Check meaning preservation between two files.")
    parser.add_argument("original_path")
    parser.add_argument("revised_path")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    original = Document.parse(Path(args.original_path).read_text(encoding="utf-8"), title="original")
    revised = Document.parse(Path(args.revised_path).read_text(encoding="utf-8"), title="revised")
    result = MeaningPreservationReviewer().compare(original, revised)

    print(f"MEANING PRESERVATION: {result.status}")
    for diff in result.diffs:
        print(f"- [{diff.kind}] {diff.description}")
    return 0
