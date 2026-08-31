"""Academic paper and assignment writing subsystem."""

from howlwriter.academic.citations import AcademicCitationManager, CitationAnalysis
from howlwriter.academic.length import (
    calculate_word_tolerance,
    count_body_words,
    evaluate_word_count,
)
from howlwriter.academic.outline import OutlineResult, check_outline_conformance
from howlwriter.academic.pipeline import AcademicPipelineResult, run_academic_pipeline
from howlwriter.academic.research import (
    AcademicResearcher,
    derive_research_plan,
    fetch_arxiv_sources,
    fetch_crossref_sources,
    load_sources_file,
    save_sources_file,
)
from howlwriter.academic.spec import (
    AssignmentSpec,
    SourceRequirements,
    load_assignment_spec,
    validate_assignment_spec,
)
from howlwriter.academic.verifier import AcademicVerifier, VerificationSummary
from howlwriter.academic.writer import ModelAcademicWriter, WriterDraftResult

__all__ = [
    "AcademicCitationManager",
    "AcademicPipelineResult",
    "AcademicResearcher",
    "AcademicVerifier",
    "AssignmentSpec",
    "CitationAnalysis",
    "ModelAcademicWriter",
    "OutlineResult",
    "SourceRequirements",
    "VerificationSummary",
    "WriterDraftResult",
    "calculate_word_tolerance",
    "check_outline_conformance",
    "count_body_words",
    "derive_research_plan",
    "evaluate_word_count",
    "fetch_arxiv_sources",
    "fetch_crossref_sources",
    "load_assignment_spec",
    "load_sources_file",
    "run_academic_pipeline",
    "save_sources_file",
    "validate_assignment_spec",
]
