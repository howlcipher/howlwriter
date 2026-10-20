"""HowlWriter's side of the Howl interop contract (docs/INTEROP.md in howlcipher/howl)."""

import json
import re
import sys

import pytest

from howlwriter import __version__
from howlwriter.cli.main import build_parser, main
from howlwriter.integration import howlplane_bridge, provider_choice
from howlwriter.integration.howlplane_bridge import HowlPlaneWritingBridge, howlplane_root_from_env
from howlwriter.integration.model_role import HowlPlaneUnavailableError, WritingRole

FLAG = re.compile(r"^--?[A-Za-z0-9][A-Za-z0-9_-]*$")


def _descriptor(capsys) -> dict:
    assert main(["interop", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_descriptor_describes_every_nested_command(capsys):
    d = _descriptor(capsys)
    assert (d["schema"], d["component"], d["version"]) == ("howl.interop/v1", "howlwriter", __version__)
    described = {tuple(c["path"]): set(c["flags"]) for c in d["commands"]}
    for command in d["commands"]:
        assert all(FLAG.match(f) for f in command["flags"]), command

    def walk(parser, path):
        flags = {o for a in parser._actions for o in a.option_strings} - {"-h", "--help"}
        assert described[path] == flags, path
        for action in parser._actions:
            if action.__class__.__name__ == "_SubParsersAction":
                for name, sub in action.choices.items():
                    walk(sub, (*path, name))

    walk(build_parser(), ())


def test_descriptor_covers_what_howlplane_runs(capsys):
    commands = {tuple(c["path"]): c for c in _descriptor(capsys)["commands"]}
    assert {"--provider", "--review-provider", "--local-model"} <= set(commands[()]["flags"])
    assert {"--fail-if-blocked", "--out"} <= set(commands[("writer",)]["flags"])
    assert {"--instructions", "--json", "--fail-if-blocked", "--out"} <= set(
        commands[("project", "draft")]["flags"]
    )
    assert "--json" in commands[("lint",)]["flags"]
    assert commands[("native", "write")]["emits"] == ["howlwriter.copy_package/v1"]
    assert set(_descriptor(capsys)["exit_codes"]) == {"0", "1", "2", "3", "4", "130"}


def test_usage_error_exits_1_not_the_no_model_code(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["writer", "--no-such-flag", "prompt"])
    assert exc.value.code == 1
    assert "unrecognized arguments" in capsys.readouterr().err


def test_howlplane_home_is_accepted_like_howlplane_root(monkeypatch):
    for name in ("HOWLPLANE_ROOT", "HOWLPLANE_HOME", "HOWLPLANE_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert howlplane_root_from_env() is None
    monkeypatch.setenv("HOWLPLANE_HOME", "/checkouts/howlplane")
    assert howlplane_root_from_env() == "/checkouts/howlplane"
    monkeypatch.setenv("HOWLPLANE_ROOT", "/explicit")
    assert howlplane_root_from_env() == "/explicit"


def _checkout(root):
    (root / "src" / "howlplane" / "control_plane").mkdir(parents=True)
    return root


def test_howlplane_home_never_shadows_an_installed_howlplane(tmp_path, monkeypatch):
    checkout = _checkout(tmp_path / "howlplane")
    monkeypatch.delenv("HOWLPLANE_ROOT", raising=False)
    monkeypatch.setenv("HOWLPLANE_HOME", str(checkout))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(howlplane_bridge.importlib.util, "find_spec", lambda name: object())
    howlplane_bridge._ensure_howlplane_on_path()
    assert str(checkout / "src") not in sys.path

    monkeypatch.setattr(howlplane_bridge.importlib.util, "find_spec", lambda name: None)
    howlplane_bridge._ensure_howlplane_on_path()
    # A fallback is appended, so it cannot shadow anything already importable.
    assert sys.path[-2:] == [str((checkout / "src").resolve()), str(checkout.resolve())]


def test_howlplane_root_still_takes_precedence(tmp_path, monkeypatch):
    checkout = _checkout(tmp_path / "howlplane")
    monkeypatch.setenv("HOWLPLANE_ROOT", str(checkout))
    monkeypatch.setattr(sys, "path", list(sys.path))
    howlplane_bridge._ensure_howlplane_on_path()
    assert sys.path[:2] == [str((checkout / "src").resolve()), str(checkout.resolve())]


def test_chosen_model_without_howlplane_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(howlplane_bridge, "_try_import_howlplane", lambda: None)
    monkeypatch.setattr(howlplane_bridge, "_IMPORT_PROBLEM", None)
    monkeypatch.setitem(provider_choice.PROCESS_DEFAULTS, "writer", None)
    monkeypatch.setitem(provider_choice.PROCESS_DEFAULTS, "reviewer", None)
    monkeypatch.setitem(provider_choice.PROCESS_DEFAULTS, "interactive", False)
    bridge = HowlPlaneWritingBridge()
    assert bridge.is_available() is False
    # No model chosen: still the "needs a model" path, so rule-based steps run.
    assert bridge.is_role_configured(WritingRole.HUMANIZER) is False
    bridge.use_provider("claude")
    with pytest.raises(HowlPlaneUnavailableError) as exc:
        bridge.is_role_configured(WritingRole.HUMANIZER)
    assert "claude" in str(exc.value) and "howlwriter[plane]" in str(exc.value)
    with pytest.raises(HowlPlaneUnavailableError):
        bridge.execute_writing_role(WritingRole.HUMANIZER, "text")
