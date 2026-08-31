"""Tests for model-backed execution in run_howl_pipeline."""

from pathlib import Path

from howlwriter.config.schema import BannedWord, HowlWriterConfig
from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from howlwriter.pipeline.howl import run_howl_pipeline
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)


def test_howl_pipeline_with_model_execution_ready(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text("""# Quarterly Report

Furthermore, we must delve into this tapestry. The team achieved 95% satisfaction on Tuesday.""")

    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(
            domain="writing",
            role="humanizer",
            provider="claude_code",
        )
    )
    registry.register_binding(
        RoleBinding(
            domain="writing",
            role="final_reviewer",
            provider="codex",
        )
    )

    fake_backend = FakeAgentBackend(
        agent_id="test_agent",
        default_stdout="""```yaml
resulting_text: |
  # Quarterly Report

  We examined our progress. The team achieved 95% satisfaction on Tuesday.
changes_made:
  - "removed 'delve into this tapestry'"
  - "simplified transition"
verdict: "PASS"
differences: []
rationale: "Natural prose with all facts preserved."
```""",
    )

    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)

    config = HowlWriterConfig(
        banned_words=[BannedWord(word="delve"), BannedWord(word="tapestry")]
    )

    res = run_howl_pipeline(draft, config, custom_backend=fake_backend)

    assert "We examined our progress" in res.final_document.text
    assert res.report.status == "READY"
    assert res.report.meaning_preservation == "PASS"
    assert res.report.semantic_meaning_status == "PASS"
    assert res.report.humanizer_provider == "test_agent"
    assert len(res.report.changes) >= 1

    rendered = res.report.render_text()
    assert "HOWLWRITER REPORT" in rendered
    assert "Humanizer:" in rendered
    assert "Meaning Preservation:" in rendered
    assert "STATUS: READY" in rendered


def test_howl_pipeline_with_semantic_fail_sets_needs_review(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text("The server handled 100 requests.")

    fake_backend = FakeAgentBackend(
        agent_id="adversarial_agent",
        default_stdout="""```yaml
resulting_text: |
  The server handled 500 requests with zero latency.
changes_made:
  - "embellished performance"
verdict: "FAIL"
differences:
  - kind: "altered_fact"
    description: "Changed 100 requests to 500 requests."
rationale: "Factual violation."
```""",
    )

    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(
            domain="writing", role="humanizer", provider="test_humanizer"
        )
    )
    registry.register_binding(
        RoleBinding(
            domain="writing", role="final_reviewer", provider="test_reviewer"
        )
    )

    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)

    config = HowlWriterConfig()
    res = run_howl_pipeline(draft, config, custom_backend=fake_backend)

    # Failed semantic review must prevent READY status
    assert res.report.status == "NEEDS_REVIEW"
    assert res.report.semantic_meaning_status == "FAIL"


def test_howl_pipeline_deterministic_only_override(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text("We need to delve into this.")

    config = HowlWriterConfig(
        banned_words=[BannedWord(word="delve", replacement="examine")],
        apply_safe_rewrites=True,
    )

    res = run_howl_pipeline(draft, config, deterministic_only=True)

    assert "examine" in res.final_document.text
    assert res.report.humanizer_provider is None
    assert res.report.status == "READY"
