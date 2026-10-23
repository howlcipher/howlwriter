"""Cross-document consistency: one work, one set of metadata across the bundle."""

from __future__ import annotations

from howlwriter.citations.registry import (
    CROSS_DOC_AUTHOR_CONFLICT,
    CROSS_DOC_DOI_CONFLICT,
    CROSS_DOC_YEAR_CONFLICT,
    DISAGREES_WITH_RECORD,
    build_registry,
)
from howlwriter.citations.verification import RecordFileProvider, verify_sources
from howlwriter.domain.source import Source
from tests.citations.test_verification import RECORDS

UPD = "https://doi.org/10.6028/NIST.SP.800-161r1-upd1"
ORIG = "https://doi.org/10.6028/NIST.SP.800-161r1"
TITLE = "*Cybersecurity supply chain risk management practices for systems and organizations*"


def _doc(entry):
    return "Body text with a citation (Boyens et al., 2022).\n\n**References**\n\n" + entry + "\n"


def _ref(year, doi=UPD, lead="Boyens, J., Smith, A., & Fallon, M.", title=TITLE):
    return f"{lead} ({year}). {title}. National Institute of Standards and Technology. {doi}"


def _codes(registry):
    return [f.code for f in registry.conflicts()]


def test_documents_that_agree_have_no_conflicts():
    registry = build_registry({"main": _doc(_ref(2022)), "reply-1": _doc(_ref(2022)), "reply-2": _doc(_ref(2022))})
    assert registry.conflicts() == []
    assert registry.entries[0].documents == ["main", "reply-1", "reply-2"]


def test_citation_fixed_in_one_document_but_not_another_is_found():
    registry = build_registry({"main": _doc(_ref(2024)), "reply-1": _doc(_ref(2022)), "reply-2": _doc(_ref(2022))})
    (finding,) = registry.conflicts()
    assert finding.code == CROSS_DOC_YEAR_CONFLICT
    assert finding.documents == ["main", "reply-1", "reply-2"]
    assert "2024 in main" in finding.message and "2022 in reply-1, reply-2" in finding.message


def test_original_and_updated_editions_are_distinct_works_not_a_conflict():
    registry = build_registry({"main": _doc(_ref(2022, doi=ORIG)), "reply-1": _doc(_ref(2022, doi=UPD))})
    assert registry.conflicts() == []
    assert len(registry.entries) == 2


def test_different_lead_author_for_the_same_doi_is_a_conflict():
    registry = build_registry({"main": _doc(_ref(2022)), "reply-1": _doc(_ref(2022, lead="National Institute of Standards and Technology"))})
    assert CROSS_DOC_AUTHOR_CONFLICT in _codes(registry)


def test_two_dois_for_one_edition_is_flagged():
    registry = build_registry({"main": _doc(_ref(2022, doi=UPD)),
                               "reply-1": _doc(_ref(2022, doi="https://doi.org/10.6028/NIST.SP.800-161r1-upd1x"))})
    assert CROSS_DOC_DOI_CONFLICT in _codes(registry)


def test_documents_without_a_doi_match_by_lead_and_title_and_conflicting_years_are_reported():
    # Same lead and title, no identifier that could mark them as different editions.
    registry = build_registry({"main": _doc(_ref(2022, doi="https://example.org/a")),
                               "reply-1": _doc(_ref(2024, doi=""))})
    assert CROSS_DOC_YEAR_CONFLICT in _codes(registry)


def test_different_titles_by_the_same_lead_are_different_works():
    other = _ref(2024, doi="", title="*Zero trust architecture for supplier networks*")
    registry = build_registry({"main": _doc(_ref(2022, doi="https://example.org/a")), "reply-1": _doc(other)})
    assert registry.conflicts() == []


def test_verified_record_flags_the_documents_that_disagree_with_it():
    registry = build_registry({"main": _doc(_ref(2024)), "reply-1": _doc(_ref(2022))})
    source = Source(id="S", title="Cybersecurity supply chain risk management practices for systems and organizations",
                    authors=["Boyens, J.", "Smith, A.", "Bartol, N.", "Winkler, K.", "Holbrook, A.", "Fallon, M."],
                    doi="10.6028/NIST.SP.800-161r1-upd1")
    source.freshness.document_identifier = "NIST SP 800-161r1-upd1"
    source.publication_date = __import__("datetime").date(2022, 1, 1)
    verifications = verify_sources([source], [RecordFileProvider(RECORDS)])
    findings = registry.apply_verifications(verifications)
    assert [f.code for f in findings] == [DISAGREES_WITH_RECORD]
    assert findings[0].documents == ["main"]  # only the document that disagrees
    entry = registry.entries[0]
    assert entry.resolved["year"]["basis"] == "cite_as"


def test_documents_citing_lists_everything_affected_by_a_correction():
    registry = build_registry({"main": _doc(_ref(2022)), "reply-1": _doc(_ref(2022)), "other": "No references here."})
    assert registry.documents_citing(registry.entries[0].key) == ["main", "reply-1"]


def test_registry_never_modifies_documents():
    docs = {"main": _doc(_ref(2024)), "reply-1": _doc(_ref(2022))}
    snapshot = dict(docs)
    build_registry(docs).conflicts()
    assert docs == snapshot


class TestAuditRegressions:
    def test_doi_in_one_document_and_none_in_another_are_one_work(self):
        a = _doc(_ref(2022, doi="https://doi.org/10.6028/abc.1"))
        b = _doc(_ref(2024, doi=""))
        registry = build_registry({"a": a, "b": b})
        assert len(registry.entries) == 1 and CROSS_DOC_YEAR_CONFLICT in _codes(registry)

    def test_same_title_with_different_dois_is_flagged_even_when_the_years_differ(self):
        registry = build_registry({"a": _doc(_ref(2022, doi="https://doi.org/10.1234/a")),
                                   "b": _doc(_ref(2024, doi="https://doi.org/10.1234/b"))})
        assert CROSS_DOC_DOI_CONFLICT in _codes(registry)

    def test_different_edition_ordinals_are_different_works(self):
        a = _doc(_ref(2020, doi="", title="*Statistics handbook, 2nd edition*"))
        b = _doc(_ref(2023, doi="", title="*Statistics handbook, 3rd edition*"))
        registry = build_registry({"a": a, "b": b})
        assert len(registry.entries) == 2 and registry.conflicts() == []
