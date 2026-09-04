"""HowlWriter CLI entry point.

A thin argparse wrapper: every subcommand module parses its own arguments
and calls straight into the corresponding howlwriter.<domain> function. No
business logic lives in the CLI package itself.
"""

from __future__ import annotations

import argparse
import sys

from howlwriter import __version__
from howlwriter.cli.commands import (
    cite,
    editor,
    factcheck,
    finalize,
    howl,
    humanize,
    lint,
    outline,
    paper,
    redpen,
    references,
    research,
    runs,
    sources,
    ui,
    voice,
    writer,
)
from howlwriter.integration.model_role import ModelRoleNotConfiguredError

_COMMAND_MODULES = (
    paper,
    writer,
    editor,
    humanize,
    voice,
    factcheck,
    research,
    sources,
    cite,
    references,
    redpen,
    lint,
    finalize,
    howl,
    outline,
    runs,
    ui,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="howlwriter",
        description="A controlled writing, editing, humanization, research, citation, "
        "provenance, and verification system.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"howlwriter {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in _COMMAND_MODULES:
        module.add_subparser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ModelRoleNotConfiguredError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError, TypeError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
