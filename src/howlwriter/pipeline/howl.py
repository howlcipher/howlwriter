"""The end-to-end HowlWriter pipeline:
INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW -> FINAL REVIEW -> OUTPUT.

Supports both deterministic execution and real model-backed execution wired
through HowlPlane with independent reviewer guarantees and comprehensive
provenance reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.diagnostic.run_record import (
    RunRecord,
    classify_failure,
    compute_sha256,
    generate_run_id,
)
from howlwriter.domain.document import Document
from howlwriter.domain.report import ChangeRecord, WritingReport
from howlwriter.editing.editor import PassthroughEditor
from howlwriter.facts.extraction import HeuristicClaimExtractor
from howlwriter.humanize.rewriter import (
    ModelHumanizerRewriter,
    SafeRewriter,
)
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD, RuleMatch
from howlwriter.redpen.critic import RedPenEngine, RedPenFinding
from howlwriter.review.meaning import (
    MeaningPreservationResult,
    MeaningPreservationReviewer,
    RealModelMeaningReviewer,
    SemanticMeaningResult,
)


@dataclass
class PipelineResult:
    original_document: Document
    final_document: Document
    lint_matches: list[RuleMatch]
    red_pen_findings: list[RedPenFinding]
    meaning_result: MeaningPreservationResult
    semantic_meaning_result: SemanticMeaningResult | None
    report: WritingReport


def run_howl_pipeline(
    path: str | Path,
    config: HowlWriterConfig,
    deterministic_only: bool = False,
    custom_backend: Any | None = None,
    run_id: str | None = None,
) -> PipelineResult:
    start_time = time.time()
    active_run_id = run_id or generate_run_id()
    text = Path(path).read_text(encoding="utf-8")
    original_document = Document.parse(text, title=Path(path).stem)
    input_sha256 = compute_sha256(text)
    input_chars = len(text)

    # Deterministic lint before transformation for observability report
    lint_before = LintEngine().run(original_document, config)

    # 1. EDIT: deterministic whitespace/heading normalization
    edited_document = PassthroughEditor().edit(original_document)

    # 2. HUMANIZE: Real model-backed Humanizer via HowlPlane when configured,
    # or safe deterministic substitutions when configured/requested.
    bridge = get_howlplane_bridge()
    can_use_model = (
        not deterministic_only
        and (
            bridge.is_role_configured(WritingRole.HUMANIZER)
            or custom_backend is not None
        )
    )

    changes: list[ChangeRecord] = []
    humanizer_provider: str | None = None

    try:
        if can_use_model:
            humanize_res = ModelHumanizerRewriter().rewrite(
                edited_document,
                config,
                cwd=Path(path).parent,
                custom_backend=custom_backend,
                run_id=active_run_id,
            )
            final_document = humanize_res.document
            changes.extend(humanize_res.changes)
            humanizer_provider = humanize_res.provider
        else:
            safe_rewrite = SafeRewriter().rewrite(edited_document, config)
            final_document = safe_rewrite.document
            changes.extend(safe_rewrite.changes)

        # 3. LINT: deterministic style rule check on transformed document
        lint_matches = LintEngine().run(final_document, config)

        # 4. RED PEN: deterministic critique, cross-referencing extracted claims
        claims = HeuristicClaimExtractor().extract(final_document)
        red_pen_findings = RedPenEngine().critique(final_document, claims=claims)

        # 5. MEANING REVIEW (Deterministic)
        meaning_result = MeaningPreservationReviewer().compare(
            original_document, final_document
        )

        # 6. MEANING REVIEW (Semantic Model Review via HowlPlane)
        can_use_meaning_reviewer = (
            not deterministic_only
            and (
                bridge.is_role_configured(WritingRole.FINAL_REVIEWER)
                or custom_backend is not None
            )
        )

        semantic_meaning_result: SemanticMeaningResult | None = None
        meaning_reviewer_provider: str | None = None
        reviewer_independence: str | None = None

        if can_use_meaning_reviewer:
            semantic_meaning_result = RealModelMeaningReviewer().compare(
                original_document,
                final_document,
                humanizer_provider=humanizer_provider,
                cwd=Path(path).parent,
                custom_backend=custom_backend,
                run_id=active_run_id,
            )
            meaning_reviewer_provider = semantic_meaning_result.provider
            reviewer_independence = (
                semantic_meaning_result.independence_status
            )
        elif humanizer_provider is not None:
            reviewer_independence = "NOT_REVIEWED"

        banned_word_count = sum(
            1 for m in lint_matches if m.rule_code == AI_STYLE_BANNED_WORD
        )
        ai_style_count = len(lint_matches) - banned_word_count

        # Determine final readiness status
        if (
            semantic_meaning_result is not None
            and semantic_meaning_result.verdict == "FAIL"
        ):
            status = "NEEDS_REVIEW"
        elif (
            meaning_result.status != "PASS"
            or (
                semantic_meaning_result is not None
                and semantic_meaning_result.verdict == "PASS_WITH_WARNINGS"
            )
            or (humanizer_provider is not None and banned_word_count > 0)
        ):
            status = "NEEDS_REVIEW"
        else:
            status = "READY"

        total_duration = round(time.time() - start_time, 2)
        report = WritingReport(
            status=status,
            run_id=active_run_id,
            mode=str(original_document.mode) if original_document.mode else None,
            humanizer_provider=humanizer_provider,
            meaning_reviewer_provider=meaning_reviewer_provider,
            reviewer_independence=reviewer_independence,
            lint_before_count=len(lint_before),
            lint_after_count=len(lint_matches),
            banned_words=banned_word_count,
            ai_style_warnings=ai_style_count,
            meaning_preservation=meaning_result.status,
            semantic_meaning_status=(
                semantic_meaning_result.verdict
                if semantic_meaning_result
                else None
            ),
            humanizer_duration_seconds=(
                humanize_res.duration_seconds
                if "humanize_res" in locals()
                else None
            ),
            meaning_reviewer_duration_seconds=(
                semantic_meaning_result.duration_seconds
                if semantic_meaning_result
                else None
            ),
            total_duration_seconds=total_duration,
            changes=changes,
        )

        record = RunRecord(
            run_id=active_run_id,
            command="howl",
            writing_mode=str(original_document.mode) if original_document.mode else None,
            success=True,
            status=status,
            humanizer_provider=humanizer_provider,
            humanizer_model=(
                humanize_res.model if "humanize_res" in locals() else None
            ),
            meaning_reviewer_provider=meaning_reviewer_provider,
            meaning_reviewer_model=(
                semantic_meaning_result.model
                if semantic_meaning_result
                else None
            ),
            reviewer_independence=reviewer_independence,
            lint_before_count=len(lint_before),
            lint_after_count=len(lint_matches),
            banned_words=banned_word_count,
            ai_style_warnings=ai_style_count,
            meaning_preservation=meaning_result.status,
            semantic_meaning_status=(
                semantic_meaning_result.verdict
                if semantic_meaning_result
                else None
            ),
            changes_count=len(changes),
            humanizer_duration_seconds=(
                humanize_res.duration_seconds
                if "humanize_res" in locals()
                else None
            ),
            meaning_reviewer_duration_seconds=(
                semantic_meaning_result.duration_seconds
                if semantic_meaning_result
                else None
            ),
            total_duration_seconds=total_duration,
            input_path=str(path),
            input_chars=input_chars,
            input_sha256=input_sha256,
            output_chars=len(final_document.text),
            output_sha256=compute_sha256(final_document.text),
            exit_code=0,
        )
        try:
            record.save()
        except Exception:
            pass

        return PipelineResult(
            original_document=original_document,
            final_document=final_document,
            lint_matches=lint_matches,
            red_pen_findings=red_pen_findings,
            meaning_result=meaning_result,
            semantic_meaning_result=semantic_meaning_result,
            report=report,
        )
    except Exception as exc:
        total_duration = round(time.time() - start_time, 2)
        try:
            failure_record = RunRecord(
                run_id=active_run_id,
                command="howl",
                writing_mode=str(original_document.mode) if original_document.mode else None,
                success=False,
                status="BLOCKED",
                humanizer_provider=humanizer_provider,
                failure_category=classify_failure(exc),
                error_message=str(exc),
                total_duration_seconds=total_duration,
                input_path=str(path),
                input_chars=input_chars,
                input_sha256=input_sha256,
                exit_code=1,
            )
            failure_record.save()
        except Exception:
            pass
        raise
