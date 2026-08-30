"""`howlwriter lint <file>` -- deterministic style lint findings only. No
business logic lives here; this just parses args, calls the engine, and
renders the result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.document import Document
from howlwriter.linting.engine import LintEngine


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("lint", help="Run the deterministic style linter on a file.")
    parser.add_argument("path", help="Path to a text or Markdown file.")
    parser.add_argument(
        "--config", dest="project_config_path", default=None, help="Project config YAML path."
    )
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    document = Document.parse(text, title=Path(args.path).stem)
    config = ConfigLoader().load(project_config_path=args.project_config_path)
    matches = LintEngine().run(document, config)

    if args.json:
        print(json.dumps([m.to_dict() for m in matches], indent=2))
        return 0

    if not matches:
        print("No findings.")
        return 0

    for match in matches:
        location = "document" if match.paragraph_index is None else f"paragraph {match.paragraph_index}"
        if match.sentence_index is not None:
            location += f", sentence {match.sentence_index}"
        print(f"{match.rule_code} ({location}): {match.message}")
    return 0
