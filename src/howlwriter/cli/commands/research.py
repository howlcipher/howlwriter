"""`howlwriter research <query>` -- always surfaces
ModelRoleNotConfiguredError. Real network research needs either a model
call or a search backend HowlWriter deliberately does not provide on its
own; see docs/howlplane-integration.md."""

from __future__ import annotations

import argparse

from howlwriter.research.researcher import NotConfiguredResearcher, ResearchQuery


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("research", help="Research a query for supporting sources (model-backed).")
    parser.add_argument("query")
    parser.add_argument("--max-sources", type=int, default=5)
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    NotConfiguredResearcher().research(ResearchQuery(text=args.query, max_sources=args.max_sources))
    return 0
