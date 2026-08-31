"""`howlwriter humanize <file>` -- real model-backed humanization through HowlPlane,
or deterministic analysis and safe-word substitutions when opted in."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.document import Document
from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.report import WritingReport
from howlwriter.humanize.detector import detect
from howlwriter.humanize.rewriter import ModelHumanizerRewriter, SafeRewriter
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD
from howlwriter.review.meaning import (
    MeaningPreservationReviewer,
    RealModelMeaningReviewer,
)


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "humanize",
        help="Humanize AI-style prose via HowlPlane model execution or deterministic analysis.",
    )
    parser.add_argument("path", help="Path to markdown document to humanize.")
    parser.add_argument(
        "--config", dest="project_config_path", default=None,
        help="Path to project configuration YAML/TOML.",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Run in deterministic-only mode without invoking models.",
    )
    parser.add_argument(
        "--safe-only",
        action="store_true",
        help="Alias for --deterministic.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply configured safe-word substitutions in deterministic mode.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write transformed text to this file (default: <path>.humanized.md in model mode).",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    document = Document.parse(text, title=Path(args.path).stem)
    config = ConfigLoader().load(project_config_path=args.project_config_path)

    lint_before = LintEngine().run(document, config)
    findings = detect(document, config)

    # 1. Deterministic-only path
    if args.deterministic or args.safe_only:
        if args.apply:
            config.apply_safe_rewrites = True

        for finding in findings:
            location = (
                "document"
                if finding.paragraph_index is None
                else f"paragraph {finding.paragraph_index}"
            )
            print(f"{finding.rule_code} ({location}): {finding.message}")
        if not findings:
            print("No humanization findings.")

        result = SafeRewriter().rewrite(document, config)
        for change in result.changes:
            print(f"applied: {change.description}")

        if args.out:
            atomic_write_text(args.out, result.document.text)
            print(f"Wrote {args.out}")
        return 0

    # 2. Real model-backed path via HowlPlane
    start_time = time.time()
    print("Running deterministic analysis...")
    print(f"  Detected {len(findings)} humanization patterns, {len(lint_before)} lint matches.")

    # ModelHumanizerRewriter will raise ModelRoleNotConfiguredError if unconfigured
    print("Invoking HUMANIZER role via HowlPlane...")
    humanize_res = ModelHumanizerRewriter().rewrite(
        document, config, cwd=Path(args.path).parent
    )
    transformed_doc = humanize_res.document

    lint_after = LintEngine().run(transformed_doc, config)
    meaning_res = MeaningPreservationReviewer().compare(
        document, transformed_doc
    )

    bridge = get_howlplane_bridge()
    semantic_res = None
    meaning_reviewer_provider = None
    reviewer_independence = "NOT_REVIEWED"

    if bridge.is_role_configured(WritingRole.FINAL_REVIEWER):
        print("Invoking MEANING_REVIEWER role via HowlPlane...")
        semantic_res = RealModelMeaningReviewer().compare(
            document,
            transformed_doc,
            humanizer_provider=humanize_res.provider,
            cwd=Path(args.path).parent,
        )
        meaning_reviewer_provider = semantic_res.provider
        reviewer_independence = semantic_res.independence_status

    banned_word_count = sum(
        1 for m in lint_after if m.rule_code == AI_STYLE_BANNED_WORD
    )
    ai_style_count = len(lint_after) - banned_word_count

    if semantic_res is not None and semantic_res.verdict == "FAIL":
        status = "NEEDS_REVIEW"
    elif (
        meaning_res.status != "PASS"
        or (semantic_res is not None and semantic_res.verdict == "PASS_WITH_WARNINGS")
    ):
        status = "NEEDS_REVIEW"
    else:
        status = "READY"

    report = WritingReport(
        status=status,
        mode=document.mode,
        humanizer_provider=humanize_res.provider,
        meaning_reviewer_provider=meaning_reviewer_provider,
        reviewer_independence=reviewer_independence,
        lint_before_count=len(lint_before),
        lint_after_count=len(lint_after),
        banned_words=banned_word_count,
        ai_style_warnings=ai_style_count,
        meaning_preservation=meaning_res.status,
        semantic_meaning_status=semantic_res.verdict if semantic_res else None,
        humanizer_duration_seconds=humanize_res.duration_seconds,
        meaning_reviewer_duration_seconds=(
            semantic_res.duration_seconds if semantic_res else None
        ),
        total_duration_seconds=round(time.time() - start_time, 2),
        changes=list(humanize_res.changes),
    )

    out_path = (
        Path(args.out)
        if args.out
        else Path(args.path).with_suffix(".humanized.md")
    )
    atomic_write_text(out_path, transformed_doc.text)
    print(f"Wrote {out_path}")
    print()
    print(report.render_text())
    return 0
