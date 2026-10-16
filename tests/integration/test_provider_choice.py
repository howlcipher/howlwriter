"""Choosing the model at run time: asked, confirmed for remote, never switched silently."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from howlwriter.integration import howlplane_bridge as bridge_module
from howlwriter.integration import provider_choice as pc
from howlwriter.integration.howlplane_bridge import HowlPlaneWritingBridge
from howlwriter.integration.model_role import ModelRoleNotConfiguredError, WritingRole

try:
    from howlplane.control_plane.agent_execution import FakeAgentBackend
    from howlplane.control_plane.role_binding import RoleBinding, RoleBindingRegistry, RoleDispatcher
except ImportError:
    from src.control_plane.agent_execution import FakeAgentBackend
    from src.control_plane.role_binding import RoleBinding, RoleBindingRegistry, RoleDispatcher


ALL_READY = [(option, True, "") for option in pc.OPTIONS]


@pytest.fixture(autouse=True)
def _clean_process_defaults(monkeypatch):
    monkeypatch.setattr(pc, "PROCESS_DEFAULTS", {"writer": None, "reviewer": None, "interactive": False})
    monkeypatch.delenv(pc.ENV_PROVIDER, raising=False)
    monkeypatch.delenv(pc.ENV_REVIEW_PROVIDER, raising=False)


@pytest.fixture
def backends(monkeypatch):
    """Fake backends keyed by provider id; records which one actually ran."""
    made: dict[str, FakeAgentBackend] = {}

    def backend_for(provider: str):
        return made.setdefault(provider, FakeAgentBackend(agent_id=provider, default_stdout="ok"))

    monkeypatch.setattr(bridge_module, "_backend_for", backend_for)
    return made


def _bridge(registry=None):
    registry = registry or RoleBindingRegistry()
    return HowlPlaneWritingBridge(dispatcher=RoleDispatcher(binding_registry=registry), registry=registry)


def _answers(*values):
    queue = list(values)
    return lambda prompt: queue.pop(0)


def test_aliases_name_exactly_the_four_choices():
    assert pc.normalize("claude") == "claude_code"
    assert pc.normalize("local") == pc.normalize("ollama") == "local_ollama"
    assert pc.normalize("AGY") == "agy" and pc.normalize("codex") == "codex"
    with pytest.raises(ValueError):
        pc.normalize("gpt")


def test_local_choice_needs_no_confirmation():
    out = io.StringIO()
    provider, confirmed = pc.ask(purpose="writing", input_fn=_answers("4"), output=out, rows=ALL_READY)
    assert (provider, confirmed) == ("local_ollama", False)
    assert "private, on this machine" in out.getvalue()


def test_remote_choice_shows_what_is_sent_and_needs_yes():
    out = io.StringIO()
    answers = _answers("1", "y")
    provider, confirmed = pc.ask(purpose="writing", input_fn=answers, output=out, rows=ALL_READY)
    assert (provider, confirmed) == ("claude_code", True)
    assert "will be sent to Claude Code" in out.getvalue()
    with pytest.raises(pc.ProviderChoiceCancelled):
        pc.ask(purpose="x", input_fn=_answers("codex", ""), output=io.StringIO(), rows=ALL_READY)


def test_cancel_and_unavailable_choices_send_nothing():
    rows = [(o, o.provider != "agy", "" if o.provider != "agy" else "not installed") for o in pc.OPTIONS]
    out = io.StringIO()
    with pytest.raises(pc.ProviderChoiceCancelled):
        pc.ask(purpose="x", input_fn=_answers("2"), output=out, rows=rows)  # agy is unavailable
    assert "[unavailable: not installed]" in out.getvalue()
    with pytest.raises(pc.ProviderChoiceCancelled):
        pc.ask(purpose="x", input_fn=_answers(""), output=io.StringIO(), rows=ALL_READY)


def test_unbound_role_without_a_chooser_still_refuses(backends):
    with pytest.raises(ModelRoleNotConfiguredError, match="--provider"):
        _bridge().execute_writing_role(role=WritingRole.WRITER, prompt="p")
    assert backends == {}


def test_asked_once_then_the_chosen_backend_runs(backends):
    bridge = _bridge()
    asked = []

    def chooser(role, avoid=None):
        asked.append((role, avoid))
        return "codex", True

    bridge.chooser = chooser
    first = bridge.execute_writing_role(role=WritingRole.WRITER, prompt="p")
    second = bridge.execute_writing_role(role=WritingRole.EDITOR, prompt="p")
    assert first.provider == second.provider == "codex"
    assert asked == [(WritingRole.WRITER, None)]
    assert len(backends["codex"].executed_calls) == 2
    assert bridge.is_remote_confirmed("codex")


def test_declining_the_choice_runs_nothing(backends):
    bridge = _bridge()

    def chooser(role, avoid=None):
        raise pc.ProviderChoiceCancelled("declined to send text to Codex; nothing was sent")

    bridge.chooser = chooser
    with pytest.raises(ModelRoleNotConfiguredError, match="nothing was sent"):
        bridge.execute_writing_role(role=WritingRole.WRITER, prompt="p")
    assert backends == {}


def test_independent_review_is_asked_for_never_switched_silently(backends):
    bridge = _bridge()
    bridge.use_provider("claude")
    calls = []

    def chooser(role, avoid=None):
        calls.append(avoid)
        return "codex", True

    bridge.chooser = chooser
    review = bridge.execute_writing_role(
        role=WritingRole.FINAL_REVIEWER, prompt="p", avoid_provider="claude_code"
    )
    assert calls == ["claude_code"]
    assert review.provider == "codex" and review.independence_status == "INDEPENDENT"


def test_without_a_reviewer_choice_the_same_model_reviews_and_says_so(backends):
    bridge = _bridge()
    bridge.use_provider("claude")
    review = bridge.execute_writing_role(
        role=WritingRole.FINAL_REVIEWER, prompt="p", avoid_provider="claude_code"
    )
    assert review.provider == "claude_code"
    assert review.independence_status == "SAME_PROVIDER"
    assert set(backends) == {"claude_code"}


def test_a_bound_role_is_used_as_before_and_nobody_is_asked(backends, monkeypatch):
    registry = RoleBindingRegistry()
    registry.register_binding(RoleBinding(domain="writing", role="writer", provider="claude_code"))
    bridge = _bridge(registry)
    bridge.chooser = lambda role, avoid=None: pytest.fail("must not ask when a role is bound")
    assert bridge.chosen_provider(WritingRole.WRITER) is None


def test_a_web_request_choice_overrides_the_process_choice(backends):
    bridge = _bridge()
    bridge.use_provider("codex")
    token = pc.REQUEST_PROVIDER.set("agy")
    try:
        assert bridge.execute_writing_role(role=WritingRole.WRITER, prompt="p").provider == "agy"
    finally:
        pc.REQUEST_PROVIDER.reset(token)


def test_models_always_run_in_an_empty_private_directory_that_is_removed(backends, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "private.txt").write_text("not for the model", encoding="utf-8")
    bridge = _bridge()
    bridge.use_provider("agy")
    seen = {}

    def side_effect(task, cwd: Path, prompt):
        seen["cwd"] = cwd
        seen["listing"] = os.listdir(cwd)
        seen["mode"] = cwd.stat().st_mode & 0o777

    backends["agy"] = FakeAgentBackend(agent_id="agy", side_effect=side_effect)
    bridge.execute_writing_role(role=WritingRole.WRITER, prompt="p")
    assert seen["cwd"] != tmp_path and seen["listing"] == [] and seen["mode"] == 0o700
    assert not seen["cwd"].exists()
    # A caller's folder (e.g. the document's) is never handed to the model either.
    explicit = tmp_path / "work"
    explicit.mkdir()
    bridge.execute_writing_role(role=WritingRole.WRITER, prompt="p", cwd=explicit)
    assert seen["cwd"] != explicit.resolve() and seen["listing"] == []
    assert not seen["cwd"].exists() and explicit.exists()


def test_cli_provider_flag_and_environment(monkeypatch, capsys):
    from howlwriter.cli import main as cli

    cli.main(["--provider", "local", "--review-provider", "claude", "voice", "list"])
    assert pc.PROCESS_DEFAULTS["writer"] == "local_ollama"
    assert pc.PROCESS_DEFAULTS["reviewer"] == "claude_code"
    monkeypatch.setenv(pc.ENV_PROVIDER, "codex")
    cli.main(["voice", "list"])
    assert pc.PROCESS_DEFAULTS["writer"] == "codex"
    assert cli.main(["--provider", "gpt", "voice", "list"]) == 1
    assert "unknown model" in capsys.readouterr().err


def test_a_bridge_created_after_the_cli_choice_uses_it(backends):
    pc.PROCESS_DEFAULTS.update(writer="local_ollama", interactive=False)
    bridge = _bridge()
    assert bridge.execute_writing_role(role=WritingRole.WRITER, prompt="p").provider == "local_ollama"
    assert not bridge.is_remote_confirmed("local_ollama")


def test_continue_without_a_model_makes_model_steps_optional_and_sticks(backends):
    bridge = _bridge()
    asked = []
    bridge.chooser = lambda role, avoid=None: asked.append(role) or (pc.NO_MODEL, False)
    assert bridge.is_role_configured(WritingRole.HUMANIZER) is False
    assert bridge.is_role_configured(WritingRole.FINAL_REVIEWER) is False
    with pytest.raises(ModelRoleNotConfiguredError, match="without a model"):
        bridge.execute_writing_role(role=WritingRole.WRITER, prompt="p")
    assert asked == [WritingRole.HUMANIZER] and backends == {}


def test_reviews_are_never_offered_no_model():
    out = io.StringIO()
    with pytest.raises(pc.ProviderChoiceCancelled):
        pc.ask(purpose="review", avoid="claude_code", input_fn=_answers("0"), output=out, rows=ALL_READY)
    assert "Continue without a model" not in out.getvalue()
    assert "wrote the text" in out.getvalue()


def test_humanize_cli_takes_the_rule_based_path_when_no_model_is_chosen(tmp_path, monkeypatch, capsys):
    from howlwriter.cli import main as cli
    from howlwriter.integration.howlplane_bridge import set_howlplane_bridge

    bridge = _bridge()
    bridge.chooser = lambda role, avoid=None: (pc.NO_MODEL, False)
    set_howlplane_bridge(bridge)
    try:
        draft = tmp_path / "draft.md"
        draft.write_text("It is important to note that we leverage robust tools.\n", encoding="utf-8")
        assert cli.main(["humanize", str(draft), "--mode", "technical"]) == 0
    finally:
        set_howlplane_bridge(None)
    assert "Continuing without a model" in capsys.readouterr().out


def test_the_web_server_never_prompts_on_its_terminal(monkeypatch):
    from howlwriter.cli.commands import ui

    monkeypatch.setitem(pc.PROCESS_DEFAULTS, "interactive", True)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", None)  # stop before serving
    ui.run(type("A", (), {"host": "127.0.0.1", "port": 0, "no_browser": True})())
    assert pc.PROCESS_DEFAULTS["interactive"] is False


def test_humanizer_shows_style_examples_to_local_models_only_unless_turned_on(tmp_path, backends):
    import json as _json

    from howlwriter.config.defaults import default_config
    from howlwriter.humanize.rewriter import _style_examples
    from howlwriter.voice import exemplars

    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "profile.json").write_text("{}", encoding="utf-8")
    passage = "I checked the capture twice. The handshake was there the second time; the certificate was not."
    bank = {"paragraphs": [{"doc": "a", "weight": 1.0, "words": 18, "text": passage}]}
    (voice_dir / exemplars.EXEMPLARS_FILE).write_text(_json.dumps(bank), encoding="utf-8")
    config = default_config()
    config.voice_profile = str(voice_dir / "profile.json")
    bridge = _bridge()
    bridge.use_provider("local")
    assert passage in _style_examples(config, bridge, WritingRole.HUMANIZER, "capture handshake", None)
    bridge.use_provider("claude")
    assert _style_examples(config, bridge, WritingRole.HUMANIZER, "capture handshake", None) == ""
    config.voice_examples = "on"
    assert passage in _style_examples(config, bridge, WritingRole.HUMANIZER, "capture", None)
    config.voice_examples = "off"
    bridge.use_provider("local")
    assert _style_examples(config, bridge, WritingRole.HUMANIZER, "capture", None) == ""


def test_local_model_choice_selects_that_ollama_model(monkeypatch):
    from howlplane.control_plane.agent_execution import OllamaLocalBackend

    monkeypatch.setitem(pc.PROCESS_DEFAULTS, "local_model", "qwen2.5:7b-instruct")
    backend = pc.make_backend("local_ollama")
    assert isinstance(backend, OllamaLocalBackend) and backend.model == "qwen2.5:7b-instruct"
    monkeypatch.setitem(pc.PROCESS_DEFAULTS, "local_model", None)
    monkeypatch.setenv(pc.ENV_LOCAL_MODEL, "llama3.1:8b")
    assert pc.make_backend("local_ollama").model == "llama3.1:8b"
    assert pc.make_backend("codex").agent_id == "codex"
