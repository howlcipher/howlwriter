"""Tests for APA 7 citation analysis and references attachment."""

from datetime import date

from howlwriter.academic.citations import AcademicCitationManager
from howlwriter.domain.document import Document
from howlwriter.domain.source import Source, SourceType


def test_in_text_citation_and_references_generation():
    s1 = Source(
        id="S001",
        title="Zero Trust Architecture",
        authors=["Rose, Scott", "Borchert, Oliver"],
        publication_date=date(2020, 8, 1),
        publisher="National Institute of Standards and Technology",
        doi="10.6028/NIST.SP.800-207",
        access_date=date.today(),
        source_type=SourceType.REPORT,
    )
    s2 = Source(
        id="S002",
        title="Autonomous AI Agent Security",
        authors=["Ahmadi, Sina"],
        publication_date=date(2025, 2, 10),
        publisher="IEEE Computer Society",
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
    )
    s3 = Source(
        id="S003",
        title="Uncited Source In Bibliography",
        authors=["Uncited, Author"],
        publication_date=date(2023, 1, 1),
        access_date=date.today(),
    )

    doc_text = """# Security Architecture

Zero trust assumes no implicit trust based solely on network location (Rose & Borchert, 2020).
Recent studies demonstrate that dynamic delegated authorization reduces stale privileges (Ahmadi, 2025).
"""
    doc = Document.parse(doc_text)
    mgr = AcademicCitationManager()
    analysis = mgr.analyze_and_build_references(doc, [s1, s2, s3])

    assert analysis.in_text_citation_count >= 2
    assert len(analysis.used_sources) == 2
    assert s1 in analysis.used_sources
    assert s2 in analysis.used_sources
    assert s3 not in analysis.used_sources

    # Check References Section
    assert "# References" in analysis.references_section_text
    assert "Rose, S., & Borchert, O. (2020). Zero trust architecture." in analysis.references_section_text
    assert "Ahmadi, S. (2025). Autonomous AI agent security." in analysis.references_section_text
    assert "Uncited, A." not in analysis.references_section_text

    # Attach References to document
    final_doc = mgr.attach_references(doc, analysis)
    assert "# References" in final_doc.text
    assert "Rose, S., & Borchert, O." in final_doc.text


def _resolvable_source_set() -> list[Source]:
    return [
        Source(
            id="S001",
            title="Zero Trust Architecture",
            authors=["Rose, Scott", "Borchert, Oliver"],
            publication_date=date(2020, 8, 1),
            publisher="National Institute of Standards and Technology",
            access_date=date.today(),
            source_type=SourceType.REPORT,
        ),
        Source(
            id="S002",
            title="Autonomous AI Agent Security",
            authors=["Ahmadi, Sina"],
            publication_date=date(2025, 2, 10),
            publisher="IEEE Computer Society",
            access_date=date.today(),
            source_type=SourceType.JOURNAL_ARTICLE,
        ),
    ]


def test_fabricated_in_text_citations_are_reported_as_unresolved():
    """A citation that matches no collected source must never pass silently."""
    doc = Document.parse(
        """# Paper

Zero trust assumes no implicit trust (Rose & Borchert, 2020).
A study found mTLS cuts lateral movement by 90% (Fenwick & Alvarez, 2019).
Later work confirms this across clusters (Nakamura et al., 2021).
As Braithwaite (2020) demonstrated, attestation is cheap.
"""
    )
    analysis = AcademicCitationManager().analyze_and_build_references(
        doc, _resolvable_source_set()
    )

    assert analysis.unmatched_in_text_citations == [
        "Fenwick & Alvarez, 2019",
        "Nakamura et al., 2021",
        "Braithwaite (2020)",
    ]
    unresolved = [w for w in analysis.warnings if w.code == "CITATION_UNRESOLVED"]
    assert len(unresolved) == 3
    assert "Fenwick & Alvarez, 2019" in unresolved[0].message
    # The fabricated works must not be smuggled into the References page.
    assert "Fenwick" not in analysis.references_section_text
    assert "Braithwaite" not in analysis.references_section_text


def test_resolvable_citations_produce_no_unresolved_warnings():
    """Every citation resolving to a source must yield zero false positives."""
    doc = Document.parse(
        """# Paper

Zero trust assumes no implicit trust (Rose & Borchert, 2020).
Delegated authorization reduces stale privileges (Ahmadi, 2025).
Ahmadi (2025) also measured the revocation latency.
"""
    )
    analysis = AcademicCitationManager().analyze_and_build_references(
        doc, _resolvable_source_set()
    )

    assert analysis.unmatched_in_text_citations == []
    assert [w for w in analysis.warnings if w.code == "CITATION_UNRESOLVED"] == []


def test_repeated_fabricated_citation_is_reported_once():
    doc = Document.parse(
        """# Paper

First mention (Fenwick & Alvarez, 2019).
Second mention of the same work (Fenwick & Alvarez, 2019).
"""
    )
    analysis = AcademicCitationManager().analyze_and_build_references(
        doc, _resolvable_source_set()
    )

    assert analysis.unmatched_in_text_citations == ["Fenwick & Alvarez, 2019"]


def test_unresolved_citation_wrong_year_does_not_resolve_to_right_author():
    """A real author with a year no collected source carries is still unresolved."""
    doc = Document.parse("# Paper\n\nA claim attributed to (Ahmadi, 2019).\n")
    analysis = AcademicCitationManager().analyze_and_build_references(
        doc, _resolvable_source_set()
    )

    assert analysis.unmatched_in_text_citations == ["Ahmadi, 2019"]
