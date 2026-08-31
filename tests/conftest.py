"""Pytest fixtures for HowlWriter test isolation."""

import pytest

from howlwriter.integration.howlplane_bridge import set_howlplane_bridge


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
