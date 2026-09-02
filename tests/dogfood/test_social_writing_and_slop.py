"""Tests for social writing, LinkedIn anti-slop rules, and truthmode opinion preservation."""

from __future__ import annotations

from howlwriter.config.defaults import default_config
from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.linting import rules
from howlwriter.linting.engine import LintEngine
from howlwriter.pipeline.howl import run_howl_pipeline
from src.control_plane.agent_execution import FakeAgentBackend


def _codes(text: str, config: HowlWriterConfig | None = None) -> list[str]:
    cfg = config or default_config()
    doc = Document.parse(text, title="test_social", mode=WritingMode.LINKEDIN)
    matches = LintEngine().run(doc, cfg)
    return [m.rule_code for m in matches]


def test_engagement_bait_detected():
    text = "AI is changing how we build software.\n\nAgree? Drop a comment below!"
    codes = _codes(text)
    assert rules.AI_STYLE_ENGAGEMENT_BAIT in codes


def test_fake_rhetorical_hook_detected():
    text = (
        "Let that sink in.\n\nHere's the thing about AI commoditization: "
        "it shifts the moat to distribution."
    )
    codes = _codes(text)
    assert rules.AI_STYLE_FAKE_RHETORICAL_HOOK in codes


def test_hashtag_spam_detected_when_exceeds_limit():
    text = (
        "Building tools for developers.\n\n"
        "#AI #SaaS #Tech #Coding #Startups #Engineering #Cloud #Innovation"
    )
    codes = _codes(text)
    assert rules.AI_STYLE_HASHTAG_SPAM in codes


def test_modest_hashtags_not_flagged():
    text = "Building tools for developers.\n\n#SoftwareEngineering #AI #SaaS"
    codes = _codes(text)
    assert rules.AI_STYLE_HASHTAG_SPAM not in codes


def test_emoji_bullets_detected():
    text = (
        "Key moat factors:\n"
        "🚀 Distribution channels\n"
        "🔥 Customer relationships\n"
        "💡 Proprietary data"
    )
    codes = _codes(text)
    assert rules.AI_STYLE_EMOJI_BULLETS in codes


def test_motivational_slop_detected():
    text = "The future belongs to those who embrace the future and unlock their true potential."
    codes = _codes(text)
    assert rules.AI_STYLE_MOTIVATIONAL_SLOP in codes


def test_paragraph_length_symmetry_does_not_flag_short_social_post():
    # 4 short paragraphs with 1-2 sentences each (natural for social posts)
    text = (
        "If AI makes developers replaceable, it also makes software easier to clone.\n\n"
        "That does not mean SaaS is dead. It means implementation alone is no longer a moat.\n\n"
        "Moats move toward distribution, proprietary data, and customer trust.\n\n"
        "Companies should consider this before celebrating."
    )
    codes = _codes(text)
    assert rules.AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY not in codes


def test_causal_argument_preservation_in_pipeline(tmp_path):
    draft = tmp_path / "post.md"
    draft.write_text(
        "If software becomes cheaper to produce with AI, implementation is less of a moat.\n\n"
        "That shifts differentiation to proprietary data and customer relationships."
    )

    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout="""```yaml
resulting_text: |
  If software becomes cheaper to produce with AI, implementation is less of a moat.

  That shifts differentiation to proprietary data and customer relationships.

  #SoftwareEngineering #AI #SaaS
changes_made: []
rationale: "Clean causal argument preserved with standard hashtags."
verdict: "PASS"
differences: []
```""",
    )

    cfg = default_config()
    res = run_howl_pipeline(
        draft,
        cfg,
        custom_backend=fake_backend,
        writing_mode=WritingMode.LINKEDIN,
    )

    assert res.report.status == "READY"
    assert res.report.banned_words == 0
    assert "SoftwareEngineering" in res.final_document.text
