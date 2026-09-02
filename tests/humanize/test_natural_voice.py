"""Focused regression tests for the Natural Voice / Humanizer refinement.

These tests exercise the deterministic detector, the model-backed humanizer
contract via a fake backend, and the CLI/config wiring for mode and voice
profile. They do not perform real model calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from howlwriter.config.loader import ConfigLoader
from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.voice import VoiceExample, VoiceProfile
from howlwriter.humanize.detector import detect
from howlwriter.humanize.rewriter import ModelHumanizerRewriter
from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from howlwriter.linting.rules import (
    AI_STYLE_CANNED_OPENING,
    AI_STYLE_CORPORATE_FILLER,
    AI_STYLE_GENERIC_INTENSIFIER,
)
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)


def _fake_backend(yaml_block: str, agent_id: str = "fake") -> FakeAgentBackend:
    return FakeAgentBackend(agent_id=agent_id, default_stdout=yaml_block)


def _setup_bridge(backend: FakeAgentBackend | None = None):
    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(domain="writing", role="humanizer", provider="fake")
    )
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)
    return backend


def _yaml_result(
    resulting_text: str,
    changes: list[dict | str] | None = None,
    rationale: str = "",
) -> str:
    changes = changes or []
    rendered_changes: list[str] = []
    for c in changes:
        if isinstance(c, dict):
            rendered_changes.append(
                f'  - description: "{c.get("description", "")}"\n'
                f'    reason: "{c.get("reason", "")}"'
            )
        else:
            rendered_changes.append(f'  - "{c}"')
    return f"""```yaml
resulting_text: |
  {resulting_text}
changes_made:
{chr(10).join(rendered_changes)}
rationale: "{rationale}"
warnings: []
```"""


@pytest.fixture(autouse=True)
def reset_bridge_after_each():
    yield
    set_howlplane_bridge(None)


# ---------------------------------------------------------------------------
# A. Clean human post
# ---------------------------------------------------------------------------

def test_clean_human_prose_passes_through_unchanged():
    text = (
        "I've spent more time debugging deployment scripts than I'd like to admit. "
        "It's the kind of work that looks simple until it isn't."
    )
    backend = _setup_bridge(
        _fake_backend(_yaml_result(text, [], "Already natural."))
    )

    config = HowlWriterConfig(humanization_strength="medium")
    doc = Document.parse(text, title="clean")
    result = ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    assert result.document.text == text
    assert result.changes == []


# ---------------------------------------------------------------------------
# B. Technical human post
# ---------------------------------------------------------------------------

def test_technical_human_preserves_numbers_and_terms():
    original = (
        "We deploy around 60 applications through the same release model. "
        "The change may reduce latency."
    )
    backend = _setup_bridge(
        _fake_backend(_yaml_result(original, [], "Technical terms kept."))
    )

    config = HowlWriterConfig(humanization_strength="medium")
    doc = Document.parse(original, title="technical")
    result = ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    assert "60" in result.document.text
    assert "applications" in result.document.text
    assert "release model" in result.document.text
    assert "may reduce" in result.document.text


# ---------------------------------------------------------------------------
# C. Moderate generic AI post
# ---------------------------------------------------------------------------

def test_moderate_generic_ai_cleanup_records_reasons():
    original = (
        "Furthermore, the release process was slow. "
        "We had to optimize the pipeline to unlock value."
    )
    revised = "The release process was slow. We streamlined the pipeline."
    backend = _setup_bridge(
        _fake_backend(
            _yaml_result(
                revised,
                [
                    {
                        "description": "Removed mechanical transition 'Furthermore'.",
                        "reason": "CANNED_TRANSITION",
                    },
                    {
                        "description": "Replaced 'unlock value' with direct wording.",
                        "reason": "CORPORATE_FILLER",
                    },
                ],
                "Removed filler while preserving facts.",
            )
        )
    )

    config = HowlWriterConfig(humanization_strength="medium")
    doc = Document.parse(original, title="moderate")
    result = ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    assert result.document.text == revised
    assert len(result.changes) == 2
    assert result.changes[0].reason == "CANNED_TRANSITION"
    assert result.changes[1].reason == "CORPORATE_FILLER"


# ---------------------------------------------------------------------------
# D. Heavy generic AI post
# ---------------------------------------------------------------------------

def test_heavy_generic_ai_reduces_canned_opening_and_filler():
    original = (
        "In today's rapidly evolving technological landscape, organizations are "
        "increasingly leveraging automation to unlock unprecedented efficiencies. "
        "It is clear that this is a pivotal moment."
    )
    revised = (
        "Organizations are using automation to make routine work faster. "
        "This matters now."
    )
    backend = _setup_bridge(
        _fake_backend(
            _yaml_result(
                revised,
                [{"description": "Simplified", "reason": "GENERIC_LLM_PHRASE"}],
            )
        )
    )

    config = HowlWriterConfig(humanization_strength="high")
    doc = Document.parse(original, title="heavy")
    result = ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    assert "In today's rapidly evolving" not in result.document.text
    assert "unlock" not in result.document.text
    assert "pivotal" not in result.document.text


# ---------------------------------------------------------------------------
# E. Over-polished post
# ---------------------------------------------------------------------------

def test_overpolished_post_keeps_direct_wording():
    original = (
        "The team endeavored to facilitate a seamless integration, ultimately "
        "elevating the user experience to unprecedented levels."
    )
    revised = "We wanted the integration to feel invisible."
    backend = _setup_bridge(
        _fake_backend(
            _yaml_result(
                revised,
                [
                    {
                        "description": "Simplified over-polished phrasing",
                        "reason": "OVERPOLISHED",
                    }
                ],
            )
        )
    )

    config = HowlWriterConfig(humanization_strength="high")
    doc = Document.parse(original, title="overpolished")
    result = ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    assert result.document.text == revised


# ---------------------------------------------------------------------------
# F. Personal opinion post
# ---------------------------------------------------------------------------

def test_personal_opinion_preserves_first_person_and_roughness():
    original = (
        "I think the new rollout is a mess. We told them the config was wrong, "
        "and they shipped it anyway. Ugh."
    )
    backend = _setup_bridge(
        _fake_backend(_yaml_result(original, [], "Voice preserved."))
    )

    config = HowlWriterConfig(humanization_strength="medium")
    doc = Document.parse(original, title="opinion")
    result = ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    assert "I think" in result.document.text or "I" in result.document.text
    assert "Ugh" in result.document.text


# ---------------------------------------------------------------------------
# G. Academic paragraph
# ---------------------------------------------------------------------------

def test_academic_mode_keeps_formal_tone_and_citations():
    original = (
        "However, Smith (2020) argued that the effect may be moderated by "
        "sample characteristics. Consequently, further replication is warranted."
    )
    revised = (
        "However, Smith (2020) argued that the effect may be moderated by "
        "sample characteristics; further replication is warranted."
    )
    backend = _setup_bridge(
        _fake_backend(
            _yaml_result(
                revised,
                [
                    {
                        "description": "Combined sentences without altering hedging",
                        "reason": "RHYTHM_NORMALIZATION",
                    }
                ],
            )
        )
    )

    config = HowlWriterConfig(
        humanization_strength="medium",
        banned_patterns=["generic_transition"],
    )
    doc = Document.parse(original, title="academic", mode=WritingMode.ACADEMIC)
    result = ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    assert "Smith (2020)" in result.document.text
    assert "may be moderated" in result.document.text
    assert "Consequently" not in result.document.text


# ---------------------------------------------------------------------------
# Specific regression cases
# ---------------------------------------------------------------------------

def test_canned_opening_is_detected():
    text = (
        "In today's rapidly evolving technological landscape, organizations are "
        "increasingly leveraging automation to unlock unprecedented efficiencies."
    )
    config = HowlWriterConfig(banned_patterns=["canned_opening"])
    doc = Document.parse(text, title="t")
    matches = detect(doc, config)
    assert any(m.rule_code == AI_STYLE_CANNED_OPENING for m in matches)


def test_corporate_filler_and_intensifier_are_detected():
    text = (
        "This is a crucial, transformative opportunity to leverage synergy and "
        "unlock scalable value."
    )
    config = HowlWriterConfig(
        banned_patterns=["generic_intensifier", "corporate_filler"]
    )
    doc = Document.parse(text, title="t")
    matches = detect(doc, config)
    codes = {m.rule_code for m in matches}
    assert AI_STYLE_GENERIC_INTENSIFIER in codes
    assert AI_STYLE_CORPORATE_FILLER in codes


def test_voice_profile_is_loaded_from_path(tmp_path: Path):
    profile = VoiceProfile(
        author_name="Author A",
        contraction_rate=0.25,
        sentence_length_mean=12.0,
        representative_examples=[VoiceExample(text="Yeah, we shipped it.")],
        structural_notes="Short paragraphs, frequent contractions.",
    )
    path = tmp_path / "voice.json"
    path.write_text(profile.to_json(), encoding="utf-8")

    from howlwriter.humanize.rewriter import (
        _load_voice_profile,
        _render_voice_profile,
    )

    loaded = _load_voice_profile(str(path))
    assert loaded is not None
    assert loaded.author_name == "Author A"
    rendered = _render_voice_profile(loaded)
    assert "Author A" in rendered
    assert "contraction_rate" in rendered
    assert "Yeah, we shipped it." in rendered


def test_humanizer_prompt_contains_mode_instructions():
    text = "Some prose."
    backend = _fake_backend(_yaml_result(text, [], "ok"))
    _setup_bridge(backend)

    config = HowlWriterConfig(humanization_strength="medium")
    doc = Document.parse(text, title="t", mode=WritingMode.LINKEDIN)
    ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    prompt = backend.executed_calls[-1]["prompt"] if backend.executed_calls else ""
    assert "LINKEDIN / SHORT-FORM MODE" in prompt
    assert "direct opening" in prompt


def test_humanizer_prompt_contains_voice_profile_text(tmp_path: Path):
    profile = VoiceProfile(
        author_name="Author B",
        contraction_rate=0.4,
        representative_examples=[VoiceExample(text="I don't know, honestly.")],
    )
    path = tmp_path / "voice_b.json"
    path.write_text(profile.to_json(), encoding="utf-8")

    text = "Some prose."
    backend = _fake_backend(_yaml_result(text, [], "ok"))
    _setup_bridge(backend)

    config = HowlWriterConfig(
        humanization_strength="medium", voice_profile=str(path)
    )
    doc = Document.parse(text, title="t")
    ModelHumanizerRewriter().rewrite(doc, config, custom_backend=backend)

    prompt = backend.executed_calls[-1]["prompt"] if backend.executed_calls else ""
    assert "Author B" in prompt
    assert "I don't know, honestly." in prompt
    assert "do NOT optimize for AI-detector scores" in prompt


# ---------------------------------------------------------------------------
# Mode separation
# ---------------------------------------------------------------------------

def test_linkedin_mode_instructions_differ_from_academic():
    backend = _fake_backend(_yaml_result("text", [], "ok"))
    _setup_bridge(backend)

    linkedin_doc = Document.parse("text", title="t", mode=WritingMode.LINKEDIN)
    ModelHumanizerRewriter().rewrite(
        linkedin_doc,
        HowlWriterConfig(humanization_strength="high"),
        custom_backend=backend,
    )
    linkedin_prompt = (
        backend.executed_calls[-1]["prompt"] if backend.executed_calls else ""
    )

    backend2 = _fake_backend(_yaml_result("text", [], "ok"))
    _setup_bridge(backend2)

    academic_doc = Document.parse("text", title="t", mode=WritingMode.ACADEMIC)
    ModelHumanizerRewriter().rewrite(
        academic_doc,
        HowlWriterConfig(humanization_strength="medium"),
        custom_backend=backend2,
    )
    academic_prompt = (
        backend2.executed_calls[-1]["prompt"] if backend2.executed_calls else ""
    )

    assert "LINKEDIN / SHORT-FORM MODE" in linkedin_prompt
    assert "ACADEMIC MODE" in academic_prompt
    assert "scholarly tone" in academic_prompt


# ---------------------------------------------------------------------------
# Change reason taxonomy parsing
# ---------------------------------------------------------------------------

def test_dict_change_records_include_reason():
    original = "Furthermore, we deployed."
    revised = "We deployed."
    backend = _setup_bridge(
        _fake_backend(
            _yaml_result(
                revised,
                [
                    {
                        "description": "Removed 'Furthermore'",
                        "reason": "CANNED_TRANSITION",
                    }
                ],
            )
        )
    )

    doc = Document.parse(original, title="t")
    result = ModelHumanizerRewriter().rewrite(doc, HowlWriterConfig(), custom_backend=backend)
    assert len(result.changes) == 1
    assert result.changes[0].reason == "CANNED_TRANSITION"


def test_string_change_records_default_reason_is_empty():
    original = "Robotic prose."
    revised = "Better prose."
    backend = _setup_bridge(_fake_backend(_yaml_result(revised, ["made it better"])))

    doc = Document.parse(original, title="t")
    result = ModelHumanizerRewriter().rewrite(doc, HowlWriterConfig(), custom_backend=backend)
    assert result.changes[0].description == "made it better"
    assert result.changes[0].reason == ""


# ---------------------------------------------------------------------------
# Config/CLI wiring
# ---------------------------------------------------------------------------

def test_config_loader_linkedin_mode_sets_humanization_strength():
    config = ConfigLoader().load(mode=WritingMode.LINKEDIN)
    assert config.humanization_strength == "high"
    assert config.research_depth == "none"


def test_config_loader_academic_mode_keeps_formal_defaults():
    config = ConfigLoader().load(mode=WritingMode.ACADEMIC)
    assert config.research_depth == "deep"
    assert config.citation_style == "apa7"
