"""End-to-end hermetic pipeline and CLI tests for academic paper workflows."""

from datetime import date

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.cli.main import main
from howlwriter.config.defaults import default_config
from howlwriter.domain.source import Source, SourceType
from src.control_plane.agent_execution import FakeAgentBackend


def test_end_to_end_academic_pipeline_ready_status(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    s1 = Source(
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
    s2 = Source(
        id="S002",
        title="Autonomous Identity-Based Threat Segmentation",
        authors=["Ahmadi, Sina"],
        publication_date=date(2025, 2, 1),
        publisher="Center for Open Science",
        doi="10.31219/osf.io/hpcq7_v1",
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text=(
            "Identity-based microsegmentation prevents horizontal privilege escalation "
            "across autonomous agent clusters."
        ),
    )

    spec = AssignmentSpec(
        title="Zero Trust and Autonomous AI Agents",
        topic=(
            "Examine how autonomous AI agents complicate identity, "
            "authorization, and access control in enterprise environments."
        ),
        target_words=50,
        word_tolerance_percent=30.0,
        outline=["Introduction", "Identity Challenges", "Conclusion"],
        source_requirements=dict(minimum_sources=2),
    )

    fake_backend = FakeAgentBackend(
        agent_id="fake_academic_backend",
        default_stdout="""```yaml
body_markdown: |
  # Zero Trust and Autonomous AI Agents

  ## Introduction
  Autonomous AI agents represent an emerging paradigm in distributed computing (Oladimeji, 2025).

  ## Identity Challenges
  Dynamic delegated authorization reduces stale token privileges by 42% (Oladimeji, 2025).
  Identity-based microsegmentation prevents privilege escalation (Ahmadi, 2025).

  ## Conclusion
  Cryptographic zero-trust policies ensure verifiable posture.
claims_made:
  - claim: "Dynamic delegated authorization reduces stale token privileges by 42%"
    source_id: "S001"
  - claim: "Identity-based microsegmentation prevents horizontal privilege escalation"
    source_id: "S002"
verdict: "PASS"
differences: []
rationale: "Rigorous factual alignment."
warnings: []
```""",
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[s1, s2],
        custom_backend=fake_backend,
    )

    assert result.report.status == "READY"
    assert result.report.target_words == 50
    assert result.report.word_count_status == "PASS"
    assert result.report.outline_status == "PASS"
    assert result.report.sources_used == 2
    assert result.report.unsupported_claims == 0
    assert "# References" in result.final_document.text
    assert "Oladimeji, G." in result.final_document.text
    assert "Ahmadi, S." in result.final_document.text


def test_pipeline_needs_review_when_requirements_uncovered(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    s1 = Source(
        id="S001",
        title="Cloud Credential Exposure Patterns",
        authors=["Rivera, Ana"],
        publication_date=date(2025, 1, 1),
        access_date=date.today(),
        source_type=SourceType.JOURNAL_ARTICLE,
        retrieved_text="Leaked long-lived credentials remain a common initial access vector.",
    )

    spec = AssignmentSpec(
        title="Cloud Credential Exposure",
        topic="Analyze leaked cloud credential exposure as an initial access vector.",
        target_words=50,
        word_tolerance_percent=30.0,
        outline=["Introduction", "Conclusion"],
        requirements=["Include specific defensive telemetry and detection queries for each stage"],
        source_requirements=dict(minimum_sources=1),
    )

    # The draft's body never mentions telemetry/detection at all, so the new
    # requirements-coverage checker should fail this requirement even though
    # the outline itself is fully satisfied.
    fake_backend = FakeAgentBackend(
        agent_id="fake_academic_backend",
        default_stdout="""```yaml
body_markdown: |
  # Cloud Credential Exposure

  ## Introduction
  Leaked long-lived credentials remain a common initial access vector (Rivera, 2025).

  ## Conclusion
  Organizations should rotate credentials regularly.
claims_made: []
verdict: "PASS"
differences: []
rationale: "No meaning drift."
warnings: []
```""",
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[s1],
        custom_backend=fake_backend,
    )

    assert result.coverage_result.status == "FAIL"
    assert result.report.requirements_coverage_status == "FAIL"
    assert result.report.status == "NEEDS_REVIEW"


def test_pipeline_deterministic_only_omits_consistency_status(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = AssignmentSpec(
        title="Deterministic Fallback Paper",
        topic="A topic drafted without any model backend available.",
        target_words=50,
        word_tolerance_percent=50.0,
        outline=["Introduction", "Conclusion"],
        source_requirements=dict(minimum_sources=0),
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[],
        deterministic_only=True,
    )

    # No model was available, so the consistency reviewer must never have
    # fabricated a verdict -- the field stays None, exactly like
    # semantic_meaning_status does when FINAL_REVIEWER isn't configured.
    assert result.consistency_review_result is None
    assert result.report.consistency_review_status is None


def test_cli_paper_command_execution(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    assignment_file = tmp_path / "assignment.yaml"
    assignment_file.write_text("""
title: Enterprise AI Governance
topic: Security controls for enterprise LLM agents.
target_words: 100
word_tolerance_percent: 20
outline:
  - Introduction
  - Governance Controls
  - Conclusion
source_requirements:
  minimum_sources: 1
""")

    out_file = tmp_path / "governance_paper.md"

    # Deterministic mode runs cleanly without needing live model providers
    exit_code = main([
        "paper",
        str(assignment_file),
        "--out",
        str(out_file),
        "--deterministic",
        "--save-artifacts",
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert out_file.exists()
    assert "# Enterprise AI Governance" in out_file.read_text()
    assert "# References" in out_file.read_text()
    assert "HOWLWRITER ACADEMIC REPORT" in captured.out
    assert (tmp_path / "governance_paper.sources.json").exists()
