"""Citation verification: bibliographic metadata against authoritative records.

Fixtures are recorded canonical records (tests/fixtures/citations); nothing
here touches the network.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from howlwriter.citations.verification import (
    AUTHOR_MISMATCH,
    AUTHOR_TYPE_MISMATCH,
    DOI_MISMATCH,
    EDITION_MISMATCH,
    PROVIDER_UNAVAILABLE,
    RECORDS_CONFLICT,
    TITLE_MISMATCH,
    YEAR_MISMATCH,
    CitationState,
    ProviderUnavailable,
    RecordFileProvider,
    crossref_message_to_record,
    edition_tokens,
    verify_citation,
    verify_sources,
    worst_state,
)
from howlwriter.domain.source import Source

RECORDS = Path(__file__).parents[1] / "fixtures" / "citations" / "canonical_records.json"


def _src(id_, title, authors, year, doi=None, url=None):
    return Source(id=id_, title=title, authors=authors,
                  publication_date=date(year, 1, 1) if year else None, doi=doi, url=url)


class _Provider:
    """Serves a subset of the recorded file, by provider name."""

    def __init__(self, names):
        self._inner = RecordFileProvider(RECORDS)
        self._names = names
        self.name = "+".join(names)

    def records_for(self, source):
        return [r for r in self._inner._records if r.provider in self._names
                and (r.doi and source.doi and r.doi.lower() == source.doi.lower()
                     or r.url and source.url and r.url == source.url)]


def _records(source, *names):
    return _Provider(list(names)).records_for(source)


def _codes(result):
    return {f.code for f in result.findings}


AI_RMF = dict(id_="S1", title="Artificial intelligence risk management framework (AI RMF 1.0)",
              doi="10.6028/NIST.AI.100-1")
GENAI = dict(id_="S2",
             title="Artificial intelligence risk management framework: Generative artificial intelligence profile",
             doi="10.6028/NIST.AI.600-1")
SP161_UPD = dict(id_="S3",
                 title="Cybersecurity supply chain risk management practices for systems and organizations "
                       "(NIST SP 800-161 Rev. 1 Update 1)",
                 doi="10.6028/NIST.SP.800-161r1-upd1")
SP161_ORIG = dict(id_="S4",
                  title="Cybersecurity supply chain risk management practices for systems and organizations",
                  doi="10.6028/NIST.SP.800-161r1")
OWASP = dict(id_="S5", title="OWASP top 10 for LLM applications 2025", url="https://genai.owasp.org/llm-top-10/")
NIST_ALL = ("nist-publication-page", "nist-document-cover", "crossref")


class TestNistAiRmf:
    def test_individual_author_and_year_verified(self):
        s = _src(authors=["Tabassi, E."], year=2023, **AI_RMF)
        assert verify_citation(s, _records(s, *NIST_ALL)).state == CitationState.VERIFIED

    def test_organizational_author_is_a_mismatch(self):
        s = _src(authors=["National Institute of Standards and Technology"], year=2023, **AI_RMF)
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.MISMATCH
        assert AUTHOR_TYPE_MISMATCH in _codes(r)

    def test_wrong_year_is_a_mismatch(self):
        s = _src(authors=["Tabassi, E."], year=2024, **AI_RMF)
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.MISMATCH and YEAR_MISMATCH in _codes(r)

    def test_wrong_individual_is_a_mismatch(self):
        s = _src(authors=["Boyens, J."], year=2023, **AI_RMF)
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.MISMATCH and AUTHOR_MISMATCH in _codes(r)


class TestGenerativeAiProfile:
    AUTHORS = ["Autio, C.", "Schwartz, R.", "Dunietz, J.", "Jain, S.", "Stanley, M.", "Tabassi, E.",
               "Hall, P.", "Roberts, K."]

    def test_author_list_verified_despite_thin_registry(self):
        s = _src(authors=self.AUTHORS, year=2024, **GENAI)
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.VERIFIED
        # The registry disagrees; the disagreement is reported, not hidden.
        assert RECORDS_CONFLICT in _codes(r)

    def test_organization_matches_registry_but_not_publisher_needs_review(self):
        s = _src(authors=["National Institute of Standards and Technology"], year=2024, **GENAI)
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.NEEDS_REVIEW

    def test_organization_against_publisher_alone_is_a_mismatch(self):
        s = _src(authors=["National Institute of Standards and Technology"], year=2024, **GENAI)
        r = verify_citation(s, _records(s, "nist-publication-page"))
        assert r.state == CitationState.MISMATCH

    def test_truncated_author_list_is_a_mismatch(self):
        s = _src(authors=self.AUTHORS[:3], year=2024, **GENAI)
        r = verify_citation(s, _records(s, "nist-publication-page"))
        assert r.state == CitationState.MISMATCH and AUTHOR_MISMATCH in _codes(r)


class TestRevisionsAndUpdates:
    AUTHORS = ["Boyens, J.", "Smith, A.", "Bartol, N.", "Winkler, K.", "Holbrook, A.", "Fallon, M."]

    def test_update_cited_with_cover_year_is_verified_with_registry_conflict_noted(self):
        s = _src(authors=self.AUTHORS, year=2022, **SP161_UPD)
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.VERIFIED
        assert RECORDS_CONFLICT in _codes(r)

    def test_update_cited_with_registry_year_needs_review(self):
        s = _src(authors=self.AUTHORS, year=2024, **SP161_UPD)
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.NEEDS_REVIEW and YEAR_MISMATCH in _codes(r)

    def test_original_publication_verified(self):
        s = _src(authors=self.AUTHORS, year=2022, **SP161_ORIG)
        assert verify_citation(s, _records(s, "nist-document-cover")).state == CitationState.VERIFIED

    def test_update_title_on_original_doi_is_an_edition_mismatch(self):
        s = _src(authors=self.AUTHORS, year=2022, id_="S4b",
                 title="Cybersecurity supply chain risk management practices for systems and organizations "
                       "(NIST SP 800-161 Rev. 1 Update 1)",
                 doi="10.6028/NIST.SP.800-161r1")
        r = verify_citation(s, _records(s, "nist-document-cover"))
        assert r.state == CitationState.MISMATCH and EDITION_MISMATCH in _codes(r)


class TestOwasp:
    def test_edition_year_title_verified(self):
        s = _src(authors=["OWASP Gen AI Security Project"], year=2025, **OWASP)
        assert verify_citation(s, _records(s, "owasp-project-page")).state == CitationState.VERIFIED

    def test_older_edition_year_is_a_mismatch(self):
        s = _src(authors=["OWASP Gen AI Security Project"], year=2023, **OWASP)
        r = verify_citation(s, _records(s, "owasp-project-page"))
        assert r.state == CitationState.MISMATCH and YEAR_MISMATCH in _codes(r)

    def test_individual_author_for_organizational_work_is_a_mismatch(self):
        s = _src(authors=["Smith, J."], year=2025, **OWASP)
        r = verify_citation(s, _records(s, "owasp-project-page"))
        assert AUTHOR_TYPE_MISMATCH in _codes(r)


class TestOtherStates:
    def test_doi_title_mismatch(self):
        s = _src(authors=["Tabassi, E."], year=2023, id_="S9",
                 title="Zero trust architecture for autonomous agents", doi="10.6028/NIST.AI.100-1")
        r = verify_citation(s, _records(s, *NIST_ALL))
        assert r.state == CitationState.MISMATCH and TITLE_MISMATCH in _codes(r)

    def test_cited_doi_differs_from_record_doi(self):
        s = _src(authors=["Tabassi, E."], year=2023, **AI_RMF)
        rec = _records(s, "nist-publication-page")
        rec[0].doi = "10.6028/NIST.AI.100-2"
        assert DOI_MISMATCH in _codes(verify_citation(s, rec))

    def test_missing_fields_are_incomplete(self):
        s = _src(authors=[], year=None, **AI_RMF)
        assert verify_citation(s, _records(s, *NIST_ALL)).state == CitationState.INCOMPLETE

    def test_no_records_is_unverifiable_not_false(self):
        s = _src(authors=["Tabassi, E."], year=2023, **AI_RMF)
        assert verify_citation(s, []).state == CitationState.UNVERIFIABLE

    def test_network_failure_never_becomes_a_mismatch(self):
        class Down:
            name = "crossref"

            def fetch(self, source):
                raise ProviderUnavailable("timeout")

        s = _src(authors=["Tabassi, E."], year=2023, **AI_RMF)
        (r,) = verify_sources([s], [Down()])
        assert r.state == CitationState.UNVERIFIABLE and PROVIDER_UNAVAILABLE in _codes(r)

    def test_unavailable_provider_does_not_hide_a_confirmed_mismatch(self):
        class Down:
            name = "crossref"

            def fetch(self, source):
                raise ProviderUnavailable("timeout")

        s = _src(authors=["Tabassi, E."], year=2020, **AI_RMF)
        (r,) = verify_sources([s], [Down(), RecordFileProvider(RECORDS)])
        assert r.state == CitationState.MISMATCH

    def test_thin_registry_alone_cannot_verify(self):
        s = _src(authors=["Autio, C."], year=2024, **GENAI)
        r = verify_citation(s, [crossref_message_to_record({"title": ["x"], "DOI": "10.1/x"})])
        assert r.state in (CitationState.NEEDS_REVIEW, CitationState.MISMATCH)
        assert r.state != CitationState.VERIFIED

    def test_worst_state_ordering(self):
        good = _src(authors=["Tabassi, E."], year=2023, **AI_RMF)
        bad = _src(authors=["Tabassi, E."], year=2020, **AI_RMF)
        results = verify_sources([good, bad], [RecordFileProvider(RECORDS)])
        assert worst_state(results) == CitationState.MISMATCH


@pytest.mark.parametrize("text,doi,expected", [
    ("AI RMF 1.0", "10.6028/NIST.AI.100-1", {"1.0"}),
    ("SP 800-161 Rev. 1 Update 1", "", {"rev1", "update1"}),
    ("", "10.6028/NIST.SP.800-161r1-upd1", {"rev1", "update1"}),
    ("", "10.6028/NIST.AI.600-1", set()),
])
def test_edition_tokens_ignore_doi_prefix(text, doi, expected):
    assert edition_tokens(text, doi=doi) == expected
