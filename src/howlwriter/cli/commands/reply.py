"""`howlwriter reply check <reply> --post FILE` -- check a reply against the post it answers.

Source posts are untrusted reference data: they are scanned for embedded
instructions and never executed. With no --post the reply is reported UNGROUNDED,
because what it attributes to the other person cannot be checked. Exit 0 only
when the reply is GROUNDED; 3 otherwise ("finished but not ready").
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from howlwriter.replies.grounding import GroundingState, SourcePost, check_reply

EXIT_NOT_GROUNDED = 3


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("reply", help="Check a reply against the post it answers.")
    actions = parser.add_subparsers(dest="reply_command", required=True)
    check = actions.add_parser("check", help="Verify what a reply attributes to the post it answers.")
    check.add_argument("reply_path", help="Path to the reply (Markdown or text).")
    check.add_argument("--post", action="append", default=[], metavar="[AUTHOR=]PATH",
                       help="Post being answered, optionally prefixed with its author. May repeat.")
    check.add_argument("--min-words", type=int, default=None)
    check.add_argument("--max-words", type=int, default=None)
    check.add_argument("--sources-text", default=None, metavar="FILE",
                       help="Text of cited sources, so quotations from them are not reported as invented.")
    check.add_argument("--genre", default="academic_peer_reply")
    check.add_argument("--json", dest="output_json", action="store_true", help="Machine-readable report.")
    check.set_defaults(handler=run_check)
    return parser


def run_check(args: argparse.Namespace) -> int:
    try:
        reply = Path(args.reply_path).read_text(encoding="utf-8")
        posts = []
        for raw in args.post:
            author, sep, path = raw.partition("=")
            if not sep:
                author, path = "", raw
            posts.append(SourcePost(text=Path(path).read_text(encoding="utf-8"), author=author.strip(),
                                    label=Path(path).name))
        extra = Path(args.sources_text).read_text(encoding="utf-8") if args.sources_text else ""
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = check_reply(reply, posts, min_words=args.min_words, max_words=args.max_words,
                         extra_quotable_text=extra, genre=args.genre)
    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(f"{report.state.value}  ({report.word_count} words)")
        for a in report.attributions:
            print(f"  attribution {a.status} {a.coverage:.0%}: {a.attributed_clause[:100]}")
        for f in report.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if report.state is GroundingState.GROUNDED else EXIT_NOT_GROUNDED
