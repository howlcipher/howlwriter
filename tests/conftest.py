import os
import sys
import types
import pytest

from howlwriter.integration.howlplane_bridge import set_howlplane_bridge

# Ensure control plane fakes are installed for portable test execution only when HowlPlane is not installed
# and fakes have not been explicitly disabled (e.g. for contract tests against the real HowlPlane package).
_no_fakes = os.environ.get("HOWLWRITER_NO_CONTROL_PLANE_FAKES") == "1"

try:
    import howlplane.control_plane.role_binding as hp_rb
    import howlplane.control_plane.agent_execution as hp_ae
    # Alias legacy src.control_plane imports to the real installed howlplane package
    if "src.control_plane" not in sys.modules:
        if "src" not in sys.modules:
            sys.modules["src"] = types.ModuleType("src")
        src_cp = types.ModuleType("src.control_plane")
        sys.modules["src.control_plane"] = src_cp
        sys.modules["src.control_plane.role_binding"] = hp_rb
        sys.modules["src.control_plane.agent_execution"] = hp_ae
except ImportError:
    if not _no_fakes:
        try:
            import src.control_plane.role_binding  # noqa: F401
            import src.control_plane.agent_execution  # noqa: F401
        except ImportError:
            from tests.fakes.control_plane import install_control_plane_fakes

            install_control_plane_fakes()


@pytest.fixture(autouse=True)
def isolate_diagnostic_runs(tmp_path, monkeypatch):
    """Keep diagnostic run records out of the developer's home directory.

    Most tests that exercise a pipeline never set HOWLWRITER_RUNS_DIR, so every
    run they performed wrote a permanent record to ~/.howlwriter/runs. That
    directory had accumulated 19,900 records, and nothing prunes it.
    """
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))
    yield


@pytest.fixture(autouse=True)
def reset_global_bridges():
    """Ensures each test starts with a clean, unconfigured bridge state."""
    set_howlplane_bridge(None)
    try:
        from howlplane.control_plane.role_binding import get_default_role_registry
        get_default_role_registry().clear()
    except Exception:
        try:
            from src.control_plane.role_binding import get_default_role_registry
            get_default_role_registry().clear()
        except Exception:
            pass
    yield
    set_howlplane_bridge(None)
    try:
        from howlplane.control_plane.role_binding import get_default_role_registry
        get_default_role_registry().clear()
    except Exception:
        try:
            from src.control_plane.role_binding import get_default_role_registry
            get_default_role_registry().clear()
        except Exception:
            pass
