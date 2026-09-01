"""Full Howl pipeline execution endpoint."""

from __future__ import annotations

from pathlib import Path
import tempfile
from fastapi import APIRouter

from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.modes import parse_mode
from howlwriter.pipeline.howl import run_howl_pipeline
from howlwriter.web.models import (
    HowlPipelineRequest,
    HowlPipelineResponse,
    RedPenFindingDto,
    RuleMatchDto,
)

router = APIRouter(prefix="/api/howl", tags=["howl"])


@router.post("", response_model=HowlPipelineResponse)
def execute_howl_pipeline(req: HowlPipelineRequest) -> HowlPipelineResponse:
    config = ConfigLoader().load(
        project_config_path=req.config_path, mode=parse_mode(req.mode)
    )
    if req.voice_profile:
        config.voice_profile = req.voice_profile

    # Write to a temporary file to leverage run_howl_pipeline's atomic file behavior
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(req.text)
        temp_path = tf.name

    try:
        res = run_howl_pipeline(
            path=temp_path,
            config=config,
            deterministic_only=req.deterministic_only,
            writing_mode=parse_mode(req.mode),
        )
    finally:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except Exception:
            pass

    lint_dtos = [
        RuleMatchDto(
            rule_code=m.rule_code,
            message=m.message,
            matched_text=m.matched_text,
            severity=m.severity,
            paragraph_index=m.paragraph_index,
            sentence_index=m.sentence_index,
            snippet=m.matched_text,
        )
        for m in res.lint_matches
    ]

    redpen_dtos = [
        RedPenFindingDto(
            finding=f.finding,
            reason=f.reason,
            recommendation=f.recommendation,
            category=f.category,
            severity=f.severity,
            location=f.location,
            snippet=f.snippet,
        )
        for f in res.red_pen_findings
    ]

    return HowlPipelineResponse(
        original_text=res.original_document.text,
        final_text=res.final_document.text,
        lint_matches=lint_dtos,
        red_pen_findings=redpen_dtos,
        meaning_preservation=res.meaning_result.status,
        semantic_meaning_status=res.semantic_meaning_result.verdict if res.semantic_meaning_result else None,
        status=res.report.status,
        run_id=res.report.run_id or "hw-unknown",
        report=res.report.to_dict(),
    )
