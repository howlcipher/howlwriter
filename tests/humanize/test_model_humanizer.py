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
from howlplane.control_plane.agent_execution import FakeAgentBackend
from howlplane.control_plane.role_binding import (
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


_REFINED = (
    "# Orchard checks\n\nTally the rows (Vale, 2024).\n\n"
    "Keep the readings **with the plot notes**.\n\n"
    '    {"reading": 4}\n\n'
    ' ```text\n   label: sample\n ```\n\n'
    "## References\n\nVale, T. (2024). *Tallying rows*."
)
_WRAPPED = (
    "```yaml\nresulting_text: |-\n"
    + "\n".join("  " + line if line else "" for line in _REFINED.splitlines())
    + "\nchanges_made:\n  - description: Tightened the opening.\n"
      "    reason: REDUNDANT_SETUP\nrationale: Clarified the notes.\nwarnings: []\n```"
)


@pytest.fixture
def refine_cli(tmp_path, monkeypatch):
    from dataclasses import replace

    from howlwriter.cli.main import main
    from howlwriter.integration import howlplane_bridge, provider_choice

    monkeypatch.setattr(provider_choice, "PROCESS_DEFAULTS", {})

    def run(response, *, parsed=False, inplace=False):
        backend = FakeAgentBackend(agent_id="local_ollama", default_stdout=response)
        monkeypatch.setattr(howlplane_bridge, "_backend_for", lambda _: backend)
        registry = RoleBindingRegistry()
        dispatcher = RoleDispatcher(binding_registry=registry)
        dispatch = dispatcher.execute

        def execute(*args, **kwargs):
            result = dispatch(*args, **kwargs)
            return result if parsed else replace(result, structured_output=None)

        monkeypatch.setattr(dispatcher, "execute", execute)
        bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
        bridge.use_provider("local")
        configured = bridge.is_role_configured
        monkeypatch.setattr(bridge, "is_role_configured",
                            lambda role: role is not WritingRole.FINAL_REVIEWER and configured(role))
        set_howlplane_bridge(bridge)
        code = main([
            "--provider", "local", "humanize", str(tmp_path / "draft.md"),
            "--mode", "academic_discussion", "--voice-examples", "off",
            "--out", str(tmp_path / ("draft.md" if inplace else "output.md")),
        ])
        assert len(backend.executed_calls) == 1
        return code

    return run


def test_cli_refines_raw_wrapped_yaml_and_preserves_markdown(tmp_path, capsys, refine_cli):
    source = tmp_path / "draft.md"
    source.write_text("Tally all rows (Vale, 2024).\n", encoding="utf-8")
    assert refine_cli(_WRAPPED) == 0
    out = (tmp_path / "output.md").read_text(encoding="utf-8")
    assert out == _REFINED
    assert "Actual Body Words:   14" in capsys.readouterr().out
    assert source.read_text(encoding="utf-8") == "Tally all rows (Vale, 2024).\n"


@pytest.mark.parametrize("response", [
    _WRAPPED.replace("  Tally", "Tally"),
    _WRAPPED + "\n\n" + _WRAPPED,
    _WRAPPED.replace("warnings: []", "warnings: []\nresulting_text: Another draft."),
    _WRAPPED.replace("warnings: []", "warnings: !!python/object:fake {}"),
    _WRAPPED.removesuffix("```"),
    "```yaml\nwarnings: []",
    "```yaml\nchanges_made: []\nrationale: Missing result.\n```",
    "```yaml\nresulting_text: ''\nchanges_made: ['changed prose']\n```",
])
@pytest.mark.parametrize("inplace", [False, True])
def test_cli_rejects_bad_wrappers_without_overwriting(tmp_path, capsys, refine_cli, response, inplace):
    source = tmp_path / "draft.md"
    output = tmp_path / "output.md"
    source.write_text("Original draft.\n", encoding="utf-8")
    output.write_text("Already reviewed.\n", encoding="utf-8")
    assert refine_cli(response, parsed=True, inplace=inplace) == 1
    assert "refinement response" in capsys.readouterr().err
    assert source.read_text(encoding="utf-8") == "Original draft.\n"
    assert output.read_text(encoding="utf-8") == "Already reviewed.\n"


@pytest.mark.parametrize("response, expected", [
    ("Keep the reading **with the plot notes**.", "Keep the reading **with the plot notes**."),
    ("Keep the reading.\n\n```yaml\nlabel: sample\n```", "Keep the reading.\n\n```yaml\nlabel: sample\n```"),
    ('{"resulting_text": "Keep the reading.", "changes_made": ["Tightened the wording."]}', "Keep the reading."),
    ("Provider note.\n\n```json\n"
     '{"resulting_text": "Keep the reading.", "changes_made": ["Tightened the wording."]}'
     "\n```\n\nEnd of response.", "Keep the reading."),
    ("```yaml\nresulting_text: ''\nchanges_made: []\nrationale: Already clear.\n```", None),
])
def test_cli_accepts_plain_prose_and_preserves_source_on_noop(tmp_path, refine_cli, response, expected):
    original = "First paragraph.  \r\n\r\n\r\nSecond paragraph.\r\n"
    (tmp_path / "draft.md").write_bytes(original.encode())
    assert refine_cli(response) == 0
    assert (tmp_path / "output.md").read_bytes() == (expected or original).encode()
