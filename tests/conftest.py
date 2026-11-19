import os
import pytest

from howlwriter.integration.howlplane_bridge import set_howlplane_bridge

# Ensure control plane fakes are installed for portable test execution only when HowlPlane is not installed
# and fakes have not been explicitly disabled (e.g. for contract tests against the real HowlPlane package).
_no_fakes = os.environ.get("HOWLWRITER_NO_CONTROL_PLANE_FAKES") == "1"

# True when the hermetic HowlPlane test double (tests/fakes/control_plane.py) is
# standing in for the real package. `contract` tests assert the real package, so
# they are skipped (not weakened) in that mode; the dedicated contract CI job
# sets HOWLWRITER_NO_CONTROL_PLANE_FAKES=1 and so can never skip them silently.
_fakes_active = False

try:
    import howlplane.control_plane.role_binding  # noqa: F401
    import howlplane.control_plane.agent_execution  # noqa: F401
except ImportError:
    if not _no_fakes:
        from tests.fakes.control_plane import install_control_plane_fakes

        install_control_plane_fakes()
        _fakes_active = True


def pytest_collection_modifyitems(config, items):
    if not _fakes_active:
        return
    skip = pytest.mark.skip(
        reason="real HowlPlane not installed; contract tests run in the dedicated "
        "contract job (HOWLWRITER_NO_CONTROL_PLANE_FAKES=1)"
    )
    for item in items:
        if "contract" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def hermetic_home(request, tmp_path_factory, monkeypatch):
    """No test may read or write the developer's real home or HowlWriter stores."""
    if "docs" in request.node.path.parent.parts[-1:]:
        # Browser tests need the real Playwright cache; they use no HowlWriter stores.
        yield
        return
    real_home = os.path.expanduser("~")
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", os.path.join(real_home, ".cache", "ms-playwright"))
    # A sibling of the test's own tmp_path, so tests that list or create folders in tmp_path are unaffected.
    base = tmp_path_factory.mktemp("hermetic")
    home = base / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for name, sub in (
        ("HOWLWRITER_VOICES_DIR", "voices"),
        ("HOWLWRITER_IDENTITIES_DIR", "identities"),
        ("HOWLWRITER_PROJECTS_DIR", "projects"),
        ("HOWLWRITER_CREDENTIALS_DIR", "credentials"),
    ):
        folder = base / "hw-stores" / sub
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(folder))
    monkeypatch.setenv("HOWLWRITER_PREFERENCES_FILE", str(base / "hw-stores" / "preferences.json"))
    for name, sub in (
        ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data"),
    ):
        monkeypatch.setenv(name, str(base / "xdg" / sub))
    for name, value in (
        ("GIT_AUTHOR_NAME", "Test Author"), ("GIT_AUTHOR_EMAIL", "author@example.invalid"),
        ("GIT_COMMITTER_NAME", "Test Committer"), ("GIT_COMMITTER_EMAIL", "committer@example.invalid"),
    ):
        monkeypatch.setenv(name, value)
    yield


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
def ignore_developer_howlplane_home(monkeypatch):
    """A developer's exported HOWLPLANE_HOME / HOWLPLANE_DIR must not steer HowlPlane discovery in tests."""
    monkeypatch.delenv("HOWLPLANE_HOME", raising=False)
    monkeypatch.delenv("HOWLPLANE_DIR", raising=False)


@pytest.fixture(autouse=True)
def reset_global_bridges():
    """Ensures each test starts with a clean, unconfigured bridge state."""
    set_howlplane_bridge(None)
    try:
        from howlplane.control_plane.role_binding import get_default_role_registry
        get_default_role_registry().clear()
    except Exception:
        pass
    yield
    set_howlplane_bridge(None)
    try:
        from howlplane.control_plane.role_binding import get_default_role_registry
        get_default_role_registry().clear()
    except Exception:
        pass
