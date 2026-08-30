"""`howlwriter editor <file>` -- real whitespace/heading normalization
(PassthroughEditor). Prose-level model-backed editing is not invoked here."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.domain.document import Document
from howlwriter.editing.editor import PassthroughEditor


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("editor", help="Normalize whitespace and heading markers.")
    parser.add_argument("path")
    parser.add_argument("--out", default=None, help="Write the normalized text here (default: stdout).")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    document = Document.parse(text, title=Path(args.path).stem)
    edited = PassthroughEditor().edit(document)
    if args.out:
        Path(args.out).write_text(edited.text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(edited.text)
    return 0
