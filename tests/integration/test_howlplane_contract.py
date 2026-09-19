"""Hermetic contract test validating integration between HowlWriter and HowlPlane.

Ensures HowlWriter integrates directly with the real pinned howlplane.control_plane
package without relying on synthetic test fakes (tests/fakes/control_plane.py).
"""

import pytest

from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    RoleBindingProtocol,
    RoleBindingRegistryProtocol,
    RoleDispatcherProtocol,
)
from howlwriter.integration.model_role import (
    ModelRoleNotConfiguredError,
    WritingRole,
)


@pytest.mark.contract
def test_real_howlplane_package_installed_and_no_fakes():
    """Verify that the real howlplane.control_plane package is imported from disk, not fakes."""
    import howlplane.control_plane as cp
    import howlplane.control_plane.role_binding as rb
    import howlplane.control_plane.agent_execution as ae

    assert hasattr(cp, "__file__"), "howlplane.control_plane must be a real package"
    assert cp.__file__ is not None
    assert "tests/fakes" not in cp.__file__, (
        f"Expected real howlplane package, got fake: {cp.__file__}"
    )
    rb_file = getattr(rb, "__file__", "")
    assert "tests/fakes" not in rb_file, (
        f"Expected real role_binding module, got fake: {rb_file}"
    )
    ae_file = getattr(ae, "__file__", "")
    assert "tests/fakes" not in ae_file, (
        f"Expected real agent_execution module, got fake: {ae_file}"
    )


@pytest.mark.contract
def test_howlplane_interface_protocol_compliance():
    """Verify that howlplane role binding classes fulfill the bridge contract protocols."""
    from howlplane.control_plane.role_binding import (
        IndependenceStatus,
        RoleBinding,
        RoleBindingRegistry,
        RoleDispatcher,
        RoleExecutionRequest,
        RoleExecutionResult,
        get_default_role_registry,
    )

    registry = RoleBindingRegistry()
    assert isinstance(registry, RoleBindingRegistryProtocol)

    dispatcher = RoleDispatcher(binding_registry=registry)
    assert isinstance(dispatcher, RoleDispatcherProtocol)

    binding = RoleBinding(domain="writing", role="humanizer", provider="claude_code")
    assert isinstance(binding, RoleBindingProtocol)

    req = RoleExecutionRequest(domain="writing", role="humanizer", prompt="test")
    assert req.domain == "writing"

    res = RoleExecutionResult(
        domain="writing",
        role="humanizer",
        provider="p",
        model="m",
        success=True,
    )
    assert res.success is True

    # Check IndependenceStatus enum members
    assert IndependenceStatus.INDEPENDENT.value == "INDEPENDENT"
    assert IndependenceStatus.SAME_PROVIDER.value == "SAME_PROVIDER"
    assert IndependenceStatus.NOT_REVIEWED.value == "NOT_REVIEWED"
    assert IndependenceStatus.UNAVAILABLE.value == "UNAVAILABLE"

    # Verify get_default_role_registry returns a working registry
    default_reg = get_default_role_registry()
    assert isinstance(default_reg, RoleBindingRegistryProtocol)


@pytest.mark.contract
def test_bridge_execution_with_real_howlplane():
    """Verify HowlPlaneWritingBridge executes cleanly using real HowlPlane classes."""
    from howlplane.control_plane.agent_execution import FakeAgentBackend
    from howlplane.control_plane.role_binding import (
        RoleBinding,
        RoleBindingRegistry,
        RoleDispatcher,
    )

    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)

    # Initially unconfigured
    assert bridge.is_role_configured(WritingRole.HUMANIZER) is False

    # Register binding
    registry.register_binding(
        RoleBinding(
            domain="writing",
            role="humanizer",
            provider="claude_code",
            model="claude-3-5-sonnet",
        )
    )
    assert bridge.is_role_configured(WritingRole.HUMANIZER) is True

    # Execute with real dispatcher and FakeAgentBackend
    fake_backend = FakeAgentBackend(
        agent_id="claude_code",
        default_stdout="""```yaml
resulting_text: "Clear, crisp, and rhythmic sentence structure."
changes_made:
  - "Eliminated repetitive adverbs"
rationale: "Improves cadence and clarity"
```""",
    )

    result = bridge.execute_writing_role(
        role=WritingRole.HUMANIZER,
        prompt="Polish this paragraph.",
        custom_backend=fake_backend,
    )

    assert result.success is True
    assert result.provider == "claude_code"
    assert result.structured_output["resulting_text"] == "Clear, crisp, and rhythmic sentence structure."
    assert "Eliminated repetitive adverbs" in result.structured_output["changes_made"]


@pytest.mark.contract
def test_unconfigured_role_fails_closed_with_real_howlplane():
    """Verify that unconfigured roles fail closed with ModelRoleNotConfiguredError."""
    from howlplane.control_plane.role_binding import (
        RoleBindingRegistry,
        RoleDispatcher,
    )

    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)

    with pytest.raises(ModelRoleNotConfiguredError) as exc_info:
        bridge.execute_writing_role(
            role=WritingRole.FINAL_REVIEWER,
            prompt="Review this document.",
        )
    assert exc_info.value.role == WritingRole.FINAL_REVIEWER
