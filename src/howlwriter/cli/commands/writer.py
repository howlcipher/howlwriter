"""`howlwriter writer <prompt>` -- draft prose from an idea, notes, or assignment topic."""

from __future__ import annotations

import argparse
import sys

from howlwriter.academic.citations import AcademicCitationManager
from howlwriter.academic.identifiers import find_ungrounded_identifiers
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
        "writer",
        help="Draft prose from an idea or notes (model-backed).",
        description="Draft prose using an explicitly configured HowlPlane writer role.",
        epilog=(
            "Setup: install HowlPlane in the same Python environment or set "
            "HOWLPLANE_ROOT to its source checkout, then set "
            "HOWLPLANE_ROLE_WRITING_WRITER=<provider> to an available provider. "
            "See docs/howlplane-integration.md. No provider is selected automatically."
        ),
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
    parser.add_argument(
        "--fail-if-blocked",
        action="store_true",
        help=(
            "Exit 3 when the draft cites a work, or names an exact identifier such as a CVE, "
            "that is not in --sources or the prompt."
        ),
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

    problems = _unsupported_specifics(res.document, sources, args.prompt)
    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)
    return 3 if problems and args.fail_if_blocked else 0


def _unsupported_specifics(document, sources: list[Source], prompt: str) -> list[str]:
    """Citations and exact identifiers in the draft that nothing given to the model supports."""
    problems = []
    # A citation that matches no supplied source names a work nobody gave the model.
    unmatched = AcademicCitationManager().analyze_and_build_references(document, sources)
    if unmatched.unmatched_in_text_citations:
        cited = unmatched.unmatched_in_text_citations
        problems.append(f"the draft cites {len(cited)} work(s) that are not in the sources: " + "; ".join(cited))
    grounding = [prompt, *(s.retrieved_text or "" for s in sources)]
    invented = [f.identifier for f in find_ungrounded_identifiers(document.text, grounding)]
    if invented:
        problems.append(
            f"the draft names {len(invented)} exact identifier(s) found in no source or the prompt: "
            + "; ".join(invented)
        )
    return problems
