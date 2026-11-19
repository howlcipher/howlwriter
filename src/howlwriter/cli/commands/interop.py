"""`howlwriter interop` -- the howl.interop/v1 descriptor other Howl components check.

HowlPlane runs `writer`, `project draft`, `humanize`, `lint` and `native
request|write`; `howl doctor` reads this descriptor to check those commands and
flags still exist. It is built from the live parser, so it cannot list a flag
HowlWriter does not accept. Contract:
https://github.com/howlcipher/howl/blob/main/docs/INTEROP.md
"""

from __future__ import annotations

import argparse
import json

from howlwriter import __version__

SCHEMA = "howl.interop/v1"

# docs/agents.md, "Exit codes".
EXIT_CODES = {
    "0": "success",
    "1": "error, including usage errors (such as invalid runs prune retention arguments), "
    "or a chosen model that cannot run because HowlPlane is unavailable",
    "2": "a model step had no model chosen; project: refused by the remote-inference gate or browser policy; "
    "voice scan/sync: the drive is not mounted",
    "3": "finished but not ready (paper report status not READY, project validate verdict, voice profile, "
    "--fail-if-blocked, a citations verify / reply check / assignment check result that is not verified, "
    "grounded or ready, or a linkedin list / validate / verify / review / reschedule-all outcome that is "
    "not ready)",
    "4": "an owner-only decision was asked for without a terminal or --owner-confirmed",
    "130": "project: cancelled",
}

ENV = [
    "HOWLWRITER_PROVIDER",
    "HOWLWRITER_REVIEW_PROVIDER",
    "HOWLWRITER_LOCAL_MODEL",
    "HOWLPLANE_ROOT",
    "HOWLPLANE_HOME",
    "HOWLPLANE_DIR",
    "HOWL_FORBID_LOCAL_INFERENCE",
    "HOWL_DEV_DIR",
    "HOWLWRITER_VOICES_DIR",
    "HOWLWRITER_RUNS_DIR",
    "HOWLWRITER_PROJECTS_DIR",
    "HOWLWRITER_IDENTITIES_DIR",
    "HOWLWRITER_PREFERENCES_FILE",
    "HOWLWRITER_CREDENTIALS_DIR",
    "HOWLWRITER_GOOGLE_CLIENT_CONFIG",
    "HOWLWRITER_HOWLPROOF",
    "HOWLWRITER_LINKEDIN_REPO",
    "HOWLWRITER_LINKEDIN_APPROVAL_KEY",
    "HOWLWRITER_LINKEDIN_APPROVAL_REF",
    "HOWLWRITER_LINKEDIN_APPROVAL_WORKFLOW",
    "HOWLWRITER_LINKEDIN_APPROVER_ID",
]

# Every `linkedin` subcommand prints a howl.result/v1 envelope under --json.
LINKEDIN_COMMANDS = (
    "init", "add", "edit", "list", "show", "validate", "submit", "schedule", "cancel", "archive",
    "queue", "evaluate", "reschedule", "reschedule-all", "verify", "review", "approve",
    "authorize-schedule", "pause", "resume", "reconcile",
)

EMITS = {
    ("native", "request"): ["howlwriter.request/v1"],
    ("native", "write"): ["howlwriter.copy_package/v1"],
    ("interop",): [SCHEMA],
    **{("linkedin", name): ["howl.result/v1"] for name in LINKEDIN_COMMANDS},
}

ACCEPTS = {
    ("native", "request"): ["howl.candidate/v1"],
    ("native", "write"): ["howlwriter.request/v1"],
}


def _flags(parser: argparse.ArgumentParser) -> list[str]:
    return sorted(
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in ("-h", "--help")
    )


def describe(parser: argparse.ArgumentParser) -> dict:
    """The descriptor for `parser` and every nested subcommand."""
    commands: list[dict] = []

    def walk(current: argparse.ArgumentParser, path: list[str]) -> None:
        flags = _flags(current)
        entry: dict = {"path": path, "flags": flags, "json": "--json" in flags or tuple(path) in EMITS}
        if tuple(path) in EMITS:
            entry["emits"] = EMITS[tuple(path)]
        if tuple(path) in ACCEPTS:
            entry["accepts"] = ACCEPTS[tuple(path)]
        commands.append(entry)
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    walk(sub, [*path, name])

    walk(parser, [])
    return {
        "schema": SCHEMA,
        "component": "howlwriter",
        "version": __version__,
        "commands": commands,
        "exit_codes": EXIT_CODES,
        "env": ENV,
        "consumes": [],
    }


def _run(args: argparse.Namespace) -> int:
    from howlwriter.cli.main import build_parser

    print(json.dumps(describe(build_parser()), indent=2))
    return 0


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "interop", help="Print the howl.interop/v1 descriptor other Howl components check."
    )
    parser.add_argument("--json", action="store_true", help="JSON output (the default).")
    parser.set_defaults(handler=_run)
    return parser
