"""Diagnostic and dogfood run history endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from howlwriter.diagnostic.run_record import RunRecord
from howlwriter.web.models import RunRecordDto

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _record_to_dto(r: RunRecord) -> RunRecordDto:
    return RunRecordDto(
        run_id=r.run_id,
        timestamp=r.timestamp,
        command=r.command,
        writing_mode=r.writing_mode,
        success=r.success,
        status=r.status,
        humanizer_provider=r.humanizer_provider,
        meaning_reviewer_provider=r.meaning_reviewer_provider,
        reviewer_independence=r.reviewer_independence,
        lint_before_count=r.lint_before_count,
        lint_after_count=r.lint_after_count,
        banned_words=r.banned_words,
        ai_style_warnings=r.ai_style_warnings,
        meaning_preservation=r.meaning_preservation,
        semantic_meaning_status=r.semantic_meaning_status,
        humanizer_duration_seconds=r.humanizer_duration_seconds,
        meaning_reviewer_duration_seconds=r.meaning_reviewer_duration_seconds,
        total_duration_seconds=r.total_duration_seconds,
        input_path=r.input_path,
        input_chars=r.input_chars,
        input_sha256=r.input_sha256,
        output_chars=r.output_chars,
        output_sha256=r.output_sha256,
        failure_category=r.failure_category,
        error_message=r.error_message,
        exit_code=r.exit_code,
        howlplane_task_ids=r.howlplane_task_ids,
        metadata=r.metadata,
    )


@router.get("", response_model=list[RunRecordDto])
def list_runs(limit: int = Query(default=30, ge=1, le=200)) -> list[RunRecordDto]:
    records = RunRecord.list_records(limit=limit)
    return [_record_to_dto(r) for r in records]


@router.get("/{run_id}", response_model=RunRecordDto)
def get_run(run_id: str) -> RunRecordDto:
    record = RunRecord.load(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run record not found: {run_id}")
    return _record_to_dto(record)
