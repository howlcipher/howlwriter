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
            evidence_origin = "RETRIEVED_EXCERPT"
            if s.retrieved_text:
                is_arxiv = "arXiv:" in (s.doi or "") or "arxiv" in (s.url or "").lower()
                is_abstract = len(s.retrieved_text) < 1500 and (
                    "abstract" in s.retrieved_text.lower() or "doi" in s.retrieved_text.lower()
                )
                if is_arxiv:
                    evidence_origin = "ARXIV_EXCERPT"
                elif is_abstract:
                    evidence_origin = "ABSTRACT"
            elif s.doi or s.url:
                evidence_origin = "METADATA"

            used_in_text = any(us.id == s.id for us in res.citation_analysis.used_sources)
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
                evidence_origin=evidence_origin,
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
                origin = "METADATA"
                if src and src.retrieved_text:
                    if "arxiv" in (src.url or "").lower():
                        origin = "ARXIV_EXCERPT"
                    elif len(src.retrieved_text) < 1500:
                        origin = "ABSTRACT"
                    else:
                        origin = "RETRIEVED_EXCERPT"

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

        result_dto = AcademicResultDto(
            paper_text=res.final_document.text,
            title=res.spec.title,
            topic=res.spec.topic,
            target_words=res.report.target_words or res.spec.target_words,
            min_words=res.report.min_words or int(res.spec.target_words * 0.9),
            max_words=res.report.max_words or int(res.spec.target_words * 1.1),
            actual_body_words=res.report.actual_body_words or 0,
            word_count_status=res.report.word_count_status or "UNKNOWN",
            outline_status=res.report.outline_status or "UNKNOWN",
            required_outline_topics=res.report.required_outline_topics or 0,
            present_outline_topics=res.report.present_outline_topics or 0,
            sources_retrieved=res.report.sources_retrieved or 0,
            sources_used=res.report.sources_used or 0,
            sources_required=res.report.sources_required or 0,
            supported_claims=res.report.supported_claims or 0,
            partially_supported_claims=res.report.partially_supported_claims or 0,
            unsupported_claims=res.report.unsupported_claims or 0,
            contradicted_claims=res.report.contradicted_claims or 0,
            citation_style=res.report.citation_style or "apa7",
            in_text_citations=res.report.in_text_citations or 0,
            reference_entries=res.report.reference_entries or 0,
            citation_warnings=res.report.citation_warnings or 0,
            writer_provider=res.report.writer_provider,
            researcher_provider=res.report.researcher_provider,
            humanizer_provider=res.report.humanizer_provider,
            meaning_reviewer_provider=res.report.meaning_reviewer_provider,
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
        )

        j.complete(result_dto)

    manager.start_in_background(job, _task)
    return job.to_dto()
