"""Tests for the HowlPlane writing bridge in HowlWriter."""

import pytest

from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    get_howlplane_bridge,
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


def test_bridge_is_role_configured():
    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)

    assert bridge.is_role_configured(WritingRole.HUMANIZER) is False

    registry.register_binding(
        RoleBinding(
            domain="writing", role="humanizer", provider="claude_code"
        )
    )
    assert bridge.is_role_configured(WritingRole.HUMANIZER) is True
    assert bridge.is_role_configured(WritingRole.FINAL_REVIEWER) is False


def test_bridge_unconfigured_role_raises_error():
    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)

    with pytest.raises(ModelRoleNotConfiguredError) as exc_info:
        bridge.execute_writing_role(
            role=WritingRole.HUMANIZER,
            prompt="Rewrite this text.",
        )
    assert exc_info.value.role == WritingRole.HUMANIZER


def test_bridge_executes_with_custom_backend():
    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)

    fake = FakeAgentBackend(
        agent_id="test_provider",
        default_stdout="""```yaml
resulting_text: "Clean prose."
changes_made:
  - "simplified words"
rationale: "Better readability"
```""",
    )

    result = bridge.execute_writing_role(
        role=WritingRole.HUMANIZER,
        prompt="Rewrite this.",
        custom_backend=fake,
    )

    assert result.success is True
    assert result.provider == "test_provider"
    assert result.structured_output["resulting_text"] == "Clean prose."


def test_global_bridge_getter_and_setter():
    orig = get_howlplane_bridge()
    try:
        new_bridge = HowlPlaneWritingBridge()
        set_howlplane_bridge(new_bridge)
        assert get_howlplane_bridge() is new_bridge
    finally:
        set_howlplane_bridge(orig)
