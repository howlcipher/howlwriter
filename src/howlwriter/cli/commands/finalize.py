"""`howlwriter finalize <original> <revised>` -- runs the meaning
preservation check standalone, outside the full `howl` pipeline, for
comparing an already-produced rewrite against its source.

With --changes it also accounts for each change: what changed, the checkable
reason, whether meaning held and whether a citation moved. A revision that
changed nothing says so."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from howlwriter.domain.document import Document
from howlwriter.review.change_report import build_change_report
from howlwriter.review.meaning import MeaningPreservationReviewer


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("finalize", help="Check meaning preservation between two files.")
    parser.add_argument("original_path")
    parser.add_argument("revised_path")
    parser.add_argument("--changes", action="store_true",
                        help="Also report each change, its reason, citation effect and meaning check.")
    parser.add_argument("--min-words", type=int, default=None)
    parser.add_argument("--max-words", type=int, default=None)
    parser.add_argument("--identity", default=None, help="With --changes: report the voice effect for this identity.")
    parser.add_argument("--mode", default=None, help="Writing mode used for the voice effect (default: academic).")
    parser.add_argument("--json", dest="output_json", action="store_true", help="Machine-readable --changes report.")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    original_text = Path(args.original_path).read_text(encoding="utf-8")
    revised_text = Path(args.revised_path).read_text(encoding="utf-8")
    if args.changes:
        report = build_change_report(original_text, revised_text, min_words=args.min_words,
                                     max_words=args.max_words, identity=args.identity, mode=args.mode)
        if args.output_json:
            print(json.dumps(report.to_dict(), indent=2, default=str))
            return 0
        print(f"MEANING PRESERVATION: {report.meaning_status}")
        print(report.summary)
        for i, c in enumerate(report.changes, 1):
            print(f"{i}. {c.kind}: {'; '.join(c.reasons)} | meaning {c.meaning} | citations: {c.citation_effect}")
            if c.before:
                print(f"     - {c.before[:140]}")
            if c.after:
                print(f"     + {c.after[:140]}")
        for line in report.requirements:
            print(f"requirement: {line}")
        for cc in report.citation_changes:
            print(f"citation [{cc.severity}] {cc.code}: {cc.message}")
        print(f"voice: {report.voice.get('status')}"
              + (f" ({report.voice.get('effect') or report.voice.get('reason', '')})" if report.voice.get("status") != "NOT_REQUESTED" else ""))
        return 0

    original = Document.parse(original_text, title="original")
    revised = Document.parse(revised_text, title="revised")
    result = MeaningPreservationReviewer().compare(original, revised)

    print(f"MEANING PRESERVATION: {result.status}")
    for diff in result.diffs:
        print(f"- [{diff.kind}] {diff.description}")
    return 0
