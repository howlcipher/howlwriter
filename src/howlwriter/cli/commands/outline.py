"""`howlwriter outline validate <file>` -- check an outline before spending a run.

Validation is separated from generation because the failures it catches are
cheap to fix and expensive to discover late: a misspelled node kind, a claim id
a research request points at that does not exist, the same sentence marked
verbatim twice. Finding those after a paid generation is a waste; finding them
after publication is worse.

It also reports the generation-freedom state, which is the one number a user
most wants before running: it tells them whether the outline they just wrote
actually constrains the model as much as they think it does.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.domain.outline import (
    NodeKind,
    Outline,
    load_outline,
    validate_outline,
)
from howlwriter.outline.freedom import assess_freedom


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "outline", help="Work with authorship outlines."
    )
    sub = parser.add_subparsers(dest="outline_command", required=True)

    validate = sub.add_parser(
        "validate", help="Validate an outline and report generation freedom."
    )
    validate.add_argument("path", help="Path to an outline YAML or JSON file.")
    validate.set_defaults(handler=run_validate)

    show = sub.add_parser(
        "show", help="Show an outline's structure as HowlWriter reads it."
    )
    show.add_argument("path", help="Path to an outline YAML or JSON file.")
    show.set_defaults(handler=run_show)

    parser.set_defaults(handler=run_validate)
    return parser


def _load(path: str) -> Outline:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"outline not found: {path}")
    return load_outline(target)


def _report_freedom(outline: Outline) -> None:
    assessment = assess_freedom(outline)
    print(f"Generation freedom: {assessment.freedom.value}")
    for reason in assessment.reasons:
        print(f"  because {reason}")
    print(
        f"  supplied: {assessment.claims} claim(s), "
        f"{assessment.preserved_sentences} preserved passage(s), "
        f"{assessment.required_points} required point(s), "
        f"{assessment.examples} example(s), "
        f"{assessment.voice_seeds} voice seed(s)"
    )
    print(
        f"  user prose: {assessment.supplied_words} word(s) against a target of "
        f"{assessment.target_words} ({assessment.coverage:.0%})"
    )


def run_validate(args: argparse.Namespace) -> int:
    # load_outline validates on the way in, so a valid file has already been
    # checked by the time it returns. Re-running the check here is what lets an
    # invalid one report every problem instead of only the first.
    try:
        outline = _load(args.path)
    except ValueError as error:
        print(f"INVALID: {error}")
        return 1

    errors = validate_outline(outline)
    if errors:
        print("INVALID")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"VALID: {args.path}")
    print(f"  schema: {outline.schema}")
    print(f"  nodes:  {len(outline.all_nodes())}")
    _report_freedom(outline)
    return 0


def run_show(args: argparse.Namespace) -> int:
    outline = _load(args.path)
    print(f"{outline.title or outline.topic or '(untitled)'}")
    if outline.mode:
        print(f"mode: {outline.mode}")
    if outline.target_words:
        print(f"target: {outline.target_words} words")
    if outline.max_words:
        print(f"hard maximum: {outline.max_words} words")
    print(f"ordering enforced: {outline.enforce_order}")
    print()
    for node in outline.all_nodes():
        marker = "*" if node.is_required else " "
        preserved = " [VERBATIM]" if node.kind is NodeKind.PRESERVE else ""
        print(
            f"{marker} {node.id:22s} {node.kind.value:18s}"
            f" {node.text[:60]}{preserved}"
        )
    if outline.research:
        print()
        print("research:")
        for request in outline.research:
            flag = "required" if request.required else "optional"
            print(f"  {request.node_id:16s} ({flag}) {request.question}")
    print()
    _report_freedom(outline)
    return 0
