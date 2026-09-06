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


def test_identifier_warnings_populate_verification_summary():
    s1 = Source(
        id="S001",
        title="Cloud Threat Detection Overview",
        authors=["Rivera, Ana"],
        publication_date=date(2024, 6, 1),
        access_date=date.today(),
        retrieved_text=(
            "AWS GuardDuty and SIEM detections can flag anomalous credential use "
            "and unusual API activity tied to compromised access keys."
        ),
    )

    # The draft invents a suspiciously precise jitter figure not present in
    # any retrieved source or the assignment's own text.
    doc_text = """# Beaconing Behavior

The malware exhibited beacon traffic with 34.72% jitter to evade detection,
consistent with AWS GuardDuty telemetry for anomalous credential use.
"""
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    _, summary = verifier.build_provenance_and_verify(doc, [s1])

    assert len(summary.identifier_warnings) >= 1
    assert any("34.72" in w for w in summary.identifier_warnings)
    assert summary.status == "NEEDS_REVIEW"


def test_identifier_grounded_via_additional_grounding_texts_not_flagged():
    doc_text = "The lab specifically analyzes CVE-2024-31337 as a case study."
    doc = Document.parse(doc_text)
    verifier = AcademicVerifier()
    _, summary = verifier.build_provenance_and_verify(
        doc,
        sources=[],
        additional_grounding_texts=["Analyze CVE-2024-31337 as the primary case study."],
    )

    assert not any("CVE-2024-31337" in w for w in summary.identifier_warnings)


def _latency_source() -> Source:
    return Source(
        id="S001",
        title="Latency Study",
        authors=["Rose, Scott"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=(
            "Our controlled deployment of mutual TLS across the service mesh "
            "reduced observed lateral movement incidents by 41 percent while "
            "adding 12 milliseconds of median request latency in Kubernetes "
            "clusters."
        ),
        evidence_depth="ABSTRACT",
        relevance="DIRECT",
    )


def test_statistic_absent_from_the_source_is_not_supported_by_it():
    """Topical overlap matched a source; the figure must come from it too."""
    doc = Document.parse(
        "# Paper\n\nMutual TLS reduced lateral movement incidents by 63 "
        "percent in Kubernetes clusters (Rose, 2024).\n"
    )

    _, summary = AcademicVerifier().build_provenance_and_verify(
        doc, [_latency_source()]
    )

    assert summary.supported_claims == 0
    assert summary.unsupported_claims == 1


def test_statistic_present_in_the_source_remains_supported():
    doc = Document.parse(
        "# Paper\n\nMutual TLS reduced lateral movement incidents by 41 "
        "percent in Kubernetes clusters (Rose, 2024).\n"
    )

    _, summary = AcademicVerifier().build_provenance_and_verify(
        doc, [_latency_source()]
    )

    assert summary.supported_claims == 1
    assert summary.unsupported_claims == 0


def test_claim_without_a_figure_is_unaffected_by_quantity_grounding():
    doc = Document.parse(
        "# Paper\n\nMutual TLS reduced observed lateral movement incidents "
        "across Kubernetes clusters (Rose, 2024).\n"
    )

    _, summary = AcademicVerifier().build_provenance_and_verify(
        doc, [_latency_source()]
    )

    assert summary.supported_claims == 1
