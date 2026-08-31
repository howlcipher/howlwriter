"""`howlwriter research <query>` -- research scholarly and authoritative sources for a topic."""

from __future__ import annotations

import argparse

from howlwriter.academic.research import AcademicResearcher, save_sources_file
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import (
    NotConfiguredRole,
    WritingRole,
)


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "research",
        help="Research a query for supporting sources (scholarly/model-backed).",
    )
    parser.add_argument("query", help="Search topic or research question.")
    parser.add_argument(
        "--max-sources",
        type=int,
        default=5,
        help="Maximum number of sources to retrieve (default: 5).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Path to save retrieved sources JSON (e.g. sources.json).",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    bridge = get_howlplane_bridge()
    if not bridge.is_role_configured(WritingRole.RESEARCHER):
        NotConfiguredRole(WritingRole.RESEARCHER).run(args.query)
        return 0

    spec = AssignmentSpec(
        title=args.query[:50],
        topic=args.query,
    )
    researcher = AcademicResearcher()
    sources = researcher.execute_research(spec, max_sources_total=args.max_sources)

    print(f"Retrieved {len(sources)} sources for query: '{args.query}'\n")
    for s in sources:
        authors_str = ", ".join(s.authors) if s.authors else "No listed author"
        year_str = str(s.publication_date.year) if s.publication_date else "n.d."
        print(f"[{s.id}] {s.title}")
        print(f"      Author(s): {authors_str} ({year_str})")
        if s.publisher:
            print(f"      Publisher: {s.publisher}")
        if s.doi:
            print(f"      DOI:       https://doi.org/{s.doi}")
        elif s.url:
            print(f"      URL:       {s.url}")
        print()

    if args.out:
        save_sources_file(args.out, sources)
        print(f"Saved {len(sources)} sources to {args.out}")

    return 0
