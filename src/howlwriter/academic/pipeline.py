"""The complete academic paper pipeline:
ASSIGNMENT -> RESEARCH -> DRAFT -> LENGTH CORRECTION -> OUTLINE CHECK ->
COVERAGE CHECK -> VERIFY -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW ->
CONSISTENCY REVIEW -> REFERENCES -> REPORT.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from typing import Any, Callable

from howlwriter.academic.citations import AcademicCitationManager, CitationAnalysis
from howlwriter.academic.consistency import (
    ConsistencyReviewResult,
    RealModelConsistencyReviewer,
    has_staged_content,
)
from howlwriter.academic.detection_coverage import evaluate_technique_detection_coverage
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
from howlwriter.academic.ai_disclosure import build_ai_use_statement
from howlwriter.academic.spec import AssignmentSpec, load_assignment_spec
from howlwriter.domain.generation_provenance import (
    GenerationProvenance,
    normalize_reviewer_independence,
    sha256_text as prov_sha256,
)
from howlwriter.integration.provenance_capture import ProvenanceRecorder
from howlwriter.outline.claims import (
    CONNECTIVE_PROSE,
    LOGICAL_EXPANSION,
    classify_addition,
    review_additions,
)
from howlwriter.outline.coverage import (
    check_coverage,
    paragraph_structure_changed,
    preserved_violations,
)
from howlwriter.provenance.assemble import (
    build_contribution,
    save_provenance,
    summarize_outline,
)
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


def _normalize_claim_entries(entries: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize a provider claim list without changing its semantics."""
    normalized: list[dict[str, Any]] = []
    for entry in entries or []:
        if isinstance(entry, dict):
            claim = str(entry.get("claim") or entry.get("claim_text") or "").strip()
            if not claim:
                continue
            source_id = str(entry.get("source_id") or "").strip()
            snippet = str(entry.get("evidence_snippet") or "").strip()
            default_basis = (
                f"retrieved source {source_id}" if source_id else "model inference"
            )
            normalized.append(
                {
                    "claim": claim,
                    "source_id": source_id,
                    "evidence_snippet": snippet,
                    "basis": str(entry.get("basis") or default_basis).strip(),
                }
            )
        elif isinstance(entry, str) and entry.strip():
            normalized.append({"claim": entry.strip(), "basis": "model inference"})
    return normalized


def _model_added_claims(
    claims_made: list[dict[str, Any]],
    claimed_additions: list[dict[str, Any]],
    outline: Any | None,
) -> list[dict[str, Any]]:
    """Conservatively separate all claims from model-introduced claims.

    The provider's explicit added-claims list is useful evidence but not
    trusted as the sole authority: omitted additions are recovered from
    claims-made, while claims traceable to an authorship outline are not
    relabelled as model contributions.
    """
    combined: dict[str, dict[str, Any]] = {}
    for entry in [*claims_made, *claimed_additions]:
        combined.setdefault(entry["claim"], entry)

    if outline is None:
        return list(combined.values())

    additions: list[dict[str, Any]] = []
    for entry in combined.values():
        classification = classify_addition(entry["claim"], outline).classification
        if classification not in (LOGICAL_EXPANSION, CONNECTIVE_PROSE):
            additions.append(entry)
    return additions


