"""Behavioral regression tests for sparse-prompt expansion, voice anti-thesaurus rules,
and minimum necessary edit restraint under social/LinkedIn writing modes.
"""

from __future__ import annotations

from howlwriter.config.defaults import default_config
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.voice import TraitValue, VoiceProfile
from howlwriter.humanize.rewriter import (
    ModelHumanizerRewriter,
    _mode_specific_instructions,
)
from howlwriter.review.meaning import RealModelMeaningReviewer
from howlwriter.voice.application import render_profile
from src.control_plane.agent_execution import FakeAgentBackend


def test_anti_thesaurus_rule_rendered_in_voice_application():
    profile = VoiceProfile(
        author_name="test_author",
        version=1,
        generated_from="corpus_build",
        traits={
            "formality": TraitValue(value="high", confidence=0.9),
            "readability": TraitValue(value="advanced", confidence=0.8),
        },
    )
    rendered = render_profile(profile, mode=WritingMode.LINKEDIN)
    assert "ANTI-THESAURUS RULE" in rendered
    assert "NEVER replace normal conversational words" in rendered
    assert "substitutability" in rendered


def test_conversational_pronouns_guideline_in_voice_application():
    profile = VoiceProfile(
        author_name="test_author",
        version=1,
        generated_from="corpus_build",
    )
    rendered = render_profile(profile, mode=WritingMode.LINKEDIN)
    assert "preserve natural conversational pronouns" in rendered
    assert "enterprises" in rendered


def test_linkedin_mode_instructions_contain_anti_thesaurus_guardrails():
    instructions = _mode_specific_instructions(WritingMode.LINKEDIN)
    assert "Avoid corporate whitepaper jargon and thesaurus upgrades" in instructions
    assert "substitutability" in instructions
    assert "commoditization" in instructions
    assert "utilize" in instructions


def test_sparse_prompt_expansion_guideline_present_in_humanizer_instructions():
    doc = Document.parse("Sparse idea notes", title="sparse_idea", mode=WritingMode.LINKEDIN)
    cfg = default_config()

    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout="""```yaml
resulting_text: |
  If AI reduces software construction costs, SaaS becomes more replaceable.

  The moat shifts from code to distribution and proprietary data.

  #SoftwareEngineering #SaaS #AI
changes_made:
  - description: "Expanded sparse prompt into 2 concise paragraphs with medium hashtags"
    reason: "GENERIC_LLM_PHRASE"
rationale: "Clean sparse expansion without jargon"
verdict: "PASS"
differences: []
```""",
    )

    rewriter = ModelHumanizerRewriter()
    res = rewriter.rewrite(doc, cfg, custom_backend=fake_backend)
    assert "SoftwareEngineering" in res.document.text
    assert len(res.changes) >= 1


def test_minimum_necessary_edit_zero_change_on_strong_draft():
    strong_text = (
        "If AI makes developers faster, it also makes software easier to replace.\n\n"
        "Most SaaS products aren't defensible because their code is complicated. They're defensible "
        "because building and maintaining that code used to take fifty people two years. When that "
        "cost collapses, the software itself stops being a moat.\n\n"
        "The moat shifts to whatever AI can't generate for free: customer trust, proprietary "
        "distribution, and real integration with customer workflows."
    )

    doc = Document.parse(strong_text, title="strong_draft", mode=WritingMode.LINKEDIN)
    fake_backend = FakeAgentBackend(
        agent_id="backend",
        default_stdout=f"""```yaml
resulting_text: |
{chr(10).join('  ' + line for line in strong_text.splitlines())}
changes_made: []
rationale: "Already clean, direct human prose. Zero changes made."
verdict: "PASS"
differences: []
```""",
    )

    cfg = default_config()
    rewriter = ModelHumanizerRewriter()
    res = rewriter.rewrite(doc, cfg, custom_backend=fake_backend)
    assert len(res.changes) == 0
    assert res.document.text.strip() == strong_text.strip()


def test_meaning_reviewer_tracks_same_provider_and_independent_accurately():
    doc1 = Document.parse("SaaS is defensible through customer trust.")
    doc2 = Document.parse("SaaS remains defensible through customer trust.")

    fake_backend = FakeAgentBackend(
        agent_id="backend_a",
        default_stdout="""```yaml
verdict: "PASS"
differences: []
rationale: "Core proposition is fully preserved."
```""",
    )

    reviewer = RealModelMeaningReviewer()
    # When reviewer is from same provider as humanizer:
    res_same = reviewer.compare(
        doc1,
        doc2,
        humanizer_provider="backend_a",
        custom_backend=fake_backend,
    )
    assert res_same.verdict == "PASS"
    assert res_same.independence_status == "SAME_PROVIDER"

    # When reviewer is from a different provider:
    res_indep = reviewer.compare(
        doc1,
        doc2,
        humanizer_provider="different_provider",
        custom_backend=fake_backend,
    )
    assert res_indep.verdict == "PASS"
    assert res_indep.independence_status == "INDEPENDENT"
