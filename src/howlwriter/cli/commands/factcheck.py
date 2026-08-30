"""`howlwriter fact-check <file>` -- real, deterministic claim extraction
by default (every claim starts UNVERIFIABLE). --verify additionally
attempts real verification, which is unconfigured for the MVP and
surfaces a clean ModelRoleNotConfiguredError rather than a traceback."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.domain.document import Document
from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.facts.extraction import HeuristicClaimExtractor
from howlwriter.facts.verification import NotConfiguredClaimVerifier


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("fact-check", help="Extract factual claims from a file.")
    parser.add_argument("path")
    parser.add_argument("--verify", action="store_true", help="Attempt verification (model-backed).")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    document = Document.parse(text, title=Path(args.path).stem)
    claims = HeuristicClaimExtractor().extract(document)

    if not claims:
        print("No candidate claims found.")
    for claim in claims:
        print(f"[{claim.verification_status.value}] ({claim.claim_type.value}) {claim.text}")
        print(f"    {claim.notes}")

    if args.verify and claims:
        verifier = NotConfiguredClaimVerifier()
        provenance = ProvenanceGraph()
        for claim in claims:
            provenance.add_claim(claim)
        verifier.verify(claims[0], provenance)
    return 0
