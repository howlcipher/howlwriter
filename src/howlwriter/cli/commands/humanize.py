"""`howlwriter humanize <file>` -- deterministic humanization findings, plus
the one opt-in safe rewrite (banned-word substitution)."""

from __future__ import annotations

import argparse
from pathlib import Path

from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.document import Document
from howlwriter.humanize.detector import detect
from howlwriter.humanize.rewriter import SafeRewriter


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("humanize", help="Detect (and optionally safely rewrite) AI-style prose.")
    parser.add_argument("path")
    parser.add_argument("--config", dest="project_config_path", default=None)
    parser.add_argument("--apply", action="store_true", help="Apply configured safe-word substitutions.")
    parser.add_argument("--out", default=None, help="Write the (possibly rewritten) text here.")
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    document = Document.parse(text, title=Path(args.path).stem)
    config = ConfigLoader().load(project_config_path=args.project_config_path)
    if args.apply:
        config.apply_safe_rewrites = True

    findings = detect(document, config)
    for finding in findings:
        location = "document" if finding.paragraph_index is None else f"paragraph {finding.paragraph_index}"
        print(f"{finding.rule_code} ({location}): {finding.message}")
    if not findings:
        print("No humanization findings.")

    result = SafeRewriter().rewrite(document, config)
    for change in result.changes:
        print(f"applied: {change.description}")

    if args.out:
        Path(args.out).write_text(result.document.text, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0
