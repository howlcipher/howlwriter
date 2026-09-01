"""Humanizer rewriting and review endpoint."""

from __future__ import annotations

from pathlib import Path
import time
from fastapi import APIRouter

from howlwriter.config.loader import ConfigLoader
from howlwriter.diagnostic.run_record import (
    RunRecord,
    compute_sha256,
    generate_run_id,
)
from howlwriter.domain.document import Document
from howlwriter.humanize.rewriter import ModelHumanizerRewriter, SafeRewriter
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD
from howlwriter.review.meaning import (
    MeaningPreservationReviewer,
    RealModelMeaningReviewer,
)
from howlwriter.web.models import (
    ChangeRecordDto,
    HumanizeRequest,
    HumanizeResponse,
    RuleMatchDto,
)

router = APIRouter(prefix="/api/humanize", tags=["humanize"])


@router.post("", response_model=HumanizeResponse)
def run_humanize(req: HumanizeRequest) -> HumanizeResponse:
    start_time = time.time()
    active_run_id = generate_run_id()
    from howlwriter.domain.modes import parse_mode

    config = ConfigLoader().load(project_config_path=req.config_path, mode=parse_mode(req.mode))

    if req.apply_safe_rewrites:
        config.apply_safe_rewrites = True

    if req.voice_profile:
        config.voice_profile = req.voice_profile

    mode = parse_mode(req.mode)
    document = Document.parse(req.text, title=req.title or "Untitled", mode=mode)
    lint_before = LintEngine().run(document, config)

    bridge = get_howlplane_bridge()
    can_use_model = not req.deterministic_only and bridge.is_role_configured(WritingRole.HUMANIZER)

    changes_dtos: list[ChangeRecordDto] = []
    humanizer_provider: str | None = None
    model_name: str | None = None
    rationale: str = ""
    warnings: list[str] = []
    duration: float = 0.0

    if can_use_model:
        cwd = Path(req.cwd) if req.cwd else Path.cwd()
        res = ModelHumanizerRewriter().rewrite(
            document,
            config,
            cwd=cwd,
            run_id=active_run_id,
        )
        transformed_doc = res.document
        humanizer_provider = res.provider
        model_name = res.model
        rationale = res.rationale
        warnings = res.warnings
        duration = res.duration_seconds
        for c in res.changes:
            changes_dtos.append(
                ChangeRecordDto(
                    description=c.description,
                    reason=c.reason,
                )
            )
    else:
        safe_res = SafeRewriter().rewrite(document, config)
        transformed_doc = safe_res.document
        duration = round(time.time() - start_time, 2)
        for c in safe_res.changes:
            changes_dtos.append(
                ChangeRecordDto(
                    description=c.description,
                    reason=c.reason,
                )
            )

    lint_after = LintEngine().run(transformed_doc, config)
    meaning_res = MeaningPreservationReviewer().compare(document, transformed_doc)

    semantic_res = None
    meaning_reviewer_provider = None
    reviewer_independence = "NOT_REVIEWED"

    if can_use_model and bridge.is_role_configured(WritingRole.FINAL_REVIEWER):
        cwd = Path(req.cwd) if req.cwd else Path.cwd()
        semantic_res = RealModelMeaningReviewer().compare(
            document,
            transformed_doc,
            humanizer_provider=humanizer_provider,
            cwd=cwd,
            run_id=active_run_id,
        )
        meaning_reviewer_provider = semantic_res.provider
        reviewer_independence = semantic_res.independence_status
    elif humanizer_provider is not None:
        reviewer_independence = "NOT_REVIEWED"

    banned_word_count = sum(1 for m in lint_after if m.rule_code == AI_STYLE_BANNED_WORD)
    ai_style_count = len(lint_after) - banned_word_count

    if semantic_res is not None and semantic_res.verdict == "FAIL":
        status = "NEEDS_REVIEW"
    elif (
        meaning_res.status != "PASS"
        or (semantic_res is not None and semantic_res.verdict == "PASS_WITH_WARNINGS")
        or (humanizer_provider is not None and banned_word_count > 0)
    ):
        status = "NEEDS_REVIEW"
    else:
        status = "READY"

    total_duration = round(time.time() - start_time, 2)

    # Record durable dogfood artifact
    record = RunRecord(
        run_id=active_run_id,
        command="humanize",
        writing_mode=str(document.mode.value) if document.mode else "general",
        success=True,
        status=status,
        humanizer_provider=humanizer_provider,
        meaning_reviewer_provider=meaning_reviewer_provider,
        reviewer_independence=reviewer_independence,
        lint_before_count=len(lint_before),
        lint_after_count=len(lint_after),
        banned_words=banned_word_count,
        ai_style_warnings=ai_style_count,
        meaning_preservation=meaning_res.status,
        semantic_meaning_status=semantic_res.verdict if semantic_res else None,
        humanizer_duration_seconds=duration if humanizer_provider else None,
        meaning_reviewer_duration_seconds=semantic_res.duration_seconds if semantic_res else None,
        total_duration_seconds=total_duration,
        input_chars=len(document.text),
        input_sha256=compute_sha256(document.text),
        output_chars=len(transformed_doc.text),
        output_sha256=compute_sha256(transformed_doc.text),
        exit_code=0,
    )
    try:
        record.save()
    except Exception:
        pass

    lint_before_dtos = [
        RuleMatchDto(
            rule_code=m.rule_code,
            message=m.message,
            matched_text=m.matched_text,
            severity=m.severity,
            paragraph_index=m.paragraph_index,
            sentence_index=m.sentence_index,
            snippet=m.matched_text,
        )
        for m in lint_before
    ]
    lint_after_dtos = [
        RuleMatchDto(
            rule_code=m.rule_code,
            message=m.message,
            matched_text=m.matched_text,
            severity=m.severity,
            paragraph_index=m.paragraph_index,
            sentence_index=m.sentence_index,
            snippet=m.matched_text,
        )
        for m in lint_after
    ]

    return HumanizeResponse(
        original_text=document.text,
        transformed_text=transformed_doc.text,
        changes=changes_dtos,
        rationale=rationale,
        warnings=warnings,
        provider=humanizer_provider,
        model=model_name,
        duration_seconds=duration,
        independence_status=reviewer_independence,
        lint_before=lint_before_dtos,
        lint_after=lint_after_dtos,
        lint_before_count=len(lint_before),
        lint_after_count=len(lint_after),
        banned_words_count=banned_word_count,
        ai_style_warnings_count=ai_style_count,
        meaning_preservation_status=meaning_res.status,
        semantic_meaning_status=semantic_res.verdict if semantic_res else None,
        mode=str(document.mode.value) if document.mode else None,
        change_count=len(changes_dtos),
        run_id=active_run_id,
        status=status,
    )
