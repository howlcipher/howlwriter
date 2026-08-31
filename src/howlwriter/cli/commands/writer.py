"""`howlwriter writer <prompt>` -- draft prose from an idea, notes, or assignment topic."""

from __future__ import annotations

import argparse
import sys

from howlwriter.academic.research import load_sources_file
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.academic.writer import ModelAcademicWriter
from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.source import Source
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import (
    NotConfiguredRole,
    WritingRole,
)


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "writer", help="Draft prose from an idea or notes (model-backed)."
    )
    parser.add_argument("prompt", help="The idea, notes, or topic to write from.")
    parser.add_argument(
        "--sources",
        default=None,
        help="Optional path to sources.json to ground the draft.",
    )
    parser.add_argument(
        "--target-words",
        type=int,
        default=500,
        help="Target body word count (default: 500).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write drafted text to this file.",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    bridge = get_howlplane_bridge()
    if not bridge.is_role_configured(WritingRole.WRITER):
        NotConfiguredRole(WritingRole.WRITER).run(args.prompt)
        return 0

    config = ConfigLoader().load()
    sources: list[Source] = []
    if args.sources:
        try:
            sources = load_sources_file(args.sources)
        except Exception as exc:
            print(f"warning: could not load sources '{args.sources}': {exc}", file=sys.stderr)

    spec = AssignmentSpec(
        title=args.prompt[:60],
        topic=args.prompt,
        target_words=args.target_words,
    )

    writer = ModelAcademicWriter()
    res = writer.draft_paper(spec, sources, config=config)

    if args.out:
        atomic_write_text(args.out, res.document.text)
        print(f"Wrote {args.out}")
    else:
        print(res.document.text)

    return 0
