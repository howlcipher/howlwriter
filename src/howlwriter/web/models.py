"""Pydantic schemas for HowlWriter local web API."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# Document Models
class OpenDocumentRequest(BaseModel):
    path: str


class SaveDocumentRequest(BaseModel):
    path: str
    content: str


class DocumentStatsResponse(BaseModel):
    path: Optional[str] = None
    title: str = ""
    word_count: int = 0
    char_count: int = 0
    line_count: int = 0
    mode: str = "article"


class DocumentResponse(BaseModel):
    path: Optional[str] = None
    title: str = ""
    content: str = ""
    word_count: int = 0
    char_count: int = 0
    line_count: int = 0
    mode: str = "article"


# Linting Models
class LintRequest(BaseModel):
    text: str
    title: Optional[str] = None
    config_path: Optional[str] = None


class RuleMatchDto(BaseModel):
    rule_code: str
    message: str
    matched_text: str = ""
    category: Optional[str] = None
    severity: str = "warning"
    paragraph_index: Optional[int] = None
    sentence_index: Optional[int] = None
    snippet: Optional[str] = None
    replacement: Optional[str] = None
    suggestion: Optional[str] = None


class LintResponse(BaseModel):
    matches: list[RuleMatchDto]
    banned_words_count: int
    ai_style_warnings_count: int
    total_count: int


# Red Pen Critic Models
class RedPenRequest(BaseModel):
    text: str
    title: Optional[str] = None
    claims: list[dict[str, Any]] = Field(default_factory=list)


class RedPenFindingDto(BaseModel):
    finding: str
    reason: str
    recommendation: str
    category: str
    severity: str
    location: Optional[str] = None
    paragraph_index: Optional[int] = None
    snippet: Optional[str] = None


class RedPenResponse(BaseModel):
    findings: list[RedPenFindingDto]
    total_count: int


# Humanize Models
class HumanizeRequest(BaseModel):
    text: str
    title: Optional[str] = None
    mode: Optional[str] = "general"
    deterministic_only: bool = False
    apply_safe_rewrites: bool = False
    config_path: Optional[str] = None
    cwd: Optional[str] = None
    voice_profile: Optional[str] = None
    #: Name of a personal voice in the local registry. An alternative to
    #: voice_profile, not an addition: passing both is rejected.
    voice: Optional[str] = None


class ChangeRecordDto(BaseModel):
    description: str
    category: str = "humanize"
    reason: Optional[str] = None
    location: Optional[str] = None


class HumanizeResponse(BaseModel):
    original_text: str
    transformed_text: str
    changes: list[ChangeRecordDto]
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None
    duration_seconds: float = 0.0
    independence_status: str = "INDEPENDENT"
    lint_before: list[RuleMatchDto] = Field(default_factory=list)
    lint_after: list[RuleMatchDto] = Field(default_factory=list)
    lint_before_count: int = 0
    lint_after_count: int = 0
    banned_words_count: int = 0
    ai_style_warnings_count: int = 0
    meaning_preservation_status: str = "PASS"
    semantic_meaning_status: Optional[str] = None
    mode: Optional[str] = None
    change_count: int = 0
    run_id: str
    status: str = "READY"


# Howl Pipeline Models
class HowlPipelineRequest(BaseModel):
    text: str
    title: Optional[str] = None
    mode: Optional[str] = "general"
    deterministic_only: bool = False
    apply_safe_rewrites: bool = False
    config_path: Optional[str] = None
    cwd: Optional[str] = None
    voice_profile: Optional[str] = None
    #: Name of a personal voice in the local registry. An alternative to
    #: voice_profile, not an addition: passing both is rejected.
    voice: Optional[str] = None


class HowlPipelineResponse(BaseModel):
    original_text: str
    final_text: str
    lint_matches: list[RuleMatchDto]
    red_pen_findings: list[RedPenFindingDto]
    meaning_preservation: str
    semantic_meaning_status: Optional[str] = None
    status: str
    run_id: str
    report: dict[str, Any]


# Academic Assignment Models
class SourceRequirementsDto(BaseModel):
    minimum_sources: int = 4
    prefer_primary_sources: bool = True
    scholarly_or_authoritative: bool = True
    allowed_types: list[str] = Field(default_factory=list)


class AssignmentSpecDto(BaseModel):
    title: str = ""
    topic: str = ""
    type: str = "academic"
    target_words: int = 2000
    word_tolerance_percent: float = 10.0
    citation_style: str = "apa7"
    source_requirements: SourceRequirementsDto = Field(default_factory=SourceRequirementsDto)
    requirements: list[str] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    voice_profile: Optional[str] = None
    #: Name of a personal voice in the local registry. An alternative to
    #: voice_profile, not an addition: passing both is rejected.
    voice: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidateSpecRequest(BaseModel):
    spec: AssignmentSpecDto


class ValidateSpecResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    spec: AssignmentSpecDto
    yaml_preview: str


class GeneratePaperRequest(BaseModel):
    spec: AssignmentSpecDto
    deterministic_only: bool = False
    cwd: Optional[str] = None
    output_formats: list[str] = Field(default_factory=list)
    output_dir: Optional[str] = None
    overwrite: bool = False
    verify_sources: bool = True
    publish: Optional[str] = None
    publish_title: Optional[str] = None
    publish_folder: Optional[str] = None
    update_doc_id: Optional[str] = None
    update_mode: str = "replace"
    allow_unverified: bool = False


# Provenance, Verification, and Source Models
class ReviewReasonDto(BaseModel):
    category: str  # RESEARCH_SUFFICIENCY, SOURCE_CLAIM_SUPPORT, SEMANTIC_REVIEW, etc.
    severity: str = "warning"  # info, warning, critical
    title: str
    explanation: str


class SourceDto(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_date: Optional[str] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    publisher: Optional[str] = None
    source_type: Optional[str] = None
    retrieved_text: Optional[str] = None
    claims_count: int = 0
    in_text_citations_count: int = 0
    relevance: str = "DIRECT"  # DIRECT, SUPPORTING, TANGENTIAL, IRRELEVANT
    evidence_origin: str = "METADATA_ONLY"  # FULL_TEXT, ABSTRACT, METADATA_ONLY, OTHER
    relevance_notes: Optional[str] = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceDto(BaseModel):
    id: str
    source_id: str
    source_title: str
    source_url: Optional[str] = None
    source_doi: Optional[str] = None
    excerpt: str
    origin_type: str = "METADATA_ONLY"  # FULL_TEXT, ABSTRACT, METADATA_ONLY, OTHER
    page_or_section: Optional[str] = None
    confidence: float = 1.0


class ClaimDto(BaseModel):
    id: str
    claim_text: str
    verdict: str  # SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONTRADICTED
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceDto] = Field(default_factory=list)
    reasoning: Optional[str] = None
    paragraph_index: Optional[int] = None
    in_text_citations: list[str] = Field(default_factory=list)


class AcademicResultDto(BaseModel):
    paper_text: str
    title: str
    topic: str
    target_words: int
    min_words: int
    max_words: int
    actual_body_words: int
    word_count_status: str
    outline_status: str
    required_outline_topics: int
    present_outline_topics: int
    sources_retrieved: int
    sources_used: int
    sources_required: int
    sources_sufficiency_status: str = "SUFFICIENT"
    supported_claims: int
    partially_supported_claims: int
    unsupported_claims: int
    contradicted_claims: int
    citation_style: str
    in_text_citations: int
    reference_entries: int
    citation_warnings: int
    writer_provider: Optional[str] = None
    researcher_provider: Optional[str] = None
    humanizer_provider: Optional[str] = None
    meaning_reviewer_provider: Optional[str] = None
    meaning_reviewer_verdict: Optional[str] = None
    meaning_reviewer_explanation: Optional[str] = None
    reviewer_independence: Optional[str] = None
    reviewer_independence_reason: Optional[str] = None
    banned_words: int = 0
    ai_style_warnings: int = 0
    meaning_preservation: str = "PASS"
    semantic_meaning_status: Optional[str] = None
    status: str = "READY"
    run_id: str
    sources: list[SourceDto] = Field(default_factory=list)
    claims: list[ClaimDto] = Field(default_factory=list)
    references_text: str = ""
    warnings: list[str] = Field(default_factory=list)
    review_reasons: list[ReviewReasonDto] = Field(default_factory=list)
    source_integrity_status: str = "PASS"
    source_integrity_warnings: int = 0
    source_integrity_findings: list[dict[str, Any]] = Field(default_factory=list)
    local_outputs: list[dict[str, Any]] = Field(default_factory=list)
    publication_results: list[dict[str, Any]] = Field(default_factory=list)


# Publishing Models
class PublishRequest(BaseModel):
    file_path: str
    destination: str = "google-docs"
    title: Optional[str] = None
    folder: Optional[str] = None
    update_doc_id: Optional[str] = None
    update_mode: str = "replace"
    allow_unverified: bool = False


class PublishResponse(BaseModel):
    success: bool
    destination: str
    document_id: Optional[str] = None
    document_url: Optional[str] = None
    version_or_revision: Optional[str] = None
    published_at: str
    error_message: Optional[str] = None


class GoogleAuthStatusResponse(BaseModel):
    authenticated: bool
    token_path: str
    scopes: list[str] = Field(default_factory=list)
    client_secrets_found: bool
    client_secrets_path: Optional[str] = None
    error: Optional[str] = None


# Job Models
class StageDto(BaseModel):
    id: str
    label: str
    status: str = "PENDING"  # PENDING, RUNNING, DONE, FAILED
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    data: dict[str, Any] = Field(default_factory=dict)


# Voice Models
#
# Everything exposed here is a summary. The UI never receives a corpus
# passage, and by default it never receives a source path either -- a voice is
# built from someone's own writing, and a browser tab is a poor place for
# either to surface.
class VoiceTraitDto(BaseModel):
    name: str
    value: str
    confidence: float = 0.0
    confidence_band: str = "UNKNOWN"
    supporting_documents: int = 0
    supporting_words: int = 0
    agreement: float = 0.0
    source: str = "deterministic"


class VoiceContextDto(BaseModel):
    name: str
    document_count: int = 0
    word_count: int = 0
    confidence: float = 0.0
    sufficiency: str = "unknown"
    traits: list[VoiceTraitDto] = Field(default_factory=list)


class VoiceCorpusSummaryDto(BaseModel):
    documents_discovered: int = 0
    unique_canonical_files: int = 0
    candidate_prose_files: int = 0
    included_documents: int = 0
    holdout_documents: int = 0
    excluded_documents: int = 0
    held_for_review_documents: int = 0
    exact_duplicates: int = 0
    cross_format_duplicates: int = 0
    revision_groups: int = 0
    extraction_failures: int = 0
    scanned_or_unreadable: int = 0
    training_words: int = 0
    holdout_words: int = 0
    sufficiency: str = "unknown"
    sufficiency_warnings: list[str] = Field(default_factory=list)
    words_by_context: dict[str, int] = Field(default_factory=dict)
    documents_by_context: dict[str, int] = Field(default_factory=dict)
    quality_classifications: dict[str, int] = Field(default_factory=dict)
    exclusion_reasons: dict[str, int] = Field(default_factory=dict)


class VoiceValidationDto(BaseModel):
    alignment: dict[str, str] = Field(default_factory=dict)
    overall_confidence: str = "UNKNOWN"
    holdout_documents: int = 0
    holdout_words: int = 0
    diversity_preservation: str = "NOT_EVALUATED"
    warnings: list[str] = Field(default_factory=list)


class VoiceOverridesDto(BaseModel):
    preserve: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    traits: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class VoiceSummaryDto(BaseModel):
    """One row in the voice list."""

    name: str
    profile_type: str = "personal_voice"
    built_at: str = ""
    included_documents: int = 0
    training_words: int = 0
    contexts: list[str] = Field(default_factory=list)
    overall_confidence: str = "UNKNOWN"
    sufficiency: str = "unknown"


class VoiceDetailDto(BaseModel):
    """Everything the UI may show about one voice."""

    name: str
    profile_type: str = "personal_voice"
    built_at: str = ""
    version: int = 0
    traits: list[VoiceTraitDto] = Field(default_factory=list)
    contexts: list[VoiceContextDto] = Field(default_factory=list)
    corpus: VoiceCorpusSummaryDto = Field(default_factory=VoiceCorpusSummaryDto)
    validation: VoiceValidationDto = Field(default_factory=VoiceValidationDto)
    overrides: VoiceOverridesDto = Field(default_factory=VoiceOverridesDto)
    warnings: list[str] = Field(default_factory=list)
    distributions: dict[str, float] = Field(default_factory=dict)


class VoiceRebuildRequest(BaseModel):
    deterministic: bool = False
    reuse_cache: bool = True


class VoiceBuildResultDto(BaseModel):
    name: str
    directory: str = ""
    detail: Optional[VoiceDetailDto] = None
    warnings: list[str] = Field(default_factory=list)


class JobResponse(BaseModel):
    job_id: str
    run_id: str
    job_type: str
    status: str  # QUEUED, RUNNING, COMPLETED, FAILED
    created_at: float
    updated_at: float
    elapsed_seconds: float = 0.0
    current_stage_id: Optional[str] = None
    stages: list[StageDto] = Field(default_factory=list)
    error_message: Optional[str] = None
    failure_category: Optional[str] = None
    result: Optional[AcademicResultDto | VoiceBuildResultDto] = None


# Run History Models
class RunRecordDto(BaseModel):
    run_id: str
    timestamp: str
    command: str
    writing_mode: Optional[str] = None
    success: bool
    status: str
    humanizer_provider: Optional[str] = None
    meaning_reviewer_provider: Optional[str] = None
    reviewer_independence: Optional[str] = None
    lint_before_count: Optional[int] = None
    lint_after_count: Optional[int] = None
    banned_words: Optional[int] = None
    ai_style_warnings: Optional[int] = None
    meaning_preservation: Optional[str] = None
    semantic_meaning_status: Optional[str] = None
    humanizer_duration_seconds: Optional[float] = None
    meaning_reviewer_duration_seconds: Optional[float] = None
    total_duration_seconds: Optional[float] = None
    input_path: Optional[str] = None
    input_chars: int = 0
    input_sha256: Optional[str] = None
    output_chars: Optional[int] = None
    output_sha256: Optional[str] = None
    failure_category: Optional[str] = None
    error_message: Optional[str] = None
    exit_code: int = 0
    howlplane_task_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Provider Models
class RoleBindingDto(BaseModel):
    role: str
    role_label: str
    domain: str = "writing"
    provider: Optional[str] = None
    model: Optional[str] = None
    is_configured: bool = False
    timeout_seconds: int = 300
    description: str = ""


class ProviderStatusDto(BaseModel):
    id: str
    name: str
    is_installed: bool
    command_path: Optional[str] = None
    description: str = ""


class ProvidersResponse(BaseModel):
    bridge_available: bool
    role_bindings: list[RoleBindingDto]
    available_providers: list[ProviderStatusDto]
    reviewer_independence: str  # INDEPENDENT, SAME_PROVIDER, NOT_REVIEWED, UNAVAILABLE
    reviewer_independence_reason: str
