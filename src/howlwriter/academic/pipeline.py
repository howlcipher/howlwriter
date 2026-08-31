"""The complete academic paper pipeline:
ASSIGNMENT -> RESEARCH -> DRAFT -> LENGTH CORRECTION -> OUTLINE CHECK ->
VERIFY -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW -> REFERENCES -> REPORT.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from howlwriter.academic.citations import AcademicCitationManager, CitationAnalysis
from howlwriter.academic.length import (
    calculate_word_tolerance,
    count_body_words,
    evaluate_word_count,
)
from howlwriter.academic.outline import OutlineResult, check_outline_conformance
from howlwriter.academic.research import AcademicResearcher
from howlwriter.academic.spec import AssignmentSpec, load_assignment_spec
from howlwriter.academic.verifier import AcademicVerifier, VerificationSummary
from howlwriter.academic.writer import ModelAcademicWriter
from howlwriter.config.defaults import default_config
from howlwriter.config.schema import HowlWriterConfig
from howlwriter.diagnostic.run_record import (
    RunRecord,
    compute_sha256,
    generate_run_id,
)
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.domain.report import WritingReport
from howlwriter.domain.source import Source
from howlwriter.humanize.rewriter import ModelHumanizerRewriter, SafeRewriter
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD, RuleMatch
from howlwriter.redpen.critic import RedPenEngine, RedPenFinding
from howlwriter.review.meaning import (
    MeaningPreservationReviewer,
    RealModelMeaningReviewer,
    SemanticMeaningResult,
)


@dataclass
class AcademicPipelineResult:
    spec: AssignmentSpec
    final_document: Document
    sources: list[Source]
    provenance_graph: ProvenanceGraph
    verification_summary: VerificationSummary
    citation_analysis: CitationAnalysis
    outline_result: OutlineResult
    lint_matches: list[RuleMatch]
    red_pen_findings: list[RedPenFinding]
    semantic_meaning_result: SemanticMeaningResult | None
    report: WritingReport


def run_academic_pipeline(
    assignment: AssignmentSpec | str | Path | dict[str, Any],
    config: HowlWriterConfig | None = None,
    existing_sources: list[Source] | None = None,
    deterministic_only: bool = False,
    custom_backend: Any | None = None,
    run_id: str | None = None,
    cwd: Path | str | None = None,
    max_length_retries: int = 2,
) -> AcademicPipelineResult:
    """Executes the full researched academic paper pipeline."""
    start_time = time.time()
    active_run_id = run_id or generate_run_id()
    cfg = config or default_config()

    spec = (
        assignment
        if isinstance(assignment, AssignmentSpec)
        else load_assignment_spec(assignment)
    )

    bridge = get_howlplane_bridge()
    can_use_models = not deterministic_only and (
        bridge.is_available() or custom_backend is not None
    )

    # 1. RESEARCH & SOURCE COLLECTION
    t_res_start = time.time()
    researcher = AcademicResearcher(existing_sources=existing_sources)
    sources = researcher.execute_research(
        spec,
        max_sources_total=max(spec.source_requirements.minimum_sources + 2, 8),
    )
    researcher_duration = round(time.time() - t_res_start, 2)
    researcher_provider = "scholarly_api" if sources else "none"

    if not sources:
        # If no sources found at all, create an initial fallback source based on topic
        # so the pipeline can proceed honestly with missing-sources status
        sources = [
            Source(
                id="S001",
                title=f"Preliminary Research Notes: {spec.title}",
                authors=["Staff Researcher"],
                publication_date=None,
                retrieved_text=f"Core topic overview: {spec.topic}",
            )
        ]

    # 2. DRAFTING (WRITER ROLE)
    t_writer_start = time.time()
    writer_provider: str | None = None
    writer_stated_claims: list[dict] = []

    if can_use_models:
        writer = ModelAcademicWriter()
        draft_res = writer.draft_paper(
            spec,
            sources,
            config=cfg,
            cwd=cwd,
            custom_backend=custom_backend,
            run_id=active_run_id,
        )
        draft_doc = draft_res.document
        writer_provider = draft_res.provider
        writer_stated_claims = draft_res.claims_stated
    else:
        # Deterministic drafting fallback: structured sections with evidence placeholders
        body_sections: list[str] = [f"# {spec.title}\n"]
        for topic in spec.outline:
            body_sections.append(f"## {topic}\n\nAnalysis and discussion of {topic.lower()}.")
        body_text = "\n\n".join(body_sections)
        draft_doc = Document.parse(body_text, title=spec.title, mode=WritingMode.ACADEMIC)

    writer_duration = round(time.time() - t_writer_start, 2)

    # 3. WORD COUNT & BOUNDED LENGTH CORRECTION
    actual_words = count_body_words(draft_doc.text)
    min_words, max_words = calculate_word_tolerance(
        spec.target_words, spec.word_tolerance_percent
    )
    wc_status, wc_reason = evaluate_word_count(
        actual_words, spec.target_words, spec.word_tolerance_percent
    )

    if can_use_models and wc_status != "PASS" and max_length_retries > 0:
        retries = 0
        while retries < max_length_retries and wc_status != "PASS":
            direction = "EXPAND" if wc_status == "TOO_SHORT" else "TIGHTEN"
            corr_res = ModelAcademicWriter().correct_length(
                draft_doc,
                spec,
                sources,
                direction=direction,
                current_words=actual_words,
                cwd=cwd,
                custom_backend=custom_backend,
                run_id=active_run_id,
            )
            draft_doc = corr_res.document
            actual_words = count_body_words(draft_doc.text)
            wc_status, wc_reason = evaluate_word_count(
                actual_words, spec.target_words, spec.word_tolerance_percent
            )
            retries += 1

    # 4. OUTLINE CONFORMANCE CHECK
    outline_res = check_outline_conformance(draft_doc, spec.outline)

    # 5. CLAIM VERIFICATION & PROVENANCE GRAPH
    verifier = AcademicVerifier()
    provenance_graph, verif_summary = verifier.build_provenance_and_verify(
        draft_doc, sources, stated_claims=writer_stated_claims
    )

    # 6. HUMANIZE (ACADEMIC CONTEXT)
    lint_before = LintEngine().run(draft_doc, cfg)
    humanizer_provider: str | None = None
    humanize_duration: float | None = None

    if can_use_models and bridge.is_role_configured(WritingRole.HUMANIZER):
        humanize_res = ModelHumanizerRewriter().rewrite(
            draft_doc,
            cfg,
            cwd=cwd,
            custom_backend=custom_backend,
            run_id=active_run_id,
        )
        transformed_doc = humanize_res.document
        humanizer_provider = humanize_res.provider
        humanize_duration = humanize_res.duration_seconds
    else:
        safe_res = SafeRewriter().rewrite(draft_doc, cfg)
        transformed_doc = safe_res.document

    # 7. LINT & RED PEN ON TRANSFORMED DOCUMENT
    lint_after = LintEngine().run(transformed_doc, cfg)
    claims_for_redpen = list(provenance_graph.claims.values())
    red_pen_findings = RedPenEngine().critique(transformed_doc, claims=claims_for_redpen)

    # 8. MEANING / SEMANTIC REVIEW
    meaning_det = MeaningPreservationReviewer().compare(draft_doc, transformed_doc)
    semantic_res: SemanticMeaningResult | None = None
    meaning_reviewer_provider: str | None = None
    reviewer_independence: str | None = None
    meaning_review_duration: float | None = None

    if can_use_models and bridge.is_role_configured(WritingRole.FINAL_REVIEWER):
        semantic_res = RealModelMeaningReviewer().compare(
            draft_doc,
            transformed_doc,
            humanizer_provider=humanizer_provider,
            cwd=cwd,
            custom_backend=custom_backend,
            run_id=active_run_id,
        )
        meaning_reviewer_provider = semantic_res.provider
        reviewer_independence = semantic_res.independence_status
        meaning_review_duration = semantic_res.duration_seconds
    elif humanizer_provider is not None:
        reviewer_independence = "NOT_REVIEWED"

    # 9. APA 7 CITATIONS & REFERENCES SECTION ATTACHMENT
    citation_mgr = AcademicCitationManager()
    citation_analysis = citation_mgr.analyze_and_build_references(
        transformed_doc, sources
    )
    final_document = citation_mgr.attach_references(
        transformed_doc, citation_analysis
    )

    # 10. EVALUATE FINAL READINESS STATUS
    # Academic criteria for READY:
    # - Word count in tolerance (wc_status == "PASS")
    # - Outline conformance (outline_res.status == "PASS")
    # - Sources count meets minimum requirement
    # - No unsupported or contradicted factual claims
    # - No ungrounded direct quotations
    # - Semantic review passes (if performed)
    # - No banned words remaining

    banned_word_count = sum(
        1 for m in lint_after if m.rule_code == AI_STYLE_BANNED_WORD
    )
    ai_style_count = len(lint_after) - banned_word_count

    has_source_deficiency = (
        len(citation_analysis.used_sources) < spec.source_requirements.minimum_sources
    )
    has_claim_deficiency = (
        verif_summary.unsupported_claims > 0
        or verif_summary.contradicted_claims > 0
        or bool(verif_summary.quotation_warnings)
    )

    if (
        wc_status != "PASS"
        or outline_res.status != "PASS"
        or has_source_deficiency
        or has_claim_deficiency
        or (semantic_res is not None and semantic_res.verdict == "FAIL")
        or (meaning_det.status != "PASS")
        or (humanizer_provider is not None and banned_word_count > 0)
    ):
        final_status = "NEEDS_REVIEW"
    else:
        final_status = "READY"

    total_duration = round(time.time() - start_time, 2)

    report = WritingReport(
        status=final_status,
        run_id=active_run_id,
        mode="academic",
        writer_provider=writer_provider,
        researcher_provider=researcher_provider,
        humanizer_provider=humanizer_provider,
        meaning_reviewer_provider=meaning_reviewer_provider,
        reviewer_independence=reviewer_independence,
        lint_before_count=len(lint_before),
        lint_after_count=len(lint_after),
        banned_words=banned_word_count,
        ai_style_warnings=ai_style_count,
        meaning_preservation=meaning_det.status,
        semantic_meaning_status=semantic_res.verdict if semantic_res else None,
        target_words=spec.target_words,
        min_words=min_words,
        max_words=max_words,
        actual_body_words=actual_words,
        word_count_status=wc_status,
        required_outline_topics=outline_res.required_topics_count,
        present_outline_topics=outline_res.present_topics_count,
        outline_status=outline_res.status,
        sources_retrieved=len(sources),
        sources_used=len(citation_analysis.used_sources),
        sources_required=spec.source_requirements.minimum_sources,
        supported_claims=verif_summary.supported_claims,
        partially_supported_claims=verif_summary.partially_supported_claims,
        unsupported_claims=verif_summary.unsupported_claims,
        contradicted_claims=verif_summary.contradicted_claims,
        citation_style=spec.citation_style,
        in_text_citations=citation_analysis.in_text_citation_count,
        reference_entries=len(citation_analysis.used_sources) or len(sources),
        citation_warnings=len(citation_analysis.warnings),
        writer_duration_seconds=writer_duration,
        researcher_duration_seconds=researcher_duration,
        humanizer_duration_seconds=humanize_duration,
        meaning_reviewer_duration_seconds=meaning_review_duration,
        total_duration_seconds=total_duration,
        sources=citation_analysis.used_sources or sources,
    )

    # 11. RECORD DOGFOOD DIAGNOSTIC ARTIFACT
    record = RunRecord(
        run_id=active_run_id,
        command="paper",
        writing_mode="academic",
        success=True,
        status=final_status,
        humanizer_provider=humanizer_provider,
        meaning_reviewer_provider=meaning_reviewer_provider,
        reviewer_independence=reviewer_independence,
        lint_before_count=len(lint_before),
        lint_after_count=len(lint_after),
        banned_words=banned_word_count,
        ai_style_warnings=ai_style_count,
        meaning_preservation=meaning_det.status,
        semantic_meaning_status=semantic_res.verdict if semantic_res else None,
        humanizer_duration_seconds=humanize_duration,
        meaning_reviewer_duration_seconds=meaning_review_duration,
        total_duration_seconds=total_duration,
        input_path=str(assignment) if isinstance(assignment, (str, Path)) else None,
        input_chars=len(str(spec.topic)),
        input_sha256=compute_sha256(str(spec.topic)),
        output_chars=len(final_document.text),
        output_sha256=compute_sha256(final_document.text),
        exit_code=0,
    )
    try:
        record.save()
    except Exception:
        pass

    return AcademicPipelineResult(
        spec=spec,
        final_document=final_document,
        sources=sources,
        provenance_graph=provenance_graph,
        verification_summary=verif_summary,
        citation_analysis=citation_analysis,
        outline_result=outline_res,
        lint_matches=lint_after,
        red_pen_findings=red_pen_findings,
        semantic_meaning_result=semantic_res,
        report=report,
    )
