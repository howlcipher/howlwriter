"""`howlwriter writer <prompt>` -- drafting from an idea or notes is
entirely model-backed; HowlWriter has no deterministic way to write prose
from nothing. Always surfaces ModelRoleNotConfiguredError until a WRITER
role implementation is wired in."""

from __future__ import annotations

import argparse

from howlwriter.integration.model_role import NotConfiguredRole, WritingRole


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("writer", help="Draft prose from an idea or notes (model-backed).")
    parser.add_argument("prompt", help="The idea, notes, or rough draft to write from.")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    NotConfiguredRole(WritingRole.WRITER).run(args.prompt)
    return 0
