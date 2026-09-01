"""Focused regression tests for the correctness-remediation milestone."""

from datetime import date

from howlwriter.academic.research import (
    classify_source_relevance,
    derive_research_plan,
)
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.academic.verifier import AcademicVerifier, _claim_escalates_evidence
from howlwriter.domain.claim import Claim, ClaimType
from howlwriter.domain.document import Document
from howlwriter.domain.source import (
    DEPTH_ABSTRACT,
    DEPTH_METADATA_ONLY,
    RELEVANCE_DIRECT,
    RELEVANCE_IRRELEVANT,
    RELEVANCE_SUPPORTING,
    RELEVANCE_TANGENTIAL,
    Source,
    SourceType,
)


def _source(**overrides) -> Source:
    defaults = dict(
        id="S001",
        title="Example title",
        authors=["Smith, Jane"],
        publication_date=date(2024, 1, 1),
        source_type=SourceType.JOURNAL_ARTICLE,
        evidence_depth=DEPTH_ABSTRACT,
        relevance=RELEVANCE_DIRECT,
    )
    defaults.update(overrides)
    return Source(**defaults)


def test_direct_source_is_accepted():
    src = _source(
        title="Rust ownership and memory safety in systems programming",
        retrieved_text="We evaluate Rust's borrow checker and ownership model.",
    )
    rel = classify_source_relevance(
        src,
        topic="Rust memory safety versus C++",
        query="Rust memory safety versus C++",
    )
    assert rel == RELEVANCE_DIRECT


def test_supporting_source_is_accepted_appropriately():
    src = _source(
        title="A survey of systems programming languages",
        retrieved_text="Many modern languages address memory safety; Rust is one example.",
    )
    rel = classify_source_relevance(
        src,
        topic="Rust memory safety versus C++",
        query="Rust memory safety versus C++",
    )
    assert rel == RELEVANCE_SUPPORTING


def test_keyword_overlap_tangential_source_is_rejected():
    # The word "verification" alone should not make a Bitcoin paper relevant
    # to Rust borrow-checking behavior.
    src = _source(
        title="Smart contract verification on the Bitcoin blockchain",
        retrieved_text="We present a framework for verifying Bitcoin contracts.",
    )
    rel = classify_source_relevance(
        src,
        topic="Rust borrow-checking behavior",
        query="Rust borrow checker verification",
    )
    assert rel in (RELEVANCE_TANGENTIAL, RELEVANCE_IRRELEVANT)


def test_unrelated_source_is_rejected():
    src = _source(
        title="International organization budget allocation",
        retrieved_text="This paper analyzes fiscal policies and budget transparency.",
    )
    rel = classify_source_relevance(
        src,
        topic="Rust memory safety versus C++",
        query="Rust memory safety versus C++",
    )
    assert rel == RELEVANCE_IRRELEVANT


def test_metadata_only_source_cannot_support_technical_finding():
    src = _source(
        title="A Study of Rust",
        retrieved_text="Published academic work by Example Press: A Study of Rust",
        evidence_depth=DEPTH_METADATA_ONLY,
        relevance=RELEVANCE_DIRECT,
    )
    doc = Document.parse("Rust eliminates data races (Smith, 2024).")
    graph, summary = AcademicVerifier().build_provenance_and_verify(doc, [src])
    assert summary.unsupported_claims >= 1
    assert summary.supported_claims == 0


def test_query_retains_distinctive_topic_terms():
    spec = AssignmentSpec(
        topic="Rust memory safety vs C++",
        outline=["Introduction", "borrow checker", "Conclusion"],
    )
    queries = derive_research_plan(spec)
    joined = " ".join(queries).lower()
    assert "rust" in joined
    assert "c++" in joined
    assert "memory" in joined
    assert "borrow" in joined


def test_overgeneralization_is_rejected():
    source = "Rust prevents some memory errors in systems code."
    claim = Claim(
        id="c1",
        text="Rust always prevents all memory errors in every program.",
        claim_type=ClaimType.FACTUAL,
    )
    assert _claim_escalates_evidence(claim, source) is True


def test_causal_escalation_is_rejected():
    source = "Unsafe code use is associated with higher bug rates."
    claim = Claim(
        id="c1",
        text="Unsafe code causes higher bug rates.",
        claim_type=ClaimType.FACTUAL,
    )
    assert _claim_escalates_evidence(claim, source) is True


def test_abstract_supports_narrow_claim():
    src = _source(
        title="Dynamic authorization in multi-agent systems",
        retrieved_text=(
            "Recent studies demonstrate that dynamic delegated authorization "
            "reduces stale token privileges by 42% across multi-agent environments."
        ),
    )
    doc = Document.parse(
        "Dynamic delegated authorization reduces stale token privileges by 42% (Smith, 2024)."
    )
    graph, summary = AcademicVerifier().build_provenance_and_verify(doc, [src])
    assert summary.supported_claims >= 1
    assert summary.unsupported_claims == 0


def test_abstract_does_not_support_stronger_claim():
    src = _source(
        title="A study of memory safety",
        retrieved_text="Rust may reduce certain memory errors in controlled benchmarks.",
    )
    doc = Document.parse(
        "Rust definitely eliminates all memory errors universally (Smith, 2024)."
    )
    _, summary = AcademicVerifier().build_provenance_and_verify(doc, [src])
    assert summary.unsupported_claims >= 1
