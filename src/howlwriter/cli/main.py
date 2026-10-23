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
    assignment,
    benchmark,
    cite,
    citations,
    editor,
    evaluate,
    factcheck,
    finalize,
    google,
    howl,
    humanize,
    interop,
    lint,
    native,
    outline,
    paper,
    project,
    publish,
    redpen,
    references,
    reply,
    research,
    runs,
    sources,
    ui,
    voice,
    writer,
)
from howlwriter.integration.model_role import HowlPlaneUnavailableError, ModelRoleNotConfiguredError

_COMMAND_MODULES = (
    assignment,
    benchmark,
    paper,
    publish,
    google,
    writer,
    editor,
    humanize,
    voice,
    evaluate,
    factcheck,
    research,
    sources,
    cite,
    citations,
    references,
    redpen,
    lint,
    finalize,
    howl,
    native,
    outline,
    project,
    reply,
    runs,
    ui,
    interop,
)


class _Parser(argparse.ArgumentParser):
    """argparse, except a usage error exits 1.

    Exit 2 means "a model step had no model chosen" (docs/agents.md). argparse's
    own 2 for a bad flag let a caller such as HowlPlane mistake an unsupported
    flag for a request for input.
    """

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="howlwriter",
        description="A controlled writing, editing, humanization, research, citation, "
        "provenance, and verification system.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"howlwriter {__version__}",
    )
    parser.add_argument(
        "--provider",
        metavar="MODEL",
        help="Model for writing steps when no HowlPlane role is bound: claude, agy, codex, or local. "
        "Without it you are asked when a step first needs a model (or set HOWLWRITER_PROVIDER).",
    )
    parser.add_argument(
        "--local-model",
        metavar="OLLAMA_MODEL",
        help="Which Ollama model 'local' runs, e.g. qwen2.5:7b-instruct (or set HOWLWRITER_LOCAL_MODEL). "
        "HowlPlane's default is a coding model.",
    )
    parser.add_argument(
        "--review-provider",
        metavar="MODEL",
        help="Model for independent review steps (must differ from the writer to be independent). "
        "Without it you are asked when needed (or set HOWLWRITER_REVIEW_PROVIDER).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in _COMMAND_MODULES:
        module.add_subparser(subparsers)
    sources.add_verify_subparser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _configure_model_choice(args)
        return args.handler(args)
    except HowlPlaneUnavailableError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ModelRoleNotConfiguredError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError, TypeError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _configure_model_choice(args: argparse.Namespace) -> None:
    """Apply --provider / environment choices; otherwise ask on a terminal when a model is needed."""
    from howlwriter.integration import provider_choice
    env_writer, env_reviewer = provider_choice.from_environment()
    writer = provider_choice.normalize(args.provider) if args.provider else env_writer
    reviewer = provider_choice.normalize(args.review_provider) if args.review_provider else env_reviewer
    # Read when the bridge is first created, so commands that never need a
    # model never import HowlPlane.
    provider_choice.PROCESS_DEFAULTS.update(
        writer=writer, reviewer=reviewer, interactive=sys.stdin.isatty(), local_model=args.local_model
    )


if __name__ == "__main__":
    raise SystemExit(main())
