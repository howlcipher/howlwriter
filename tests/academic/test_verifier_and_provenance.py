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


def _study_source(text: str) -> Source:
    return Source(
        id="S001",
        title="Study",
        authors=["Rose, Scott"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=text,
        evidence_depth="ABSTRACT",
        relevance="DIRECT",
    )


_SUBJECT = (
    "insider breaches across enterprise Kubernetes clusters under mutual TLS "
    "deployment"
)


def _supported(claim: str, source_text: str) -> bool:
    _, summary = AcademicVerifier().build_provenance_and_verify(
        Document.parse(f"# P\n\n{claim}\n"), [_study_source(source_text)]
    )
    return summary.supported_claims == 1


def test_rounded_claim_is_supported_by_a_more_precise_source():
    """A source reporting 41.2% supports a paper that rounds it to 41%."""
    assert _supported(
        f"Roughly 41% of {_SUBJECT} failed authentication (Rose, 2024).",
        f"In our trial, 41.2% of {_SUBJECT} failed authentication.",
    )


def test_decimal_rate_in_source_supports_a_percentage_claim():
    assert _supported(
        f"The model had a 5% false positive rate for {_SUBJECT} (Rose, 2024).",
        f"The false positive rate was 0.05 for {_SUBJECT}.",
    )


def test_thousands_separator_does_not_break_matching():
    assert _supported(
        f"Throughput for {_SUBJECT} scaled by 1200% (Rose, 2024).",
        f"Throughput for {_SUBJECT} scaled by 1,200%.",
    )


def test_reference_marker_does_not_ground_a_percentage():
    """"[41]" is a citation marker, not a measurement of 41 percent."""
    assert not _supported(
        f"Our analysis revealed a 41 percent drop in {_SUBJECT} (Rose, 2024).",
        f"Prior threat models for {_SUBJECT} assume perimeter defenses [41].",
    )


def test_section_number_does_not_ground_a_percentage():
    assert not _supported(
        f"Failure rates for {_SUBJECT} stabilized at 4.1 percent (Rose, 2024).",
        f"As detailed in Section 4.1, {_SUBJECT} were distributed evenly.",
    )


def test_same_number_in_a_different_unit_does_not_ground_a_percentage():
    assert not _supported(
        f"mTLS produced a 41 percent drop in latency for {_SUBJECT} (Rose, 2024).",
        f"Average ping time for {_SUBJECT} settled at 41 milliseconds.",
    )


def test_leading_decimal_percentage_is_still_checked():
    assert not _supported(
        f"False rejections for {_SUBJECT} dropped by .5% (Rose, 2024).",
        f"False rejections for {_SUBJECT} decreased slightly.",
    )


_TWO_TRENDS = (
    "Security enforcement increased deployment velocity across enterprise "
    "Kubernetes clusters by 15 percent. Separately, incident counts decreased "
    "by 40 percent."
)
_VELOCITY = (
    "deployment velocity across enterprise Kubernetes clusters under security "
    "enforcement"
)


def _supported_against(claim: str, source_text: str) -> bool:
    source = _study_source(source_text)
    source.authors = ["Alvarez, Nina"]
    _, summary = AcademicVerifier().build_provenance_and_verify(
        Document.parse(f"# P\n\n{claim}\n"), [source]
    )
    return summary.supported_claims == 1


def test_claim_reversing_its_source_is_not_supported():
    """The figure and the topic match; the claim says the opposite happened."""
    assert not _supported_against(
        f"Security enforcement decreased {_VELOCITY} by 15 percent "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_claim_agreeing_with_its_source_stays_supported():
    assert _supported_against(
        f"Security enforcement increased {_VELOCITY} by 15 percent "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_direction_is_bound_to_the_sentence_reporting_the_same_figure():
    """A different trend elsewhere in the abstract must not manufacture a
    disagreement, nor excuse a real one."""
    assert _supported_against(
        f"Incident counts decreased by 40 percent for {_VELOCITY} "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )
    assert not _supported_against(
        f"Incident counts increased by 40 percent for {_VELOCITY} "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_claim_without_a_direction_word_is_not_judged_on_direction():
    assert _supported_against(
        f"Security enforcement shifted {_VELOCITY} by 15 percent "
        "(Alvarez, 2024).",
        _TWO_TRENDS,
    )


def test_author_surname_is_not_read_as_a_direction_word():
    """"(Rose, 2024)" must not make a claim read as "rose"."""
    source = _study_source(
        f"Security enforcement reduced {_VELOCITY} by 15 percent."
    )
    _, summary = AcademicVerifier().build_provenance_and_verify(
        Document.parse(
            f"# P\n\nSecurity enforcement reduced {_VELOCITY} by 15 percent "
            "(Rose, 2024).\n"
        ),
        [source],
    )
    assert summary.supported_claims == 1
