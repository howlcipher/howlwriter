"""`howlwriter citations verify <sources.json>` -- check citation metadata against authoritative records.

A resolving DOI does not show that the author, year and edition in a formatted
citation are right. This compares them with canonical records: Crossref (unless
--offline) and any publisher records supplied with --records. Exit 0 only when
every citation is VERIFIED; 3 otherwise ("finished but not ready"). A provider
that cannot be reached yields UNVERIFIABLE, never a claim the citation is wrong.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from howlwriter.citations.verification import (
    CitationState,
    CrossrefProvider,
    RecordFileProvider,
    verify_sources,
    worst_state,
)
from howlwriter.domain.source import source_from_dict
from howlwriter.research.integrity import SourceIntegrityVerifier

EXIT_NOT_VERIFIED = 3


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("citations", help="Verify citation metadata against authoritative records.")
    actions = parser.add_subparsers(dest="citations_command", required=True)
    verify = actions.add_parser(
        "verify", help="Compare each source's author, year, edition and title with canonical records.")
    verify.add_argument("sources_path", help="Path to a sources.json file.")
    verify.add_argument(
        "--records", action="append", default=[], metavar="FILE",
        help="JSON file of canonical records (publisher pages, document covers). May repeat.")
    verify.add_argument("--offline", action="store_true", help="Do not contact Crossref; use --records only.")
    verify.add_argument("--check-links", action="store_true",
                        help="Also probe each DOI and URL with the SSRF-safe source integrity verifier.")
    verify.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout in seconds.")
    verify.add_argument("--json", dest="output_json", action="store_true", help="Machine-readable report.")
    verify.set_defaults(handler=run_verify)
    return parser


def run_verify(args: argparse.Namespace) -> int:
    try:
        raw = json.loads(Path(args.sources_path).read_text(encoding="utf-8"))
        entries = raw["sources"] if isinstance(raw, dict) else raw
        sources = [source_from_dict(e) for e in entries]
        providers: list = [RecordFileProvider(path, name=Path(path).name) for path in args.records]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not sources:
        print("error: the sources file lists no sources, so there is nothing to verify", file=sys.stderr)
        return 1
    integrity = SourceIntegrityVerifier(timeout_seconds=args.timeout)
    if not args.offline:
        providers.append(CrossrefProvider(integrity))

    results = verify_sources(sources, providers)
    overall = worst_state(results)
    links = {}
    if args.check_links:
        for source in sources:
            finding = integrity.verify_source(source)
            links[source.id] = {"access": finding.access_status, "http_status": finding.http_status,
                                "severity": finding.severity}

    if args.output_json:
        payload = {"overall": overall.value, "citations": [r.to_summary() for r in results]}
        if links:
            for item in payload["citations"]:
                item["link"] = links.get(item["source_id"])
        print(json.dumps(payload, indent=2))
    else:
        for result in results:
            print(f"{result.state.value:<13} {result.source_id}  {result.title[:70]}")
            for f in result.findings:
                print(f"    [{f.severity}] {f.code}: {f.message}")
            if result.source_id in links:
                link = links[result.source_id]
                print(f"    link: {link['access']} (HTTP {link['http_status'] or 'N/A'})")
        print(f"\nOVERALL: {overall.value}")
    return 0 if overall == CitationState.VERIFIED else EXIT_NOT_VERIFIED
