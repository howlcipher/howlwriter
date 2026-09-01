"""The complete academic paper pipeline:
ASSIGNMENT -> RESEARCH -> DRAFT -> LENGTH CORRECTION -> OUTLINE CHECK ->
COVERAGE CHECK -> VERIFY -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW ->
CONSISTENCY REVIEW -> REFERENCES -> REPORT.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from howlwriter.academic.citations import AcademicCitationManager, CitationAnalysis
from howlwriter.academic.consistency import (
    ConsistencyReviewResult,
    RealModelConsistencyReviewer,
    has_staged_content,
)
from howlwriter.academic.coverage import CoverageResult, check_requirements_coverage
from howlwriter.academic.length import (
    count_body_words,
    evaluate_word_count_bounds,
    resolve_length_bounds,
)
from howlwriter.academic.outline import OutlineResult, check_outline_conformance
from howlwriter.academic.redundancy import RedundancyResult, detect_redundancy
from howlwriter.academic.requirements import (
    apply_identifier_specificity_overrides,
    classify_requirements,
    is_identifier_fabrication_prohibition,
)
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
from howlwriter.domain.source import (
    DEPTH_METADATA_ONLY,
    RELEVANCE_IRRELEVANT,
    Source,
)
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

# A redundancy result is treated as a real deficiency (feeding NEEDS_REVIEW)
# only once it clears one of these thresholds -- a single incidental overlap
# is noise, not a rubric-evidence-restatement problem.
_REDUNDANCY_TABLE_RESTATEMENT_GATE = 1
_REDUNDANCY_NEAR_DUPLICATE_GATE = 2


@dataclass
class AcademicPipelineResult:
    spec: AssignmentSpec
    final_document: Document
    sources: list[Source]
    provenance_graph: ProvenanceGraph
    verification_summary: VerificationSummary
    citation_analysis: CitationAnalysis
    outline_result: OutlineResult
    coverage_result: CoverageResult
    redundancy_result: RedundancyResult
    lint_matches: list[RuleMatch]
    red_pen_findings: list[RedPenFinding]
    semantic_meaning_result: SemanticMeaningResult | None
    consistency_review_result: ConsistencyReviewResult | None
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
    sources = researcher.execute_research(spec)
    researcher_duration = round(time.time() - t_res_start, 2)
    researcher_provider = "scholarly_api" if sources else "none"

    if not sources:
        # If no sources found at all, create an honest fallback marker that is
        # explicitly not eligible for citation. It does not count toward the
        # minimum and cannot be used to support claims.
        sources = [
            Source(
                id="S001",
                title=f"Preliminary Research Notes: {spec.title}",
                authors=["Staff Researcher"],
                publication_date=None,
                retrieved_text=f"Core topic overview: {spec.topic}",
                relevance=RELEVANCE_IRRELEVANT,
                evidence_depth=DEPTH_METADATA_ONLY,
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
    bounds = resolve_length_bounds(spec)
    actual_words = count_body_words(draft_doc.text)
    min_words, max_words = bounds.min_words, bounds.max_words
    wc_status, wc_reason = evaluate_word_count_bounds(
        actual_words,
        bounds.min_words,
        bounds.max_words,
        bounds.target_words,
        hard_max_words=bounds.hard_max_words,
    )

    pre_correction_redundancy = detect_redundancy(draft_doc)

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
                redundancy_hint=(
                    pre_correction_redundancy if direction == "TIGHTEN" else None
                ),
            )
            draft_doc = corr_res.document
            actual_words = count_body_words(draft_doc.text)
            wc_status, wc_reason = evaluate_word_count_bounds(
                actual_words,
                bounds.min_words,
                bounds.max_words,
                bounds.target_words,
                hard_max_words=bounds.hard_max_words,
            )
            retries += 1

    # 4. OUTLINE CONFORMANCE CHECK
    outline_res = check_outline_conformance(draft_doc, spec.outline)

    # 4a. REQUIREMENT CLASSIFICATION & GROUNDING CORPUS (shared by coverage
    # and identifier verification below -- see academic/requirements.py for
    # why positive/prohibition/length/style requirements are routed to
    # different validators instead of all being scored by word overlap).
    grounding_texts = [s.retrieved_text or "" for s in sources]
    grounding_texts.extend([spec.topic, *spec.requirements, *spec.known_identifiers])
    req_buckets = classify_requirements(spec.requirements)

    # 4b. MINIMUM-SUFFICIENT-COVERAGE CHECK (positive requirements only --
    # prohibition/length/style requirements are scored by their own
    # dedicated validators below, not by word overlap).
    coverage_res = check_requirements_coverage(draft_doc, req_buckets.positive)
    coverage_res = apply_identifier_specificity_overrides(
        coverage_res, draft_doc, grounding_texts
    )

    # 4c. REDUNDANCY CHECK (final, post-correction)
    redundancy_res = detect_redundancy(draft_doc)
    has_redundancy_deficiency = (
        sum(1 for f in redundancy_res.findings if f.kind == "table_restatement")
        >= _REDUNDANCY_TABLE_RESTATEMENT_GATE
        or sum(1 for f in redundancy_res.findings if f.kind == "near_duplicate_paragraph")
        >= _REDUNDANCY_NEAR_DUPLICATE_GATE
    )

    # 5. CLAIM VERIFICATION & PROVENANCE GRAPH
    verifier = AcademicVerifier()
    provenance_graph, verif_summary = verifier.build_provenance_and_verify(
        draft_doc,
        sources,
        stated_claims=writer_stated_claims,
        additional_grounding_texts=[spec.topic, *spec.requirements, *spec.known_identifiers],
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

    # 8b. CONSISTENCY REVIEW (sequence/dependency + heading/label + citation fit)
    consistency_res: ConsistencyReviewResult | None = None
    if can_use_models and bridge.is_role_configured(WritingRole.FINAL_REVIEWER):
        consistency_res = RealModelConsistencyReviewer().review(
            transformed_doc,
            sources,
            staged_content_detected=has_staged_content(transformed_doc),
            cwd=cwd,
            custom_backend=custom_backend,
            run_id=active_run_id,
        )

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
    # - Word count within the hard bounds (wc_status in ("PASS", "TARGET_MISS");
    #   TARGET_MISS -- missing only the soft preferred range while staying
    #   under any hard ceiling -- is a quality signal, not a blocking one;
    #   only TOO_SHORT/HARD_LIMIT_FAILURE block readiness. See
    #   academic/length.py's evaluate_word_count_bounds.)
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
        or bool(verif_summary.identifier_warnings)
    )
    has_length_deficiency = wc_status in ("TOO_SHORT", "HARD_LIMIT_FAILURE")

    if (
        has_length_deficiency
        or outline_res.status != "PASS"
        or coverage_res.status != "PASS"
        or has_source_deficiency
        or has_claim_deficiency
        or has_redundancy_deficiency
        or (semantic_res is not None and semantic_res.verdict == "FAIL")
        or (consistency_res is not None and consistency_res.verdict == "FAIL")
        or (meaning_det.status != "PASS")
        or (humanizer_provider is not None and banned_word_count > 0)
    ):
        final_status = "NEEDS_REVIEW"
    else:
        final_status = "READY"

    total_duration = round(time.time() - start_time, 2)

    # 10b. REQUIREMENT-BUCKET OBSERVABILITY (prohibition/length/style) --
    # report-only signals, not additional NEEDS_REVIEW gates: the identifier-
    # fabrication prohibition sub-type already gates readiness above via
    # has_claim_deficiency/identifier_warnings, unchanged.
    identifier_prohibitions = [
        r for r in req_buckets.prohibition if is_identifier_fabrication_prohibition(r)
    ]
    other_prohibitions = [
        r for r in req_buckets.prohibition if r not in identifier_prohibitions
    ]

    prohibition_requirements_count = len(identifier_prohibitions) or None
    prohibition_requirements_passed = (
        (0 if verif_summary.identifier_warnings else len(identifier_prohibitions))
        if identifier_prohibitions
        else None
    )
    other_prohibition_requirements_count = len(other_prohibitions) or None

    length_requirement_items_count = len(req_buckets.length) or None
    length_requirement_items_passed = (
        (len(req_buckets.length) if wc_status in ("PASS", "TARGET_MISS") else 0)
        if req_buckets.length
        else None
    )

    style_requirements_count = len(req_buckets.style) or None
    style_requirements_passed = (
        (0 if has_redundancy_deficiency else len(req_buckets.style))
        if req_buckets.style
        else None
    )

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
        consistency_review_status=consistency_res.verdict if consistency_res else None,
        consistency_findings_count=(
            len(consistency_res.findings) if consistency_res else None
        ),
        target_words=bounds.target_words,
        min_words=min_words,
        max_words=max_words,
        hard_max_words=bounds.hard_max_words,
        target_pages_min=spec.length_constraints.target_page_min,
        target_pages_max=spec.length_constraints.target_page_max,
        max_pages=spec.length_constraints.max_pages,
        actual_body_words=actual_words,
        word_count_status=wc_status,
        required_outline_topics=outline_res.required_topics_count,
        present_outline_topics=outline_res.present_topics_count,
        outline_status=outline_res.status,
        required_criteria_count=coverage_res.required_count,
        present_criteria_count=coverage_res.present_count,
        requirements_coverage_status=coverage_res.status,
        prohibition_requirements_count=prohibition_requirements_count,
        prohibition_requirements_passed=prohibition_requirements_passed,
        other_prohibition_requirements_count=other_prohibition_requirements_count,
        length_requirement_items_count=length_requirement_items_count,
        length_requirement_items_passed=length_requirement_items_passed,
        style_requirements_count=style_requirements_count,
        style_requirements_passed=style_requirements_passed,
        redundancy_findings_count=len(redundancy_res.findings),
        sources_retrieved=len(sources),
        sources_used=len(citation_analysis.used_sources),
        sources_required=spec.source_requirements.minimum_sources,
        supported_claims=verif_summary.supported_claims,
        partially_supported_claims=verif_summary.partially_supported_claims,
        unsupported_claims=verif_summary.unsupported_claims,
        contradicted_claims=verif_summary.contradicted_claims,
        quotation_warnings=len(verif_summary.quotation_warnings),
        identifier_warnings=len(verif_summary.identifier_warnings),
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
        length_hard_ceiling_exceeded=(wc_status == "HARD_LIMIT_FAILURE"),
        requirements_coverage_status=coverage_res.status,
        redundancy_flagged=has_redundancy_deficiency,
        identifier_grounding_flagged=bool(verif_summary.identifier_warnings),
        consistency_review_status=consistency_res.verdict if consistency_res else None,
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
        coverage_result=coverage_res,
        redundancy_result=redundancy_res,
        lint_matches=lint_after,
        red_pen_findings=red_pen_findings,
        semantic_meaning_result=semantic_res,
        consistency_review_result=consistency_res,
        report=report,
    )
