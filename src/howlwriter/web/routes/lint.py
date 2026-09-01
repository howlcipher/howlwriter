"""Deterministic style and banned-word linting endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from howlwriter.config.loader import ConfigLoader
from howlwriter.domain.document import Document
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD
from howlwriter.web.models import LintRequest, LintResponse, RuleMatchDto

router = APIRouter(prefix="/api/lint", tags=["lint"])


@router.post("", response_model=LintResponse)
def run_lint(req: LintRequest) -> LintResponse:
    config = ConfigLoader().load(project_config_path=req.config_path)
    document = Document.parse(req.text, title=req.title or "Untitled")

    matches = LintEngine().run(document, config)
    dtos: list[RuleMatchDto] = []
    banned_count = 0

    for m in matches:
        if m.rule_code == AI_STYLE_BANNED_WORD:
            banned_count += 1
        dtos.append(
            RuleMatchDto(
                rule_code=m.rule_code,
                message=m.message,
                matched_text=m.matched_text,
                severity=m.severity,
                paragraph_index=m.paragraph_index,
                sentence_index=m.sentence_index,
                snippet=m.matched_text,
            )
        )

    ai_style_count = len(matches) - banned_count

    return LintResponse(
        matches=dtos,
        banned_words_count=banned_count,
        ai_style_warnings_count=ai_style_count,
        total_count=len(matches),
    )
