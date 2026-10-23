"""Academic genres: one voice, different conventions."""

from __future__ import annotations

import json

import pytest

from howlwriter.academic.spec import AssignmentSpec
from howlwriter.domain.genres import (
    GENRE_FORMULAIC_OPENING,
    GENRE_HEADINGS,
    GENRE_PAPER_REGISTER,
    GENRE_THIRD_PERSON_PEER,
    AcademicGenre,
    check_genre_conformance,
    parse_genre,
)
from howlwriter.domain.modes import WritingMode, parse_mode
from howlwriter.voice.application import MODE_CONTEXTS


def _codes(text, genre):
    return {f.code for f in check_genre_conformance(text, genre)}


class TestResolution:
    @pytest.mark.parametrize("name", ["academic_discussion", "academic_peer_reply", "academic_research_paper",
                                      "Academic-Peer-Reply"])
    def test_genres_keep_the_academic_register(self, name):
        assert parse_genre(name) is not None
        mode = parse_mode(name)
        assert mode is WritingMode.ACADEMIC
        assert MODE_CONTEXTS[mode] == "academic"  # same register, so the same voice profile

    def test_unknown_names_are_still_custom(self):
        assert parse_mode("academic_poetry") is WritingMode.CUSTOM
        assert parse_genre("academic_poetry") is None

    def test_existing_modes_unchanged(self):
        assert parse_mode("academic") is WritingMode.ACADEMIC
        assert parse_mode("casual") is WritingMode.CUSTOM or parse_mode("casual") is WritingMode.CASUAL


class TestConformance:
    def test_discussion_post_with_headings_is_flagged(self):
        assert GENRE_HEADINGS in _codes("## Introduction\nAI belongs in risk management.", AcademicGenre.DISCUSSION)

    def test_clean_discussion_post_passes(self):
        text = "AI belongs inside the existing risk process. I would inventory systems and assign owners."
        assert check_genre_conformance(text, "academic_discussion") == []

    def test_research_paper_may_use_headings(self):
        assert check_genre_conformance("## Method\nWe sampled.\n\n## Results\nIt worked.", "academic_research_paper") == []

    def test_references_heading_is_not_a_body_heading(self):
        text = "I would inventory systems.\n\n**References**\n\nOWASP. (2025). Title."
        assert check_genre_conformance(text, "academic_discussion") == []
        text = "I would inventory systems.\n\n# References\n\nOWASP. (2025). Title."
        assert check_genre_conformance(text, "academic_peer_reply") == []

    @pytest.mark.parametrize("opening", [
        "Great post, Peter.", "I completely agree with your take.", "Thank you for sharing this.",
        "Excellent points about contracts.", "This is a great overview of vendor risk.",
        "I really enjoyed reading your post.",
    ])
    def test_formulaic_peer_openings_are_flagged(self, opening):
        assert GENRE_FORMULAIC_OPENING in _codes(opening + " You say vendors need contracts.", "academic_peer_reply")

    def test_direct_engagement_opening_passes(self):
        text = "You note the framework is voluntary, and that limits what a vendor owes you."
        assert check_genre_conformance(text, "academic_peer_reply") == []

    def test_formulaic_opening_is_only_a_peer_reply_rule(self):
        assert GENRE_FORMULAIC_OPENING not in _codes("Great post on this topic, honestly.", "academic_discussion")

    def test_third_person_review_of_the_peer_is_flagged(self):
        text = "Peter Ebot argues that contracts should define acceptable AI use. The point limits vendors."
        assert GENRE_THIRD_PERSON_PEER in _codes(text, "academic_peer_reply")

    def test_third_person_naming_with_direct_address_is_fine(self):
        text = "Peter Ebot argues that contracts should define acceptable AI use, and you are right that it matters."
        assert GENRE_THIRD_PERSON_PEER not in _codes(text, "academic_peer_reply")

    def test_paper_register_in_a_reply_is_flagged(self):
        assert GENRE_PAPER_REGISTER in _codes("In conclusion, contracts matter.", "academic_peer_reply")
        assert GENRE_PAPER_REGISTER in _codes("This paper examines vendors.", "academic_discussion")

    def test_no_genre_means_no_findings(self):
        assert check_genre_conformance("## Heading\nGreat post.", None) == []


class TestWriterPrompt:
    @staticmethod
    def _prompt(genre):
        from src.control_plane.agent_execution import FakeAgentBackend

        from howlwriter.academic.writer import ModelAcademicWriter

        backend = FakeAgentBackend(agent_id="fake_writer", default_stdout="""```yaml
body_markdown: |
  Text (Tabassi, 2023).
claims_made: []
warnings: []
```""")
        spec = AssignmentSpec(title="T", topic="Topic", target_words=250, genre=genre, outline=["Point one"])
        ModelAcademicWriter().draft_paper(spec, [], custom_backend=backend)
        return backend.executed_calls[0]["prompt"]

    def test_default_prompt_is_the_research_paper_prompt(self):
        prompt = self._prompt("")
        assert "rigorous, high-quality academic research paper" in prompt
        assert "Use clear markdown headings for major outline sections." in prompt
        assert "GENRE:" not in prompt

    def test_research_paper_genre_keeps_headings(self):
        prompt = self._prompt("academic_research_paper")
        assert "GENRE: ACADEMIC RESEARCH PAPER" in prompt
        assert "Use clear markdown headings" in prompt

    def test_peer_reply_prompt_asks_for_a_conversation_without_headings(self):
        prompt = self._prompt("academic_peer_reply")
        assert "GENRE: PEER REPLY" in prompt
        assert "Great post" in prompt  # named only as something to avoid
        assert "no headings" in prompt
        assert "rigorous, high-quality academic research paper" not in prompt
        assert "Use clear markdown headings for major outline sections." not in prompt

    def test_discussion_prompt_asks_for_a_position(self):
        prompt = self._prompt("academic_discussion")
        assert "GENRE: ACADEMIC DISCUSSION POST" in prompt
        assert "no section headings" in prompt


class TestSpec:
    def test_default_genre_is_empty_and_parses_to_none(self):
        spec = AssignmentSpec(title="T", topic="x")
        assert spec.genre == "" and parse_genre(spec.genre) is None

    def test_spec_round_trips_genre(self):
        spec = AssignmentSpec(title="T", topic="x", genre="academic_peer_reply")
        assert AssignmentSpec.from_dict(json.loads(json.dumps(spec.to_dict()))).genre == "academic_peer_reply"


class TestVoiceRouting:
    """A genre must reach the same voice profile as plain academic mode, never fall to 'unknown'."""

    @pytest.mark.parametrize("name", ["academic_discussion", "academic_peer_reply", "academic_research_paper"])
    def test_genre_routes_to_the_academic_profile_context(self, name):
        from howlwriter.voice.selection import context_for_mode

        assert context_for_mode(name) == context_for_mode("academic") == "academic"

    def test_base_mode_name_folds_only_genres(self):
        from howlwriter.domain.genres import base_mode_name

        assert base_mode_name("Academic_Peer_Reply") == "academic"
        assert base_mode_name("professional") == "professional"
        assert base_mode_name(None) == ""

    def test_choose_profile_uses_the_academic_context_for_a_genre(self, tmp_path):
        from howlwriter.evaluation.personal import choose_profile

        choice = choose_profile("Some text. " * 40, mode="academic_peer_reply", identities_root=tmp_path)
        assert choice.context == "academic"
