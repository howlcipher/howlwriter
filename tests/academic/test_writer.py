"""Tests for ModelAcademicWriter and length correction passes."""

from datetime import date

from howlwriter.academic.spec import AssignmentSpec
from howlwriter.academic.writer import ModelAcademicWriter
from howlwriter.domain.source import Source, SourceType
from src.control_plane.agent_execution import FakeAgentBackend


def test_model_academic_writer_drafts_paper_with_sources(tmp_path):
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
            "Dynamic delegated authorization reduces stale token privileges "
            "by 42% in multi-agent systems."
        ),
    )

    spec = AssignmentSpec(
        title="Zero Trust and Autonomous AI Agents",
        topic=(
            "Examine how autonomous AI agents complicate identity, authorization, "
            "and access control in enterprise environments."
        ),
        target_words=100,
        word_tolerance_percent=20.0,
        outline=["Introduction", "Identity Challenges", "Conclusion"],
    )

    fake_backend = FakeAgentBackend(
        agent_id="fake_writer",
        default_stdout="""```yaml
body_markdown: |
  # Zero Trust and Autonomous AI Agents

  ## Introduction
  Autonomous AI agents represent an emerging paradigm (Oladimeji, 2025).

  ## Identity Challenges
  Dynamic delegated authorization reduces stale token privileges by 42% (Oladimeji, 2025).

  ## Conclusion
  Cryptographic zero-trust policies ensure verifiable posture.
claims_made:
  - claim: "Dynamic delegated authorization reduces stale token privileges by 42%"
    source_id: "S001"
added_claims:
  - claim: "Dynamic delegated authorization reduces stale token privileges by 42%"
    source_id: "S001"
    basis: "retrieved evidence selected during expansion"
word_count_estimate: 45
warnings: []
```""",
    )

    writer = ModelAcademicWriter()
    res = writer.draft_paper(spec, [s1], custom_backend=fake_backend)

    assert res.document.title == "Zero Trust and Autonomous AI Agents"
    assert "## Introduction" in res.document.text
    assert "## Identity Challenges" in res.document.text
    assert "(Oladimeji, 2025)" in res.document.text
    assert res.word_count > 0
    assert len(res.claims_stated) == 1
    assert len(res.added_claims) == 1
    assert res.added_claims[0]["basis"] == "retrieved evidence selected during expansion"


def test_length_correction_pass():
    spec = AssignmentSpec(
        title="Short Paper",
        topic="Short topic",
        target_words=200,
    )
    from howlwriter.domain.document import Document

    initial_doc = Document.parse("# Short Paper\n\nToo short text.")

    fake_backend = FakeAgentBackend(
        agent_id="fake_writer",
        default_stdout="""```yaml
body_markdown: |
  # Short Paper

  ## Section 1
  Expanded substantive academic text addressing the research questions with rigorous depth.

  ## Section 2
  Further discussion of structural controls and enterprise implementation strategies.
word_count_estimate: 25
```""",
    )

    writer = ModelAcademicWriter()
    res = writer.correct_length(
        initial_doc,
        spec,
        sources=[],
        direction="EXPAND",
        current_words=5,
        custom_backend=fake_backend,
    )
    assert "Expanded substantive academic text" in res.document.text
    assert res.word_count > 5


def test_writer_salvages_a_reply_whose_yaml_does_not_parse():
    spec = AssignmentSpec(title="Backups", topic="Why backups matter", target_words=40)
    backend = FakeAgentBackend(
        agent_id="fake_writer",
        default_stdout=(
            "```yaml\nbody_markdown: |\n  # Backups\n\nBackups protect data.\n"
            "claims_made:\n  - claim: \"Backups protect data.\"\n    source_id: \"\"\nwarnings: []\n```"
        ),
    )
    res = ModelAcademicWriter().draft_paper(spec, [], custom_backend=backend)

    assert res.document.text.startswith("# Backups")
    assert "claims_made" not in res.document.text and "```" not in res.document.text
    assert res.claims_stated == [{"claim": "Backups protect data.", "source_id": ""}]


def test_writer_without_sources_forbids_citations_instead_of_asking_for_them():
    spec = AssignmentSpec(title="Backups", topic="Why backups matter", target_words=40)
    backend = FakeAgentBackend(agent_id="fake_writer", default_stdout="Backups protect data.")
    ModelAcademicWriter().draft_paper(spec, [], custom_backend=backend)

    prompt = backend.executed_calls[-1]["prompt"]
    assert "NO SOURCES WERE PROVIDED" in prompt
    assert "Insert APA 7 in-text citations" not in prompt
