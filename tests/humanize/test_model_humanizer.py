"""Tests for ModelHumanizerRewriter executing via HowlPlane."""

import pytest

from howlwriter.config.schema import BannedWord, HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.humanize.rewriter import (
    ModelHumanizeResult,
    ModelHumanizerRewriter,
)
from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from howlwriter.integration.model_role import (
    ModelRoleNotConfiguredError,
    WritingRole,
)
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)


def test_model_humanizer_unconfigured_raises():
    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)

    doc = Document.parse("We must delve into this tapestry.")
    config = HowlWriterConfig()

    rewriter = ModelHumanizerRewriter()
    with pytest.raises(ModelRoleNotConfiguredError) as exc_info:
        rewriter.rewrite(doc, config)
    assert exc_info.value.role == WritingRole.HUMANIZER


def test_model_humanizer_executes_with_structured_yaml():
    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(
            domain="writing",
            role="humanizer",
            provider="fake_humanizer_agent",
        )
    )
    fake_backend = FakeAgentBackend(
        agent_id="fake_humanizer_agent",
        default_stdout="""```yaml
resulting_text: |
  We need to look closely at this work.
changes_made:
  - "replaced generic transition"
  - "removed 'delve' and 'tapestry'"
rationale: "Eliminated AI clichés."
warnings: []
```""",
    )
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)

    doc = Document.parse(
        "Furthermore, we must delve into this tapestry.",
        title="Test Doc",
        mode="essay",
    )
    config = HowlWriterConfig(
        banned_words=[BannedWord(word="delve"), BannedWord(word="tapestry")],
        humanization_strength="high",
    )

    rewriter = ModelHumanizerRewriter()
    result = rewriter.rewrite(doc, config, custom_backend=fake_backend)

    assert isinstance(result, ModelHumanizeResult)
    assert "We need to look closely" in result.document.text
    assert len(result.changes) == 2
    assert "replaced generic transition" in result.changes[0].description
    assert result.provider == "fake_humanizer_agent"
    assert result.rationale == "Eliminated AI clichés."


def test_model_humanizer_fallback_raw_output():
    fake_backend = FakeAgentBackend(
        agent_id="raw_agent",
        default_stdout="This is plain rewritten text without any markdown blocks.",
    )
    doc = Document.parse("Original robotic prose.")
    config = HowlWriterConfig()

    rewriter = ModelHumanizerRewriter()
    result = rewriter.rewrite(doc, config, custom_backend=fake_backend)

    assert result.document.text == "This is plain rewritten text without any markdown blocks."
    assert len(result.changes) == 1
    assert result.provider == "raw_agent"
