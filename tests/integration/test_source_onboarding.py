"""Exercise discovery in fresh processes without pytest's Plane doubles."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROLE_MODULE = '''
import os
from types import SimpleNamespace
IndependenceStatus = object
RoleExecutionRequest = object
class RoleBindingRegistry:
    def get_binding(self, domain, role):
        provider = os.environ.get("HOWLPLANE_ROLE_WRITING_WRITER")
        return SimpleNamespace(provider=provider) if provider else None
class RoleDispatcher:
    def __init__(self, binding_registry):
        self.registry = binding_registry
    def execute(self, *args, **kwargs):
        raise AssertionError("discovery must not execute a provider")
def get_default_role_registry():
    return RoleBindingRegistry()
'''


def package(root, relative):
    folder = root / relative
    folder.mkdir(parents=True)
    (folder / "role_binding.py").write_text(ROLE_MODULE)


def child_env(root=None, extra_path=None):
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("HOWLPLANE_ROLE_"):
            del env[name]
    env.pop("HOWLPLANE_ROOT", None)
    writer_src = Path(__file__).resolve().parents[2] / "src"
    env["PYTHONPATH"] = os.pathsep.join(
        str(p) for p in [writer_src, extra_path] if p is not None
    )
    env["HOWL_FORBID_LOCAL_INFERENCE"] = "1"
    if root is not None:
        env["HOWLPLANE_ROOT"] = str(root)
    return env


@pytest.mark.parametrize("layout", ["src", "legacy", "installed"])
def test_discover_role_without_provider_execution(tmp_path, layout):
    relative = {
        "src": "src/howlplane/control_plane",
        "legacy": "src/control_plane",
        "installed": "howlplane/control_plane",
    }[layout]
    package(tmp_path, relative)
    env = child_env(
        root=tmp_path if layout != "installed" else None,
        extra_path=tmp_path if layout == "installed" else None,
    )
    env["HOWLPLANE_ROLE_WRITING_WRITER"] = "explicit_test_provider"
    code = """
from howlwriter.integration.howlplane_bridge import HowlPlaneWritingBridge
from howlwriter.integration.model_role import WritingRole
bridge = HowlPlaneWritingBridge()
assert bridge.is_available()
assert bridge.is_role_configured(WritingRole.WRITER)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("available", [False, True])
def test_public_writer_missing_setup_is_actionable(tmp_path, available):
    if available:
        package(tmp_path, "src/howlplane/control_plane")
    env = child_env(root=tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "howlwriter.cli.main", "writer", "Test topic"],
        env=env, cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "HOWLPLANE_ROLE_WRITING_WRITER" in result.stderr
    assert "HOWLPLANE_ROOT" in result.stderr
    assert "docs/howlplane-integration.md" in result.stderr
    assert "Traceback" not in result.stderr


def test_public_writer_help_explains_setup(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "howlwriter.cli.main", "writer", "--help"],
        env=child_env(), cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "HOWLPLANE_ROLE_WRITING_WRITER" in result.stdout
    assert "HOWLPLANE_ROOT" in result.stdout


def broken_package(root):
    """A HowlPlane checkout that is present but needs a dependency this Python lacks."""
    folder = root / "src/howlplane/control_plane"
    folder.mkdir(parents=True)
    for init in (root / "src/howlplane/__init__.py", folder / "__init__.py"):
        init.write_text("")
    for name in ("role_binding.py", "agent_execution.py"):
        (folder / name).write_text("import missing_dep_for_test\n")


def test_a_broken_howlplane_names_its_missing_dependency(tmp_path):
    broken_package(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "howlwriter.cli.main", "--provider", "claude", "writer", "Test topic"],
        env=child_env(root=tmp_path), cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "missing_dep_for_test" in result.stderr
    assert "is not configured" not in result.stderr
    assert "Traceback" not in result.stderr


def test_a_broken_howlplane_shows_in_model_availability(tmp_path):
    broken_package(tmp_path)
    code = """
from howlwriter.integration import provider_choice
reasons = {why for _, ready, why in provider_choice.availability() if not ready}
assert len(reasons) == 1 and "missing_dep_for_test" in reasons.pop(), reasons
"""
    result = subprocess.run(
        [sys.executable, "-c", code], env=child_env(root=tmp_path), cwd=tmp_path,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
