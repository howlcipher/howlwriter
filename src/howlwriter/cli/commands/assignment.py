"""`howlwriter assignment check <package.yaml>` -- readiness of a whole submission package.

Evaluates every deliverable against one specification (length, topics, genre,
leaked workflow text, citations, source-grounding of replies, meaning
preservation) and reports one state. Exit 0 only for READY_FOR_HUMAN_REVIEW; 3
otherwise. A successful export of a document is not evidence of any of this.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from howlwriter.assignment.package import PackageState, check_package, load_package_spec
from howlwriter.citations.verification import CrossrefProvider, RecordFileProvider

EXIT_NOT_READY = 3


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("assignment", help="Check a multi-document assignment package.")
    actions = parser.add_subparsers(dest="assignment_command", required=True)
    check = actions.add_parser("check", help="Evaluate every deliverable in a package spec together.")
    check.add_argument("package_path", help="Path to the package YAML.")
    check.add_argument("--records", action="append", default=[], metavar="FILE",
                       help="Canonical records (publisher pages, document covers). May repeat.")
    check.add_argument("--offline", action="store_true", help="Do not contact Crossref.")
    check.add_argument("--json", dest="output_json", action="store_true", help="Machine-readable report.")
    check.set_defaults(handler=run_check)
    return parser


def run_check(args: argparse.Namespace) -> int:
    try:
        spec = load_package_spec(args.package_path)
        providers = [RecordFileProvider(p, name=Path(p).name) for p in args.records]
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.offline:
        providers.append(CrossrefProvider())
    try:
        report = check_package(spec, providers=providers)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(f"{report.title}: {report.state.value}")
        for d in report.deliverables:
            print(f"  {d.id:<16} {d.state.value:<24} {d.word_count if d.word_count is not None else '-':>5} words")
            for f in d.findings:
                print(f"      [{f.level}] {f.code}: {f.message}")
        for f in report.package_findings:
            print(f"  [{f.level}] {f.code}: {f.message}")
        for item in report.unavailable_checks:
            print(f"  unavailable: {item}")
        for item in report.human_decisions:
            print(f"  human decision: {item}")
    return 0 if report.state is PackageState.READY_FOR_HUMAN_REVIEW else EXIT_NOT_READY
