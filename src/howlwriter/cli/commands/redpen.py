"""`howlwriter red-pen <file>` (alias: `critique`) -- criticism, not
rewriting. Formats findings as RED_PEN_NNN blocks matching the spec's own
example output."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.domain.document import Document
from howlwriter.facts.extraction import HeuristicClaimExtractor
from howlwriter.redpen.critic import RedPenEngine


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("red-pen", aliases=["critique"], help="Critique a file (no rewriting).")
    parser.add_argument("path")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    document = Document.parse(text, title=Path(args.path).stem)
    claims = HeuristicClaimExtractor().extract(document)
    findings = RedPenEngine().critique(document, claims=claims)

    if not findings:
        print("No red pen findings.")
        return 0

    for finding in findings:
        print(finding.id)
        print(f"Paragraph {finding.paragraph_index}, sentence {finding.sentence_index}")
        print(f'"{finding.quoted_text}"')
        print()
        print(f"Reason:\n{finding.reason}")
        print()
        print(f"Recommendation:\n{finding.recommendation.capitalize()}.")
        print()
    return 0
