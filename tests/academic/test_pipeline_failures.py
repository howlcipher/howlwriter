"""Tests for failure modes, gating, and edge cases in the academic paper pipeline."""

from datetime import date
import pytest

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec, LengthConstraints, SourceRequirements
from howlwriter.config.defaults import default_config
from howlwriter.domain.source import Source
from src.control_plane.agent_execution import FakeAgentBackend


def test_failure_to_reach_word_target_results_in_needs_review(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = AssignmentSpec(
        title="Length Bound Test",
        topic="Testing word count failure modes.",
        target_words=1000,
        word_tolerance_percent=10.0,  # 900 to 1100 words required
        outline=["Section 1", "Section 2"],
    )

    # Fake backend returns a very short draft (~20 words) and fails to expand even after retry
    fake_backend = FakeAgentBackend(
        agent_id="fake_short_writer",
        default_stdout="""```yaml
body_markdown: |
  # Length Bound Test

  ## Section 1
  This draft remains too short.

  ## Section 2
  Still too short to satisfy the required word target.
word_count_estimate: 20
```""",
    )

    s1 = Source(
        id="S001",
        title="Length Bound Test Source",
        authors=["Author, Real"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="Test source retrieved text for length bounds.",
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[s1],
        custom_backend=fake_backend,
        max_length_retries=1,
    )

    assert result.report.status == "NEEDS_REVIEW"
    assert result.report.word_count_status == "TOO_SHORT"
    assert result.report.actual_body_words < 100


def test_missing_outline_topic_results_in_needs_review(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    s1 = Source(
        id="S001",
        title="Outline Test Source",
        authors=["Author, Real"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="Test source retrieved text for outline check.",
    )

    spec = AssignmentSpec(
        title="Outline Gap Test",
        topic="Testing missing outline topic detection.",
        target_words=30,
        word_tolerance_percent=50.0,
        outline=["Required Topic A", "Required Topic B", "Missing Topic C"],
    )

    fake_backend = FakeAgentBackend(
        agent_id="fake_outline_dropper",
        default_stdout="""```yaml
body_markdown: |
  # Outline Gap Test

  ## Required Topic A
  Discussion of topic A in detail.

  ## Required Topic B
  Discussion of topic B in detail.
word_count_estimate: 25
```""",
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[s1],
        custom_backend=fake_backend,
    )

    assert result.report.status == "NEEDS_REVIEW"
    assert result.report.outline_status == "FAIL"
    assert result.outline_result.present_topics_count == 2
    assert result.outline_result.required_topics_count == 3


def test_unsupported_claims_block_ready_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    s1 = Source(
        id="S001",
        title="AI Security Study",
        authors=["Author, Real"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="AI models require standard API security practices.",
    )

    spec = AssignmentSpec(
        title="Ungrounded Claims Paper",
        topic="Testing hallucination gating.",
        target_words=30,
        word_tolerance_percent=50.0,
        outline=["Analysis"],
    )

    # Writer asserts a factual claim completely ungrounded in S001
    fake_backend = FakeAgentBackend(
        agent_id="fake_hallucinating_writer",
        default_stdout="""```yaml
body_markdown: |
  # Ungrounded Claims Paper

  ## Analysis
  A study of 500 banks demonstrated an exact 98.7% breach elimination rate in 2026.
word_count_estimate: 25
```""",
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[s1],
        custom_backend=fake_backend,
    )

    assert result.report.status == "NEEDS_REVIEW"
    assert result.verification_summary.unsupported_claims >= 1


def _length_tier_spec(title: str) -> AssignmentSpec:
    # Small, easy-to-hit-precisely scale (10 words/page) so filler text can
    # exactly control which length tier is hit: min_words=20, soft
    # max_words=30, hard_max_words=40.
    return AssignmentSpec(
        title=title,
        topic="Testing soft-target vs hard-maximum length tiering.",
        length_constraints=LengthConstraints(
            target_page_min=2, target_page_max=3, max_pages=4, words_per_page=10
        ),
        source_requirements=SourceRequirements(minimum_sources=0),
        outline=[],
        requirements=[],
    )


def _filler_body_yaml_block(title: str, filler_word_count: int) -> str:
    # Single paragraph of distinct-from-heading, non-numeric filler words --
    # deliberately one paragraph only, so redundancy.py's cross-paragraph
    # near-duplicate check (which compares distinct paragraphs) never fires
    # regardless of in-paragraph repetition. Every line is pre-indented by 2
    # spaces to satisfy YAML block-literal ("|") indentation rules once
    # embedded under "body_markdown: |" below.
    filler = " ".join(["filler"] * filler_word_count)
    lines = [f"# {title}", "", filler]
    return "\n".join(f"  {line}" if line else "" for line in lines)


def test_target_miss_does_not_force_needs_review(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = _length_tier_spec("Target Miss Test")
    # Heading "Target Miss Test" = 3 words; 32 filler words -> 35 total,
    # which is above the soft max (30) but at/under the hard max (40).
    body = _filler_body_yaml_block("Target Miss Test", 32)

    fake_backend = FakeAgentBackend(
        agent_id="fake_target_miss_writer",
        default_stdout=f"""```yaml
body_markdown: |
{body}
word_count_estimate: 35
```""",
    )

    s1 = Source(
        id="S001",
        title="Length Tier Test Source",
        authors=["Author, Real"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="Test source retrieved text for length tiering.",
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[s1],
        custom_backend=fake_backend,
        max_length_retries=0,
    )

    assert result.report.word_count_status == "TARGET_MISS"
    assert result.report.status == "READY"


def test_hard_limit_failure_forces_needs_review(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))

    spec = _length_tier_spec("Hard Limit Test")
    # Heading "Hard Limit Test" = 3 words; 42 filler words -> 45 total,
    # above the hard max (40).
    body = _filler_body_yaml_block("Hard Limit Test", 42)

    fake_backend = FakeAgentBackend(
        agent_id="fake_hard_limit_writer",
        default_stdout=f"""```yaml
body_markdown: |
{body}
word_count_estimate: 45
```""",
    )

    s1 = Source(
        id="S001",
        title="Length Tier Test Source",
        authors=["Author, Real"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="Test source retrieved text for length tiering.",
    )

    result = run_academic_pipeline(
        spec,
        default_config(),
        existing_sources=[s1],
        custom_backend=fake_backend,
        max_length_retries=0,
    )

    assert result.report.word_count_status == "HARD_LIMIT_FAILURE"
    assert result.report.status == "NEEDS_REVIEW"


def test_writer_provider_failure_raises_clear_error():
    s1 = Source(
        id="S001",
        title="Test Source",
        authors=["Author, Real"],
        publication_date=date(2024, 1, 1),
        access_date=date.today(),
        retrieved_text="Test source retrieved text.",
    )
    spec = AssignmentSpec(
        title="Provider Error Test",
        topic="Testing error propagation.",
    )
    fake_failing_backend = FakeAgentBackend(
        agent_id="failing_backend",
        default_exit_code=1,
        default_stderr="Provider quota exceeded / connection refused",
    )

    with pytest.raises(RuntimeError, match="failing_backend"):
        run_academic_pipeline(
            spec,
            default_config(),
            existing_sources=[s1],
            custom_backend=fake_failing_backend,
        )
