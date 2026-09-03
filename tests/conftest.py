"""Pytest fixtures for HowlWriter test isolation."""

import pytest

from howlwriter.integration.howlplane_bridge import set_howlplane_bridge

# Ensure control plane fakes are installed for portable test execution if HowlPlane is not installed.
try:
    import src.control_plane.role_binding  # noqa: F401
    import src.control_plane.agent_execution  # noqa: F401
except ImportError:
    from tests.fakes.control_plane import install_control_plane_fakes

    install_control_plane_fakes()


@pytest.fixture(autouse=True)
def reset_global_bridges():
    """Ensures each test starts with a clean, unconfigured bridge state."""
    set_howlplane_bridge(None)
    try:
        from src.control_plane.role_binding import get_default_role_registry
        get_default_role_registry().clear()
    except Exception:
        pass
    yield
    set_howlplane_bridge(None)
    try:
        from src.control_plane.role_binding import get_default_role_registry
        get_default_role_registry().clear()
    except Exception:
        pass
