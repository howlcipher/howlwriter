"""`howlwriter voice learn <files...>` -- learns a VoiceProfile from a
corpus of the author's own writing using the deterministic corpus-stats
learner (no model call)."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.voice.learner import CorpusStatsLearner


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("voice", help="Voice profile operations.")
    voice_subparsers = parser.add_subparsers(dest="voice_command", required=True)

    learn_parser = voice_subparsers.add_parser(
        "learn", help="Learn a voice profile from a corpus of text files."
    )
    learn_parser.add_argument("paths", nargs="+", help="One or more text files making up the corpus.")
    learn_parser.add_argument("--author", default="", help="Author name to label the profile with.")
    learn_parser.add_argument("--out", default=None, help="Write the learned profile as JSON to this path.")
    learn_parser.set_defaults(handler=run_learn)

    return parser


def run_learn(args: argparse.Namespace) -> int:
    corpus = [Path(p).read_text(encoding="utf-8") for p in args.paths]
    profile = CorpusStatsLearner().learn(corpus, author_name=args.author)
    rendered = profile.to_json()
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
        print(f"Wrote voice profile to {args.out}")
    else:
        print(rendered)
    return 0
