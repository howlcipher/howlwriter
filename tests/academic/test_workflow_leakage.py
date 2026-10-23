"""The academic pipeline holds a paper whose prose contains workflow commentary."""

from datetime import date

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.config.defaults import default_config
from howlwriter.domain.source import Source, SourceType
from src.control_plane.agent_execution import FakeAgentBackend

_SOURCE = Source(
    id="S001",
    title="Zero Trust Governance for Autonomous AI Agents",
    authors=["Oladimeji, Ganiyu"],
    publication_date=date(2025, 3, 1),
    publisher="Elsevier BV",
    doi="10.2139/ssrn.7194038",
    access_date=date.today(),
    source_type=SourceType.JOURNAL_ARTICLE,
    retrieved_text=(
        "Autonomous AI agents represent an emerging paradigm in distributed computing. "
        "Dynamic delegated authorization reduces stale token privileges by 42% in multi-agent systems."
    ),
)

_REPLY = """```yaml
body_markdown: |
  # Zero Trust and Autonomous AI Agents

  ## Introduction
  Autonomous AI agents represent an emerging paradigm in distributed computing (Oladimeji, 2025).

  ## Identity Challenges
  Dynamic delegated authorization reduces stale token privileges by 42% (Oladimeji, 2025).

  ## Conclusion
  {conclusion}
claims_made:
  - claim: "Dynamic delegated authorization reduces stale token privileges by 42%"
    source_id: "S001"
verdict: "PASS"
differences: []
rationale: "Rigorous factual alignment."
warnings: []
```"""


def _run(tmp_path, monkeypatch, conclusion):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))
    spec = AssignmentSpec(
        title="Zero Trust and Autonomous AI Agents",
        topic="Examine how autonomous AI agents complicate identity, authorization, and access control.",
        target_words=50,
        word_tolerance_percent=30.0,
        outline=["Introduction", "Identity Challenges", "Conclusion"],
        source_requirements=dict(minimum_sources=1),
    )
    backend = FakeAgentBackend(agent_id="fake_leak_backend", default_stdout=_REPLY.format(conclusion=conclusion))
    return run_academic_pipeline(spec, default_config(), existing_sources=[_SOURCE], custom_backend=backend)


def test_provenance_note_in_prose_holds_the_paper(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch,
                  "Delegated authorization is the stronger control. This is my recommendation, not a cited result.")
    assert result.report.workflow_leakage_findings == 1
    assert result.report.status == "NEEDS_REVIEW"


def test_clean_prose_reports_zero_and_stays_ready(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, "Delegated authorization is the stronger control.")
    assert result.report.workflow_leakage_findings == 0
    assert result.report.status == "READY"


def test_a_real_limitation_is_not_treated_as_leakage(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch,
                  "The evidence covers multi-agent systems only, so single-agent deployments remain untested.")
    assert result.report.workflow_leakage_findings == 0


def test_verify_sources_compares_citation_metadata_with_authoritative_records(tmp_path, monkeypatch):
    """A resolving DOI is not enough: the year must agree with the records."""
    from howlwriter.citations.verification import CanonicalAuthor, CanonicalRecord

    class Records:
        name = "records"

        def __init__(self, year):
            self.year = year

        def fetch(self, source):
            return CanonicalRecord(
                provider="publisher-page", authority="publisher", title=source.title,
                authors=[CanonicalAuthor(family="Oladimeji", given="Ganiyu")], year=self.year,
                year_source="cite_as", doi=source.doi)

    def run(year):
        monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))
        spec = AssignmentSpec(
            title="Zero Trust and Autonomous AI Agents", topic="Examine identity for autonomous agents.",
            target_words=50, word_tolerance_percent=30.0, outline=["Introduction", "Identity Challenges", "Conclusion"],
            source_requirements=dict(minimum_sources=1))
        backend = FakeAgentBackend(agent_id="fake_meta_backend",
                                   default_stdout=_REPLY.format(conclusion="Delegated authorization is the stronger control."))
        import httpx

        from howlwriter.research.integrity import SourceIntegrityVerifier

        def crossref(request):
            # A DOI that resolves and carries the right title: reachability is fine; only metadata can differ.
            return httpx.Response(200, json={"message": {"title": [_SOURCE.title], "DOI": _SOURCE.doi}})

        offline = SourceIntegrityVerifier(mock_transport=httpx.MockTransport(crossref))
        return run_academic_pipeline(spec, default_config(), existing_sources=[_SOURCE], custom_backend=backend,
                                     verify_sources=True, citation_providers=[Records(year)],
                                     integrity_verifier=offline)

    ok = run(2025)
    assert ok.report.citation_metadata_status == "VERIFIED" and ok.report.status == "READY"
    wrong = run(2023)
    assert wrong.report.citation_metadata_status == "MISMATCH" and wrong.report.status == "BLOCKED"
    assert "MISMATCH" in wrong.report.render_text() if hasattr(wrong.report, "render_text") else True


def test_without_verify_sources_citation_metadata_is_reported_as_not_checked(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, "Delegated authorization is the stronger control.")
    assert result.report.citation_metadata_status is None
