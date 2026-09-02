"""The end-to-end HowlWriter pipeline:
[OUTLINE ->] INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW ->
FINAL REVIEW -> OUTPUT.

Two entry shapes share one chain. Given a file, the pipeline transforms prose
someone already wrote. Given an outline, it first WRITES that prose, then
transforms it exactly as before.

The distinction matters for what "meaning preservation" is measured against.
With a file, the original is the user's draft. With an outline there is no
draft to preserve, so the writer's own output becomes the baseline the
humanizer is held to, matching what the academic pipeline already does. What
the outline guarantees instead -- verbatim retention, required points, ordering
-- is checked separately and deterministically by the coverage report, because
a model asked whether it followed an outline will say yes.

Supports both deterministic execution and real model-backed execution wired
through HowlPlane with independent reviewer guarantees and comprehensive
provenance reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from howlwriter.academic.length import (
    calculate_word_tolerance,
    count_body_words,
    evaluate_word_count_bounds,
)
from howlwriter.config.schema import HowlWriterConfig
from howlwriter.diagnostic.run_record import (
    RunRecord,
    classify_failure,
    compute_sha256,
    generate_run_id,
)
from howlwriter.domain.document import Document
from howlwriter.domain.generation_provenance import (
    LEVEL_SUMMARY,
    GenerationProvenance,
    StageRecord,
    sha256_text,
)
from howlwriter.domain.outline import Outline
from howlwriter.domain.report import ChangeRecord, WritingReport
from howlwriter.editing.editor import PassthroughEditor
from howlwriter.facts.extraction import HeuristicClaimExtractor
from howlwriter.humanize.rewriter import (
    ModelHumanizerRewriter,
    SafeRewriter,
)
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.integration.provenance_capture import ProvenanceRecorder
from howlwriter.linting.engine import LintEngine
from howlwriter.provenance.assemble import (
    build_contribution,
    save_provenance,
    summarize_outline,
)
from howlwriter.outline.claims import review_additions
from howlwriter.outline.coverage import CoverageReport, check_coverage
from howlwriter.outline.writer import OutlineDraftResult, OutlineWriter
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
    #: Present only for outline-guided runs.
    coverage: CoverageReport | None = None
    provenance: GenerationProvenance | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cwd_for(path: str | Path | None) -> Path:
    """Working directory to hand a provider.

    An outline run has no input file, so it falls back to the current
    directory rather than passing None into a provider that expects a path.
    """
    if path is None:
        return Path.cwd()
    candidate = Path(path)
    return candidate.parent if candidate.suffix else candidate


def _draft_from_outline(
    outline: Outline,
    config: HowlWriterConfig,
    mode: Any,
    *,
    run_id: str,
    cwd: str | Path | None,
    custom_backend: Any | None,
    target_words: int | None = None,
    seed: int | None = None,
) -> tuple[OutlineDraftResult, Any]:
    """Run the writer stage, with the voice profile ranked below the outline.

    The voice block is rendered using a per-piece structural realization, so the
    writer and the humanizer look at a consistent plausible realization rather than
    static corpus-wide averages.
    """
    from howlwriter.humanize.rewriter import (
        _load_voice_profile,
        _mode_specific_instructions,
    )
    from howlwriter.voice.application import render_profile
    from howlwriter.voice.realization import derive_structural_realization

    profile = _load_voice_profile(config.voice_profile)
    realization = None
    if profile is not None:
        freedom_val = (
            getattr(outline.assess_freedom(), "freedom", None)
            if hasattr(outline, "assess_freedom")
            else None
        )
        realization = derive_structural_realization(
            profile=profile,
            mode=mode,
            outline=outline,
            target_words=target_words,
            input_text=outline.topic or outline.title or "",
            seed=seed,
            freedom=freedom_val,
        )
    voice_block = (
        render_profile(profile, mode, realization=realization)
        if profile is not None
        else ""
    )
    draft = OutlineWriter().draft(
        outline,
        voice_block=voice_block,
        mode_rules=_mode_specific_instructions(mode),
        run_id=run_id,
        cwd=_cwd_for(cwd),
        custom_backend=custom_backend,
    )
    return draft, realization


def run_howl_pipeline(
    path: str | Path | None,
    config: HowlWriterConfig,
    deterministic_only: bool = False,
    custom_backend: Any | None = None,
    run_id: str | None = None,
    target_words: int | None = None,
    word_tolerance_percent: float = 15.0,
    max_words: int | None = None,
    writing_mode: Any | None = None,
    outline: Outline | None = None,
    provenance_level: str = LEVEL_SUMMARY,
    seed: int | None = None,
) -> PipelineResult:
    from howlwriter.domain.modes import parse_mode

    if path is None and outline is None:
        raise ValueError("run_howl_pipeline needs either a path or an outline")

    start_time = time.time()
    active_run_id = run_id or generate_run_id()
    mode = parse_mode(writing_mode or (outline.mode if outline else None))

    recorder = ProvenanceRecorder(run_id=active_run_id)
    provenance = GenerationProvenance(
        run_id=active_run_id,
        workflow="howl-outline" if outline is not None else "howl",
        writing_mode=mode.value if mode else None,
        provenance_level=provenance_level,
        outline_present=outline is not None,
        voice_profile=config.voice_profile,
    )
    stage_index = 0

    def _stage(name: str, **fields: Any) -> None:
        nonlocal stage_index
        stage_index += 1
        provenance.stages.append(
            StageRecord(name=name, sequence=stage_index, **fields)
        )

    with recorder:
        return _run(
            path=path,
            config=config,
            deterministic_only=deterministic_only,
            custom_backend=custom_backend,
            active_run_id=active_run_id,
            target_words=target_words,
            word_tolerance_percent=word_tolerance_percent,
            max_words=max_words,
            mode=mode,
            outline=outline,
            recorder=recorder,
            provenance=provenance,
            stage=_stage,
            start_time=start_time,
            provenance_level=provenance_level,
            seed=seed,
        )


def _run(
    *,
    path: str | Path | None,
    config: HowlWriterConfig,
    deterministic_only: bool,
    custom_backend: Any | None,
    active_run_id: str,
    target_words: int | None,
    word_tolerance_percent: float,
    max_words: int | None,
    mode: Any,
    outline: Outline | None,
    recorder: ProvenanceRecorder,
    provenance: GenerationProvenance,
    stage: Any,
    start_time: float,
    provenance_level: str = LEVEL_SUMMARY,
    seed: int | None = None,
) -> PipelineResult:
    outline_draft = None
    coverage_report: CoverageReport | None = None
    realization = None

    if outline is not None:
        # WRITE first. There is no prose yet, so nothing downstream of here has
        # anything to work on until the writer returns.
        outline_draft, realization = _draft_from_outline(
            outline, config, mode,
            run_id=active_run_id, cwd=path, custom_backend=custom_backend,
            target_words=target_words, seed=seed,
        )
        text = outline_draft.document.text
        original_document = outline_draft.document
        provenance.generation_freedom = outline_draft.assessment.freedom.value
        provenance.outline_sha256 = sha256_text(outline.to_json())
        provenance.draft_sha256 = sha256_text(text)
        provenance.added_claims = list(outline_draft.added_claims)
        provenance.gaps = list(outline_draft.gaps)
        provenance.warnings.extend(outline_draft.warnings)
        if realization:
            provenance.structural_realization = realization.to_dict()
        stage(
            "outline_writer",
            model_backed=True,
            call_sequences=[c.sequence for c in recorder.calls],
            output_sha256=provenance.draft_sha256,
            duration_seconds=outline_draft.duration_seconds,
            detail=f"freedom={outline_draft.assessment.freedom.value}",
        )
    else:
        text = Path(path).read_text(encoding="utf-8")
        original_document = Document.parse(text, title=Path(path).stem, mode=mode)
        stage("input", input_sha256=sha256_text(text))
        if config.voice_profile:
            from howlwriter.humanize.rewriter import _load_voice_profile
            from howlwriter.voice.realization import derive_structural_realization

            profile = _load_voice_profile(config.voice_profile)
            if profile is not None:
                realization = derive_structural_realization(
                    profile=profile,
                    mode=mode,
                    target_words=target_words or original_document.stats.words,
                    input_text=text,
                    seed=seed,
                    freedom="MINIMAL" if original_document.stats.words > 100 else "HIGH",
                )
                if realization:
                    provenance.structural_realization = realization.to_dict()

    input_sha256 = compute_sha256(text)
    input_chars = len(text)
    provenance.input_sha256 = input_sha256

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
                cwd=_cwd_for(path),
                custom_backend=custom_backend,
                run_id=active_run_id,
                realization=realization,
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
                cwd=_cwd_for(path),
                custom_backend=custom_backend,
                run_id=active_run_id,
            )
            meaning_reviewer_provider = semantic_meaning_result.provider
            reviewer_independence = (
                semantic_meaning_result.independence_status
            )
            provenance.reviewer_independence_by_stage["meaning_review"] = (
                reviewer_independence or "UNKNOWN"
            )
        elif humanizer_provider is not None:
            reviewer_independence = "NO_REVIEWER"
            provenance.reviewer_independence_by_stage["meaning_review"] = "NO_REVIEWER"

        if outline_draft and outline_draft.provider and humanizer_provider:
            provenance.reviewer_independence_by_stage["humanizer_vs_writer"] = (
                "INDEPENDENT_PROVIDER"
                if outline_draft.provider != humanizer_provider
                else "SAME_PROVIDER"
            )

        banned_word_count = sum(
            1 for m in lint_matches if m.rule_code == AI_STYLE_BANNED_WORD
        )
        ai_style_count = len(lint_matches) - banned_word_count

        # Optional length constraint (deliberately no outline/rubric concept
        # for the general howl pipeline this milestone -- see academic/
        # pipeline.py for the full constraint-aware academic pipeline).
        actual_words: int | None = None
        min_words: int | None = None
        resolved_max_words: int | None = None
        wc_status: str | None = None
        if target_words is not None:
            actual_words = count_body_words(final_document.text)
            min_words, soft_max_words = calculate_word_tolerance(
                target_words, word_tolerance_percent
            )
            resolved_max_words = (
                min(soft_max_words, max_words) if max_words is not None else soft_max_words
            )
            wc_status, _ = evaluate_word_count_bounds(
                actual_words, min_words, resolved_max_words, target_words
            )

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
            or (wc_status is not None and wc_status != "PASS")
        ):
            status = "NEEDS_REVIEW"
        else:
            status = "READY"

        total_duration = round(time.time() - start_time, 2)
        report = WritingReport(
            status=status,
            run_id=active_run_id,
            mode=str(original_document.mode.value) if original_document.mode else None,
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
            change_count=len(changes),
            target_words=target_words,
            min_words=min_words,
            max_words=resolved_max_words,
            actual_body_words=actual_words,
            word_count_status=wc_status,
        )

        record = RunRecord(
            run_id=active_run_id,
            command="howl",
            writing_mode=str(original_document.mode.value) if original_document.mode else None,
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
            input_path=str(path) if path else None,
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

        provenance.calls = list(recorder.calls)
        provenance.artifact_sha256 = compute_sha256(final_document.text)
        provenance.humanized_sha256 = provenance.artifact_sha256
        provenance.completed_at = _utc_now()
        provenance.review = {
            "meaning_preservation": meaning_result.status,
            "semantic_meaning": (
                semantic_meaning_result.verdict if semantic_meaning_result else None
            ),
            "reviewer_independence": reviewer_independence,
            "readiness": status,
        }
        if outline is not None:
            # Checked against the FINAL artifact, not the draft: an outline
            # guarantee that survives the writer and dies in the humanizer is
            # not a guarantee.
            coverage_report = check_coverage(outline, final_document.text)
            provenance.coverage = coverage_report.to_dict()
            provenance.outline_summary = summarize_outline(outline)
            claim_review = review_additions(
                provenance.added_claims,
                outline,
                # The general pipeline has no retrieval behind it, so an
                # addition here cannot be checked against evidence. It is
                # surfaced rather than allowed to block, and the academic
                # pipeline -- which does have evidence -- decides differently.
                research_backed=False,
            )
            provenance.review["model_additions"] = claim_review.to_dict()
            provenance.warnings.extend(claim_review.notes)
            provenance.contribution = build_contribution(
                outline,
                coverage=provenance.coverage,
                artifact_text=final_document.text,
                added_claims=provenance.added_claims,
                gaps=provenance.gaps,
                unsupported=len(claim_review.new_factual),
            )
            stage(
                "outline_coverage",
                status=coverage_report.status,
                output_sha256=provenance.artifact_sha256,
                detail=(
                    f"required {coverage_report.required_represented}/"
                    f"{coverage_report.required_supplied}, preserved "
                    f"{coverage_report.preserved_retained}/"
                    f"{coverage_report.preserved_supplied}"
                ),
            )
        provenance.complete = True
        save_provenance(provenance, level=provenance_level)

        return PipelineResult(
            original_document=original_document,
            final_document=final_document,
            lint_matches=lint_matches,
            red_pen_findings=red_pen_findings,
            meaning_result=meaning_result,
            semantic_meaning_result=semantic_meaning_result,
            report=report,
            coverage=coverage_report,
            provenance=provenance,
        )
    except Exception as exc:
        total_duration = round(time.time() - start_time, 2)
        try:
            failure_record = RunRecord(
                run_id=active_run_id,
                command="howl",
                writing_mode=str(original_document.mode.value) if original_document.mode else None,
                success=False,
                status="BLOCKED",
                humanizer_provider=humanizer_provider,
                failure_category=classify_failure(exc),
                error_message=str(exc),
                total_duration_seconds=total_duration,
                input_path=str(path) if path else None,
                input_chars=input_chars,
                input_sha256=input_sha256,
                exit_code=1,
            )
            failure_record.save()
        except Exception:
            pass
        raise
