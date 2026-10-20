"""Owner-only command-line actions: refuse when nobody can be asked.

Some decisions belong to the person whose writing and materials these are:
attesting authorship, counting a Workshop answer as their writing, and
letting private evidence go to a remote model. A person at a terminal makes
them by running the command. Without a terminal (an AI agent, a script, a
pipe) the command refuses unless ``--owner-confirmed`` says the owner gave
this exact decision, and the decision is recorded as relayed where a record
exists.
"""

from __future__ import annotations

import argparse
import sys

EXIT_OWNER_REQUIRED = 4

SOURCE_TERMINAL = "user_attestation"
SOURCE_RELAYED = "owner_relayed"

HELP = (
    "The owner gave this exact decision (e.g. told an AI agent running this command). "
    "Required when there is no terminal; never pass it on your own judgement."
)


class OwnerConfirmationRequired(Exception):
    """An owner-only change was requested where nobody can be asked."""


def has_terminal() -> bool:
    return bool(sys.stdin is not None and sys.stdin.isatty())


def add_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--owner-confirmed", action="store_true", help=HELP)


def source(args: argparse.Namespace, action: str, why: str, *, relay_allowed: bool = True) -> str:
    """Who is making this owner-only change: the person at a terminal, or an explicit relay."""
    if has_terminal():
        return SOURCE_TERMINAL
    if relay_allowed and getattr(args, "owner_confirmed", False):
        return SOURCE_RELAYED
    how = (
        "run it in a terminal"
        if not relay_allowed
        else "run it in a terminal, or, if the owner told you this exact decision, rerun with "
        "--owner-confirmed"
    )
    raise OwnerConfirmationRequired(
        f"{action} {why}, and only the owner may decide it. There is no terminal to ask them; "
        f"{how}. Nothing was changed."
    )


def actor(args: argparse.Namespace) -> str:
    """Who is making a change anyone may make, for the record: the user, a relay, or an agent."""
    if has_terminal():
        return "user"
    return "owner_relayed" if getattr(args, "owner_confirmed", False) else "agent"


def report(error: OwnerConfirmationRequired) -> int:
    print(f"error: {error}", file=sys.stderr)
    return EXIT_OWNER_REQUIRED
