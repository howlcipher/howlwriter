"""Academic paper endpoints: spec validation and pipeline execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException
import yaml

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import (
    AssignmentSpec,
    SourceRequirements,
    validate_assignment_spec,
)
from howlwriter.citations.apa7 import APA7Formatter
from howlwriter.domain.claim import VerificationStatus
from howlwriter.web.jobs import Job, get_job_manager
from howlwriter.web.models import (
    AcademicResultDto,
    AssignmentSpecDto,
    ClaimDto,
    EvidenceDto,
    GeneratePaperRequest,
    JobResponse,
    ReviewReasonDto,
    SourceDto,
    SourceRequirementsDto,
    ValidateSpecRequest,
    ValidateSpecResponse,
)

router = APIRouter(prefix="/api/academic", tags=["academic"])


def _dto_to_spec(dto: AssignmentSpecDto) -> AssignmentSpec:
    return AssignmentSpec(
        title=dto.title,
        topic=dto.topic,
        type=dto.type,
        target_words=dto.target_words,
        word_tolerance_percent=dto.word_tolerance_percent,
        citation_style=dto.citation_style,
        source_requirements=SourceRequirements(
            minimum_sources=dto.source_requirements.minimum_sources,
            prefer_primary_sources=dto.source_requirements.prefer_primary_sources,
            scholarly_or_authoritative=dto.source_requirements.scholarly_or_authoritative,
            allowed_types=dto.source_requirements.allowed_types,
        ),
        requirements=dto.requirements,
        outline=dto.outline,
        voice_profile=dto.voice_profile,
        metadata=dto.metadata,
    )


def _spec_to_dto(spec: AssignmentSpec) -> AssignmentSpecDto:
    return AssignmentSpecDto(
        title=spec.title,
        topic=spec.topic,
        type=spec.type,
        target_words=spec.target_words,
        word_tolerance_percent=spec.word_tolerance_percent,
        citation_style=spec.citation_style,
        source_requirements=SourceRequirementsDto(
            minimum_sources=spec.source_requirements.minimum_sources,
            prefer_primary_sources=spec.source_requirements.prefer_primary_sources,
            scholarly_or_authoritative=spec.source_requirements.scholarly_or_authoritative,
            allowed_types=spec.source_requirements.allowed_types,
        ),
        requirements=spec.requirements,
        outline=spec.outline,
        voice_profile=spec.voice_profile,
        metadata=spec.metadata,
    )


@router.post("/validate", response_model=ValidateSpecResponse)
def validate_spec(req: ValidateSpecRequest) -> ValidateSpecResponse:
    try:
        spec = _dto_to_spec(req.spec)
        errors = validate_assignment_spec(spec)
        yaml_str = yaml.dump(spec.to_dict(), sort_keys=False, indent=2)
        return ValidateSpecResponse(
            valid=len(errors) == 0,
            errors=errors,
            spec=_spec_to_dto(spec),
            yaml_preview=yaml_str,
        )
    except Exception as exc:
        return ValidateSpecResponse(
            valid=False,
            errors=[str(exc)],
            spec=req.spec,
            yaml_preview="",
        )


@router.post("/generate", response_model=JobResponse)
def start_generate_paper(req: GeneratePaperRequest) -> JobResponse:
    spec = _dto_to_spec(req.spec)
    errors = validate_assignment_spec(spec)
    if errors:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid assignment spec: {'; '.join(errors)}",
        )

    manager = get_job_manager()
    job = manager.create_job(job_type="academic_paper")

    def _task(j: Job) -> None:
        def _on_stage(stage_id: str, status: str, data: dict[str, Any]) -> None:
            j.update_stage(stage_id, status, data)

        cwd_path = Path(req.cwd) if req.cwd else Path.cwd()
        res = run_academic_pipeline(
            assignment=spec,
            deterministic_only=req.deterministic_only,
            run_id=j.run_id,
            cwd=cwd_path,
            stage_callback=_on_stage,
        )

        # Build Sources DTOs
        source_dtos: list[SourceDto] = []
        source_id_map: dict[str, SourceDto] = {}
        for s in res.sources:
            # Use the domain's authoritative evidence_depth. Do not infer FULL_TEXT
            # from character count; depth is assigned by the retrieval subsystem.
            evidence_origin = s.evidence_depth if s.evidence_depth else "OTHER"
            relevance = s.relevance if s.relevance else "DIRECT"

            used_in_text = any(us.id == s.id for us in res.citation_analysis.used_sources)
            raw_meta = {
                "raw_authors": s.authors,
                "raw_title": s.title,
                "raw_publication_date": s.publication_date.isoformat() if s.publication_date else None,
                "raw_publisher": s.publisher,
                "raw_doi": s.doi,
                "raw_url": s.url,
                "retrieved_char_count": len(s.retrieved_text) if s.retrieved_text else 0,
            }

            sdto = SourceDto(
                id=s.id,
                title=s.title,
                authors=s.authors,
                publication_date=s.publication_date.isoformat() if s.publication_date else None,
                url=s.url,
                doi=s.doi,
                publisher=s.publisher,
                source_type=s.source_type.value if s.source_type else None,
                retrieved_text=s.retrieved_text,
                claims_count=len(res.provenance_graph.claims_for_source(s.id)),
                in_text_citations_count=1 if used_in_text else 0,
                relevance=relevance,
                evidence_origin=evidence_origin,
                raw_metadata=raw_meta,
                metadata={},
            )
            source_dtos.append(sdto)
            source_id_map[s.id] = sdto

        # Build Claims & Evidence DTOs
        claim_dtos: list[ClaimDto] = []
        for cid, c in res.provenance_graph.claims.items():
            ev_list = res.provenance_graph.evidence_for_claim(cid)
            ev_dtos = []
            for ev in ev_list:
                src = res.provenance_graph.sources.get(ev.source_id)
                # Preserve authoritative evidence depth from the retrieval subsystem.
                origin = src.evidence_depth if src and src.evidence_depth else "OTHER"

                ev_dtos.append(
                    EvidenceDto(
                        id=ev.id,
                        source_id=ev.source_id,
                        source_title=src.title if src else "Unknown Source",
                        source_url=src.url if src else None,
                        source_doi=src.doi if src else None,
                        excerpt=ev.snippet,
                        origin_type=origin,
                    )
                )

            if isinstance(c.verification_status, VerificationStatus):
                verdict_str = c.verification_status.value.upper()
            else:
                verdict_str = str(c.verification_status).upper()

            claim_dtos.append(
                ClaimDto(
                    id=c.id,
                    claim_text=c.text,
                    verdict=verdict_str,
                    evidence_ids=[e.id for e in ev_list],
                    source_ids=[e.source_id for e in ev_list] or c.supporting_sources,
                    evidence=ev_dtos,
                    reasoning=c.notes,
                    paragraph_index=c.document_span.paragraph_index if c.document_span else None,
                )
            )

        refs_text = APA7Formatter().reference_page(
            res.citation_analysis.used_sources or res.sources
        ).text

        citation_warnings = [
            w.message if hasattr(w, "message") else str(w)
            for w in res.citation_analysis.warnings
        ]
        all_warnings = citation_warnings + res.verification_summary.quotation_warnings

        # Audit Requirement 3: Source Sufficiency
        # Usable sources are those the domain classifies as DIRECT or SUPPORTING;
        # tangential or irrelevant sources must not satisfy the minimum.
        usable_sources_count = sum(1 for s in res.sources if s.is_usable)
        used_usable_sources_count = sum(
            1 for s in res.citation_analysis.used_sources if s.is_usable
        )
        sources_retrieved_count = res.report.sources_retrieved or usable_sources_count
        sources_required_count = res.report.sources_required or res.spec.source_requirements.minimum_sources
        sources_used_count = res.report.sources_used or used_usable_sources_count
        is_source_deficient = sources_retrieved_count < sources_required_count
        sources_sufficiency = "DEFICIENT" if is_source_deficient else "SUFFICIENT"

        # Audit Requirement 5: Categorized Review Reasons
        review_reasons_list: list[ReviewReasonDto] = []

        # 1. Research Sufficiency
        if is_source_deficient:
            review_reasons_list.append(
                ReviewReasonDto(
                    category="RESEARCH_SUFFICIENCY",
                    severity="critical",
                    title=(
                        f"Source Deficiency ({sources_retrieved_count} gathered, "
                        f"{sources_required_count} required)"
                    ),
                    explanation=(
                        f"The research phase gathered {sources_retrieved_count} usable sources, "
                        f"falling short of the requested minimum ({sources_required_count}). "
                        "Try expanding topic keywords or broadening search constraints."
                    ),
                )
            )

        # 2. Source / Claim Support
        unsupported_count = res.report.unsupported_claims or 0
        contradicted_count = res.report.contradicted_claims or 0
        abstract_only_count = sum(1 for s in source_dtos if s.evidence_origin == "ABSTRACT")
        metadata_only_count = sum(1 for s in source_dtos if s.evidence_origin == "METADATA_ONLY")

        if unsupported_count > 0 or contradicted_count > 0:
            review_reasons_list.append(
                ReviewReasonDto(
                    category="SOURCE_CLAIM_SUPPORT",
                    severity="critical",
                    title=f"Unverified Claims ({unsupported_count} unsupported)",
                    explanation=(
                        f"{unsupported_count} claims drafted in the text lacked sufficient evidence in "
                        "retrieved literature to verify factual support."
                    ),
                )
            )

        if abstract_only_count > 0 or metadata_only_count > 0:
            review_reasons_list.append(
                ReviewReasonDto(
                    category="SOURCE_CLAIM_SUPPORT",
                    severity="info",
                    title=(
                        f"Evidence Grounding: {abstract_only_count} Abstract / "
                        f"{metadata_only_count} Metadata-Only"
                    ),
                    explanation=(
                        "Truthful Grounding: Evidence is derived from scholarly abstracts and metadata. "
                        "Full paper body text was not inspected."
                    ),
                )
            )

        # 3. Semantic Review
        sem_status = res.report.semantic_meaning_status or res.report.meaning_preservation or "PASS"
        if sem_status not in ("PASS", "PASS_WITH_WARNINGS"):
            review_reasons_list.append(
                ReviewReasonDto(
                    category="SEMANTIC_REVIEW",
                    severity="warning",
                    title=f"Adversarial Semantic Review Flag ({sem_status})",
                    explanation=(
                        "Independent semantic reviewer identified potential factual "
                        "distortion or nuance drift. Reviewer judgments represent "
                        "automated scrutiny rather than absolute truth."
                    ),
                )
            )

        # 4. Word Count
        actual_words = res.report.actual_body_words or 0
        target_words = res.report.target_words or res.spec.target_words
        if res.report.word_count_status in ("TOO_SHORT", "TOO_LONG"):
            review_reasons_list.append(
                ReviewReasonDto(
                    category="WORD_COUNT",
                    severity="warning",
                    title=f"Word Count Deviation ({actual_words} / {target_words} words)",
                    explanation=(
                        f"Actual body length ({actual_words} words) is outside "
                        f"specified tolerance ({res.report.word_count_status})."
                    ),
                )
            )

        # 5. Outline
        if (res.report.present_outline_topics or 0) < (res.report.required_outline_topics or 0):
            review_reasons_list.append(
                ReviewReasonDto(
                    category="OUTLINE",
                    severity="warning",
                    title=(
                        f"Missing Outline Sections "
                        f"({res.report.present_outline_topics}/{res.report.required_outline_topics})"
                    ),
                    explanation="One or more mandatory assignment outline sections were omitted or altered.",
                )
            )

        # 6. Citations
        if len(all_warnings) > 0:
            review_reasons_list.append(
                ReviewReasonDto(
                    category="CITATIONS",
                    severity="info",
                    title=f"APA 7 Metadata Warnings ({len(all_warnings)} notices)",
                    explanation=(
                        "Missing upstream Crossref metadata (dates or authors) resulted in deterministic "
                        "APA 7 fallbacks ('n.d.' or title citation)."
                    ),
                )
            )

        result_dto = AcademicResultDto(
            paper_text=res.final_document.text,
            title=res.spec.title,
            topic=res.spec.topic,
            target_words=target_words,
            min_words=res.report.min_words or int(target_words * 0.9),
            max_words=res.report.max_words or int(target_words * 1.1),
            actual_body_words=actual_words,
            word_count_status=res.report.word_count_status or "UNKNOWN",
            outline_status=res.report.outline_status or "UNKNOWN",
            required_outline_topics=res.report.required_outline_topics or 0,
            present_outline_topics=res.report.present_outline_topics or 0,
            sources_retrieved=sources_retrieved_count,
            sources_used=sources_used_count,
            sources_required=sources_required_count,
            sources_sufficiency_status=sources_sufficiency,
            supported_claims=res.report.supported_claims or 0,
            partially_supported_claims=res.report.partially_supported_claims or 0,
            unsupported_claims=unsupported_count,
            contradicted_claims=contradicted_count,
            citation_style=res.report.citation_style or "apa7",
            in_text_citations=res.report.in_text_citations or 0,
            reference_entries=res.report.reference_entries or 0,
            citation_warnings=res.report.citation_warnings or len(all_warnings),
            writer_provider=res.report.writer_provider,
            researcher_provider=res.report.researcher_provider,
            humanizer_provider=res.report.humanizer_provider,
            meaning_reviewer_provider=res.report.meaning_reviewer_provider,
            meaning_reviewer_verdict=sem_status,
            meaning_reviewer_explanation=None,
            reviewer_independence=res.report.reviewer_independence,
            banned_words=res.report.banned_words or 0,
            ai_style_warnings=res.report.ai_style_warnings or 0,
            meaning_preservation=res.report.meaning_preservation or "PASS",
            semantic_meaning_status=res.report.semantic_meaning_status,
            status=res.report.status,
            run_id=res.report.run_id or j.run_id,
            sources=source_dtos,
            claims=claim_dtos,
            references_text=refs_text,
            warnings=all_warnings,
            review_reasons=review_reasons_list,
        )

        j.complete(result_dto)

    manager.start_in_background(job, _task)
    return job.to_dto()
