from datetime import date

from howlwriter.academic.verifier import AcademicVerifier
from howlwriter.domain.document import Document
from howlwriter.domain.source import Source, SourceType


def test_provenance_and_supported_claim_mapping():
    s1 = Source(
        id="S001",
        title="Zero Trust Governance for Autonomous AI Agents",
        authors=["Oladimeji, Ganiyu"],
        publication_date=date(2025, 3, 15),
        publisher="Elsevier",
        doi="10.2139/ssrn.7194038",
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=(
            "Recent studies demonstrate that dynamic delegated authorization "
            "reduces stale token privileges by 42% across multi-agent environments."
        ),
    )

    doc_text = """# Zero Trust Systems

Dynamic delegated authorization reduces stale token privileges by 42% (Oladimeji, 2025).
"""
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(doc, [s1])

    assert len(graph.sources) == 1
    assert "S001" in graph.sources
    assert summary.supported_claims >= 1
    assert summary.unsupported_claims == 0
    assert summary.status == "PASS"

    # Evidence links claim to source
    assert len(graph.evidence) >= 1
    ev = graph.evidence[0]
    assert ev.source_id == "S001"
    assert ev.supports is True


def test_unsupported_claim_demotes_readiness():
    s1 = Source(
        id="S001",
        title="General AI Security",
        authors=["Smith, Alice"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="AI systems require basic credential isolation and token rotation.",
    )

    # Document asserts a fabricated statistical metric completely absent from the source
    doc_text = """# Security Claims

A benchmark across 950 Fortune 500 banks demonstrated an 89.4% reduction in data breaches during 2026.
"""
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    graph, summary = verifier.build_provenance_and_verify(doc, [s1])

    assert summary.unsupported_claims >= 1
    assert summary.status == "NEEDS_REVIEW"


def test_quotation_integrity_checks():
    s1 = Source(
        id="S001",
        title="Foundations of Computer Security",
        authors=["Dijkstra, Edsger"],
        publication_date=date(1982, 5, 1),
        access_date=date.today(),
        retrieved_text=(
            "Simplicity is a great virtue but it requires hard work to achieve it "
            "and education to appreciate it."
        ),
    )

    # Case 1: Real verbatim quote from source
    quote1 = (
        'As Dijkstra noted, "Simplicity is a great virtue but it requires hard work '
        'to achieve it and education to appreciate it."'
    )
    doc1 = Document.parse(quote1)
    _, summary1 = AcademicVerifier().build_provenance_and_verify(doc1, [s1])
    assert len(summary1.quotation_warnings) == 0

    # Case 2: Fabricated quote not in source
    quote2 = (
        'Dijkstra stated, "Autonomous AI agents will inevitably destroy traditional network '
        'perimeters by 2026 without cryptographic zero trust."'
    )
    doc2 = Document.parse(quote2)
    _, summary2 = AcademicVerifier().build_provenance_and_verify(doc2, [s1])
    assert len(summary2.quotation_warnings) == 1
    assert "was not found verbatim in any retrieved source" in summary2.quotation_warnings[0]
    assert summary2.status == "NEEDS_REVIEW"
