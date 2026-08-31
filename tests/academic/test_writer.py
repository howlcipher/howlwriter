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