def _record_preserve_rejection(
    provenance: GenerationProvenance,
    *,
    stage: str,
    violations: list[Any],
) -> None:
    ids = [finding.node_id for finding in violations]
    event = {
        "stage": stage,
        "action": "REJECTED_CANDIDATE_AND_RETAINED_PRIOR_ARTIFACT",
        "preserved_ids": ids,
    }
    provenance.review.setdefault("preserve_guard", []).append(event)
    provenance.warnings.append(
        f"{stage} output was rejected because it altered or removed preserved "
        f"passage(s): {', '.join(ids)}. The prior artifact was retained."
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
    coverage_result: CoverageResult
    redundancy_result: RedundancyResult
    lint_matches: list[RuleMatch]
    red_pen_findings: list[RedPenFinding]
    semantic_meaning_result: SemanticMeaningResult | None
    consistency_review_result: ConsistencyReviewResult | None
    report: WritingReport
    #: Present only when an authorship outline drove the run.
    authorship_coverage: Any | None = None
    provenance: Any | None = None
    ai_use_statement: Any | None = None


def run_academic_pipeline(
    assignment: AssignmentSpec | str | Path | dict[str, Any] | None,
    *args: Any,
    **kwargs: Any,
) -> AcademicPipelineResult:
    """Public entry point. Guarantees the provenance recorder is released.

    The recorder is activated inside the pipeline body rather than around it,
    because the spec has to be resolved before the record can describe the run.
    That leaves an exception path where the ContextVar would stay set and the
    next run's model calls would be recorded against this one, so the reset is
    made unconditional here. The signature stays fully positional-compatible:
    every existing caller passes config and the rest positionally.
    """
    from howlwriter.integration.provenance_capture import reset_recorder

    try:
        return _run_academic_pipeline(assignment, *args, **kwargs)
    finally:
        reset_recorder()


def _run_academic_pipeline(
    assignment: AssignmentSpec | str | Path | dict[str, Any] | None,
    config: HowlWriterConfig | None = None,
    existing_sources: list[Source] | None = None,
    deterministic_only: bool = False,
    custom_backend: Any | None = None,
    run_id: str | None = None,
    cwd: Path | str | None = None,
    max_length_retries: int = 2,
    stage_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
    outline: Any | None = None,
    seed: int | None = None,
) -> AcademicPipelineResult:
    """Executes the full researched academic paper pipeline.

    An authorship outline, when supplied, is translated into the assignment
    spec rather than routed around it, so source relevance and sufficiency,
    evidence depth, identifier grounding, claim verification, APA formatting,
    requirement classification, the soft target against the hard ceiling,
    redundancy, consistency and quotation validation all still run. What the
    outline adds -- verbatim retention, ordering, claim-to-source assignment --
    is checked afterwards on the finished document.
    """
    start_time = time.time()
    active_run_id = run_id or generate_run_id()
    cfg = config or default_config()

    def _notify(stage_id: str, status: str, label: str, data: dict[str, Any] | None = None) -> None:
        """Report pipeline progress to an optional observer (the local web job
        manager). Never allowed to affect the pipeline: a misbehaving observer
        is swallowed, not propagated."""
        if stage_callback is not None:
            try:
                payload: dict[str, Any] = {"label": label}
                if data:
                    payload.update(data)
                stage_callback(stage_id, status, payload)
            except Exception:
                pass

    if assignment is None and outline is None:
        raise ValueError(
            "run_academic_pipeline needs either an assignment spec or an outline"
        )
    if assignment is None:
        # An outline carries the title, topic, length and requirements, so it
        # can stand alone. The bridge below fills the spec from it.
        spec = AssignmentSpec()
    elif isinstance(assignment, AssignmentSpec):
        spec = assignment
    else:
        spec = load_assignment_spec(assignment)

    recorder = ProvenanceRecorder(run_id=active_run_id)
    provenance = GenerationProvenance(
        run_id=active_run_id,
        workflow="paper-outline" if outline is not None else "paper",
        writing_mode="academic",
        outline_present=outline is not None,
        voice_profile=("configured_voice_profile" if cfg.voice_profile else None),
    )
    if outline is not None:
        from howlwriter.academic.outline_bridge import (
            research_questions,
            spec_from_outline,
        )
        from howlwriter.outline.freedom import assess_freedom

        spec = spec_from_outline(outline, base=spec)
        assessment = assess_freedom(outline)
        provenance.generation_freedom = assessment.freedom.value
        provenance.outline_sha256 = prov_sha256(outline.to_json())
        provenance.outline_summary = summarize_outline(outline)
        provenance.research["requested"] = research_questions(outline)
    recorder_token = recorder.activate()

    realization = None
    if cfg.voice_profile:
        from howlwriter.humanize.rewriter import _load_voice_profile
        from howlwriter.voice.realization import derive_structural_realization

        profile = _load_voice_profile(cfg.voice_profile)
        if profile is not None:
            realization = derive_structural_realization(
                profile=profile,
                mode=WritingMode.ACADEMIC,
                outline=outline,
                target_words=spec.target_words,
                input_text=spec.topic,
                seed=seed,
                freedom=provenance.generation_freedom,
            )
            if realization:
                provenance.structural_realization = realization.to_dict()

    _notify("validate", "DONE", "Assignment Validated", {
        "title": spec.title,
        "topic": spec.topic,
        "target_words": spec.target_words,
        "minimum_sources": spec.source_requirements.minimum_sources,
    })

    bridge = get_howlplane_bridge()
    can_use_models = not deterministic_only and (
        bridge.is_available() or custom_backend is not None
    )

    # 1. RESEARCH & SOURCE COLLECTION
    _notify("research", "RUNNING", "Research & Source Discovery")
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
    _notify("research", "DONE", "Research & Source Discovery", {
        "sources_count": len(sources),
        "duration": researcher_duration,
        "provider": researcher_provider,
    })

    # 2. DRAFTING (WRITER ROLE)
    _notify("drafting", "RUNNING", "Drafting Paper")
    t_writer_start = time.time()
    writer_provider: str | None = None
    writer_stated_claims: list[dict] = []
    writer_added_claims: list[dict] = []

    if can_use_models:
        writer = ModelAcademicWriter()
        draft_res = writer.draft_paper(
            spec,
            sources,
            config=cfg,
            cwd=cwd,
            custom_backend=custom_backend,
            run_id=active_run_id,
            realization=realization,
        )
        draft_doc = draft_res.document
        writer_provider = draft_res.provider
        writer_stated_claims = _normalize_claim_entries(draft_res.claims_stated)
        writer_added_claims = _normalize_claim_entries(draft_res.added_claims)
        provenance.added_claims = _model_added_claims(
            writer_stated_claims, writer_added_claims, outline
        )
    else:
        # Deterministic drafting fallback: structured sections with evidence placeholders
        body_sections: list[str] = [f"# {spec.title}\n"]
        for topic in spec.outline:
            body_sections.append(f"## {topic}\n\nAnalysis and discussion of {topic.lower()}.")
        if outline is not None:
            body_sections[1:1] = [
                node.text for node in outline.preserved() if node.text.strip()
            ]
        body_text = "\n\n".join(body_sections)
        draft_doc = Document.parse(body_text, title=spec.title, mode=WritingMode.ACADEMIC)

    initial_preserve_violations = preserved_violations(outline, draft_doc.text)
    if initial_preserve_violations:
        ids = ", ".join(f.node_id for f in initial_preserve_violations)
        raise RuntimeError(
            "Academic writer violated the verbatim-preserve contract for "
            f"outline passage(s): {ids}. No altered artifact was accepted."
        )

    writer_duration = round(time.time() - t_writer_start, 2)
    _notify("drafting", "DONE", "Drafting Paper", {
        "duration": writer_duration,
        "provider": writer_provider,
        "claims_stated": len(writer_stated_claims),
    })

    # 3. WORD COUNT & BOUNDED LENGTH CORRECTION
    _notify("length_check", "RUNNING", "Word Count & Length Check")
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
            candidate_doc = corr_res.document
            violations = preserved_violations(outline, candidate_doc.text)
            if violations:
                _record_preserve_rejection(
                    provenance, stage="length_correction", violations=violations
                )
                break
            draft_doc = candidate_doc
            actual_words = count_body_words(draft_doc.text)
            wc_status, wc_reason = evaluate_word_count_bounds(
                actual_words,
                bounds.min_words,
                bounds.max_words,
                bounds.target_words,
                hard_max_words=bounds.hard_max_words,
            )
            retries += 1

    _notify("length_check", "DONE", "Word Count & Length Check", {
        "actual_words": actual_words,
        "target_words": bounds.target_words,
        "min_words": bounds.min_words,
        "max_words": bounds.max_words,
        "hard_max_words": bounds.hard_max_words,
        "status": wc_status,
        "reason": wc_reason,
    })

    # 4. OUTLINE CONFORMANCE CHECK
    _notify("outline_check", "RUNNING", "Outline Conformance")
    outline_res = check_outline_conformance(draft_doc, spec.outline)
    _notify("outline_check", "DONE", "Outline Conformance", {
        "status": outline_res.status,
        "required": outline_res.required_topics_count,
        "present": outline_res.present_topics_count,
    })

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
    _notify("claim_verification", "RUNNING", "Claim & Provenance Verification")
    verifier = AcademicVerifier()
    provenance_graph, verif_summary = verifier.build_provenance_and_verify(
        draft_doc,
        sources,
        stated_claims=writer_stated_claims,
        additional_grounding_texts=[spec.topic, *spec.requirements, *spec.known_identifiers],
    )
    unsupported_ids = {c.id for c in provenance_graph.unsupported_claims()}
    supported_additions = {
        claim.text
        for claim in provenance_graph.claims.values()
        if claim.id not in unsupported_ids
    }
    claim_review = review_additions(
        provenance.added_claims,
        outline,
        research_backed=True,
        supported_claims=supported_additions,
    )
    provenance.review["model_additions"] = claim_review.to_dict()
    provenance.warnings.extend(claim_review.notes)
    _notify("claim_verification", "DONE", "Claim & Provenance Verification", {
        "supported": verif_summary.supported_claims,
        "partially_supported": verif_summary.partially_supported_claims,
        "unsupported": verif_summary.unsupported_claims,
        "contradicted": verif_summary.contradicted_claims,
        "total_claims": len(provenance_graph.claims),
    })

    # 6. HUMANIZE (ACADEMIC CONTEXT)
    _notify("humanizing", "RUNNING", "Safe Prose Humanizing")
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
            realization=realization,
        )
        candidate_doc = humanize_res.document
        violations = preserved_violations(outline, candidate_doc.text)
        structure_changed = bool(
            realization
            and realization.guidance_level == "none"
            and paragraph_structure_changed(draft_doc.text, candidate_doc.text)
        )
        if violations:
            _record_preserve_rejection(
                provenance, stage="humanizer", violations=violations
            )
            transformed_doc = draft_doc
        elif structure_changed:
            provenance.review.setdefault("authority_guard", []).append(
                {
                    "stage": "humanizer",
                    "action": "REJECTED_CANDIDATE_AND_RETAINED_PRIOR_ARTIFACT",
                    "near_complete_structure_changed": True,
                }
            )
            provenance.warnings.append(
                "Humanizer output was rejected because it restructured a "
                "near-complete draft whose authority level permits no sampled "
                "structural rewrite. The prior artifact was retained."
            )
            transformed_doc = draft_doc
        else:
            transformed_doc = candidate_doc
        humanizer_provider = humanize_res.provider
        humanize_duration = humanize_res.duration_seconds
    else:
        safe_res = SafeRewriter().rewrite(draft_doc, cfg)
        transformed_doc = safe_res.document
    _notify("humanizing", "DONE", "Safe Prose Humanizing", {
        "provider": humanizer_provider or "deterministic",
        "duration": humanize_duration,
    })

    # 7. LINT & RED PEN ON TRANSFORMED DOCUMENT
    _notify("lint_redpen", "RUNNING", "Deterministic Lint & Red Pen")
    lint_after = LintEngine().run(transformed_doc, cfg)
    claims_for_redpen = list(provenance_graph.claims.values())
    red_pen_findings = RedPenEngine().critique(transformed_doc, claims=claims_for_redpen)
    _notify("lint_redpen", "DONE", "Deterministic Lint & Red Pen", {
        "lint_count": len(lint_after),
        "red_pen_count": len(red_pen_findings),
    })

    # 8. MEANING / SEMANTIC REVIEW
    _notify("meaning_review", "RUNNING", "Meaning Preservation Review")
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
        reviewer_independence = normalize_reviewer_independence(
            semantic_res.independence_status
        )
        if getattr(semantic_res, "fallback_record", None):
            provenance.reviewer_fallbacks.append(semantic_res.fallback_record)
        provenance.reviewer_independence_by_stage["meaning_review"] = (
            reviewer_independence or "UNKNOWN"
        )
        meaning_review_duration = semantic_res.duration_seconds
    elif humanizer_provider is not None:
        reviewer_independence = "NO_REVIEWER"
        provenance.reviewer_independence_by_stage["meaning_review"] = "NO_REVIEWER"

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
        if getattr(consistency_res, "fallback_record", None):
            provenance.reviewer_fallbacks.append(consistency_res.fallback_record)
            consistency_indep = normalize_reviewer_independence(
                consistency_res.fallback_record.independence_status
            )
        else:
            reviewed_provider = humanizer_provider or writer_provider
            consistency_indep = (
                "INDEPENDENT_PROVIDER"
                if (
                    reviewed_provider
                    and consistency_res.provider
                    and reviewed_provider != consistency_res.provider
                )
                else (
                    "SAME_PROVIDER"
                    if reviewed_provider and consistency_res.provider
                    else "UNKNOWN"
                )
            )
        provenance.reviewer_independence_by_stage["consistency_review"] = consistency_indep
    else:
        provenance.reviewer_independence_by_stage["consistency_review"] = "NO_REVIEWER"
    reviewer_independence = provenance.reviewer_independence()
    _notify("meaning_review", "DONE", "Meaning Preservation Review", {
        "deterministic_status": meaning_det.status,
        "semantic_status": semantic_res.verdict if semantic_res else None,
        "reviewer_provider": meaning_reviewer_provider,
        "independence": reviewer_independence,
        "consistency_status": consistency_res.verdict if consistency_res else None,
    })

    # 9. APA 7 CITATIONS & REFERENCES SECTION ATTACHMENT
    _notify("citations_references", "RUNNING", "APA 7 Citations & References")
    citation_mgr = AcademicCitationManager()
    citation_analysis = citation_mgr.analyze_and_build_references(
        transformed_doc, sources
    )
    final_document = citation_mgr.attach_references(
        transformed_doc, citation_analysis
    )
    final_preserve_violations = preserved_violations(outline, final_document.text)
    if final_preserve_violations:
        ids = ", ".join(f.node_id for f in final_preserve_violations)
        raise RuntimeError(
            "A post-processing stage violated the verbatim-preserve contract "
            f"for passage(s): {ids}. No altered final artifact was accepted."
        )
    _notify("citations_references", "DONE", "APA 7 Citations & References", {
        "in_text_citations": citation_analysis.in_text_citation_count,
        "references_count": len(citation_analysis.used_sources) or len(sources),
        "warnings_count": len(citation_analysis.warnings),
    })

    # 10. EVALUATE FINAL READINESS STATUS
    # Academic criteria for READY:
    # - Word count within the hard bounds (wc_status in ("PASS", "TARGET_MISS");
    #   TARGET_MISS -- missing only the soft preferred range while staying
    #   under any hard ceiling -- is a quality signal, not a blocking one;
    #   only TOO_SHORT/HARD_LIMIT_FAILURE block readiness. See
    #   academic/length.py's evaluate_word_count_bounds.)
    # - Outline conformance (outline_res.status == "PASS")
    # - Preserved passages and required outline points honored (coverage passes)
    # - Sources count meets minimum requirement
    # - No unsupported or contradicted factual claims
    # - No ungrounded direct quotations
    # - Semantic review passes (if performed)
    # - No banned words remaining

    banned_word_count = sum(
        1 for m in lint_after if m.rule_code == AI_STYLE_BANNED_WORD
    )
    ai_style_count = len(lint_after) - banned_word_count

    # Technique detection coverage validation
    attack_ids = sorted(set(re.findall(r"\bT\d{4}(?:\.\d{3})?\b", final_document.body_text)))
    requires_detection = any(
        any(k in r.lower() for k in ("detection", "telemetry", "defensive", "sensor", "observability", "logging", "choke point"))
        for r in (spec.requirements or []) + [spec.topic, spec.title]
    )
    if requires_detection and attack_ids:
        detection_summary = evaluate_technique_detection_coverage(final_document, attack_ids)
        if detection_summary.status == "FAIL":
            for m in detection_summary.missing_techniques:
                verif_summary.identifier_warnings.append(
                    f"Technique detection coverage missing for {m}: no mapped detection telemetry or observability analysis."
                )

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

    authorship_coverage = None
    has_authorship_deficiency = False
    if outline is not None:
        authorship_coverage = check_coverage(outline, final_document.text)
        provenance.coverage = authorship_coverage.to_dict()
        has_authorship_deficiency = authorship_coverage.status == "FAIL"

    if (
        has_length_deficiency
        or outline_res.status != "PASS"
        or coverage_res.status != "PASS"
        or has_authorship_deficiency
        or has_source_deficiency
        or has_claim_deficiency
        or claim_review.blocks_readiness
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
    _notify("final_report", "DONE", "Final Report & Dogfood Record", {
        "status": final_status,
        "run_id": active_run_id,
        "total_duration": total_duration,
    })

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

    recorder.deactivate(recorder_token)
    provenance.calls = list(recorder.calls)
    provenance.artifact_sha256 = compute_sha256(final_document.text)
    provenance.completed_at = datetime.now(timezone.utc).isoformat()
    # Every read below is a contract with another stage's result dataclass.
    #  was one of these and did not exist; the field is
    # , and no deterministic test reached this line because the
    # consistency reviewer needs both a model and staged content. See
    # tests/academic/test_provenance_contract.py.
    provenance.review.update({
        "meaning_preservation": meaning_det.status,
        "semantic_meaning": semantic_res.verdict if semantic_res else None,
        "consistency": consistency_res.verdict if consistency_res else None,
        "readiness": final_status,
    })
    provenance.research.update(
        {
            "sources_retrieved": len(sources),
            "claims_verified": len(provenance_graph.claims),
            "unsupported_claims": len(provenance_graph.unsupported_claims()),
        }
    )
    if outline is not None and authorship_coverage is None:
        authorship_coverage = check_coverage(outline, final_document.text)
        provenance.coverage = authorship_coverage.to_dict()

    provenance.contribution = build_contribution(
        outline,
        coverage=provenance.coverage,
        artifact_text=final_document.text,
        added_claims=provenance.added_claims,
        gaps=provenance.gaps,
        research_grounded=sum(
            1
            for finding in claim_review.new_factual
            if finding.claim in supported_additions
        ),
        unsupported=sum(
            1
            for finding in claim_review.new_factual
            if finding.claim not in supported_additions
        ),
    )
    provenance.complete = True
    save_provenance(provenance)
    ai_statement = build_ai_use_statement(provenance)

    return AcademicPipelineResult(
        authorship_coverage=authorship_coverage,
        provenance=provenance,
        ai_use_statement=ai_statement,
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
