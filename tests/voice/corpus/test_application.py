"""Applying a voice: resolution, layering, anti-cloning, and precedence.

The invariants here are the ones a user would notice if they broke -- a voice
that silently rewrote a citation, overrode a page limit, or turned every post
into the same shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.voice import (
    TraitValue,
    VoiceContext,
    VoiceExample,
    VoiceOverrides,
    VoiceProfile,
)
from howlwriter.humanize.rewriter import _load_voice_profile, _render_voice_profile
from howlwriter.voice.application import (
    MODE_CONTEXTS,
    context_for_mode,
    render_profile,
)
from howlwriter.voice.corpus.build import build_voice
from howlwriter.voice.corpus.resolve import (
    profile_reference,
    resolve_named_voice,
    resolve_voice_option,
)
from howlwriter.voice.corpus.store import OVERRIDES_FILE, VoiceStore


def _corpus_profile(store_root: Path, build_corpus, name: str = "subject") -> VoiceProfile:
    return build_voice(name, [build_corpus(14)], store_root=store_root,
                       deterministic_only=True).profile


# --- named voice resolution -------------------------------------------

def test_a_named_voice_resolves_to_its_profile(store_root, build_corpus):
    _corpus_profile(store_root, build_corpus, "jane")
    profile = resolve_named_voice("jane", root=store_root)
    assert profile.profile_name == "jane"
    assert profile.is_corpus_built


def test_a_missing_voice_names_the_ones_that_exist(store_root, build_corpus):
    _corpus_profile(store_root, build_corpus, "jane")
    with pytest.raises(FileNotFoundError) as error:
        resolve_named_voice("nobody", root=store_root)
    assert "jane" in str(error.value)
    assert "voice build" in str(error.value)


def test_profile_reference_points_at_the_profile_file(store_root, build_corpus):
    _corpus_profile(store_root, build_corpus, "jane")
    reference = profile_reference("jane", root=store_root)
    assert Path(reference).is_file()
    assert Path(reference).name == "profile.json"


def test_voice_profile_path_still_works_unchanged(tmp_path):
    """Backwards compatibility: the pre-existing flag is untouched."""
    legacy = VoiceProfile(
        author_name="A Writer",
        sentence_length_mean=18.5,
        contraction_rate=0.4,
        preferred_phrases=["as it happens"],
        representative_examples=[VoiceExample(text="A hand-picked sentence.")],
    )
    path = tmp_path / "voice.json"
    path.write_text(legacy.to_json(), encoding="utf-8")

    assert resolve_voice_option(voice=None, voice_profile=str(path)) == str(path)
    loaded = _load_voice_profile(str(path))
    assert loaded.author_name == "A Writer"
    assert loaded.sentence_length_mean == 18.5


def test_a_legacy_profile_renders_exactly_as_before(tmp_path):
    legacy = VoiceProfile(
        author_name="A Writer",
        sentence_length_mean=18.5,
        preferred_phrases=["as it happens"],
        representative_examples=[VoiceExample(text="A hand-picked sentence.")],
    )
    rendered = render_profile(legacy)
    assert "author_name: A Writer" in rendered
    assert "sentence_length_mean: 18.5" in rendered
    assert "preferred_phrases: as it happens" in rendered
    assert "A hand-picked sentence." in rendered


def test_both_flags_at_once_is_an_error_rather_than_a_silent_choice(store_root, build_corpus, tmp_path):
    _corpus_profile(store_root, build_corpus, "jane")
    path = tmp_path / "other.json"
    path.write_text(VoiceProfile(author_name="Other").to_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="alternatives"):
        resolve_voice_option(voice="jane", voice_profile=str(path), root=store_root)


def test_neither_flag_resolves_to_nothing():
    assert resolve_voice_option(voice=None, voice_profile=None) is None


def test_a_nonexistent_path_is_tolerated_as_an_author_label():
    assert _load_voice_profile("Some Author Name") is None
    assert _load_voice_profile(None) is None


def test_a_corrupt_profile_file_does_not_crash_the_humanizer(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert _load_voice_profile(str(path)) is None


def test_overrides_are_reattached_when_loading_from_a_voice_directory(store_root, build_corpus):
    _corpus_profile(store_root, build_corpus, "jane")
    store = VoiceStore("jane", root=store_root)
    (store.directory / OVERRIDES_FILE).write_text(
        'preserve:\n  - long flowing sentences\navoid: []\ntraits: {}\nnotes: ""\n',
        encoding="utf-8",
    )
    loaded = _load_voice_profile(str(store.directory / "profile.json"))
    assert loaded.overrides.preserve == ["long flowing sentences"]


# --- mode to context mapping ------------------------------------------

def test_each_mode_maps_to_a_context():
    for mode in WritingMode:
        assert MODE_CONTEXTS[mode] in ("academic", "professional", "general")


def test_linkedin_and_academic_draw_on_different_contexts():
    assert context_for_mode(WritingMode.LINKEDIN) == "professional"
    assert context_for_mode(WritingMode.ACADEMIC) == "academic"
    assert context_for_mode(WritingMode.CASUAL) == "general"


def test_an_unknown_mode_falls_back_rather_than_crashing():
    assert context_for_mode("not-a-mode") == "general"
    assert context_for_mode(None) == "general"
    assert context_for_mode("academic") == "academic"


# --- rendering: layering and anti-cloning ------------------------------

def _profile_with_contexts() -> VoiceProfile:
    return VoiceProfile(
        author_name="",
        profile_name="subject",
        version=1,
        generated_from="corpus_build",
        traits={
            "directness": TraitValue(value="high", confidence=0.9, supporting_documents=20),
            "contractions": TraitValue(value="common", confidence=0.8, supporting_documents=20),
        },
        contexts={
            "academic": VoiceContext(
                name="academic",
                traits={"contractions": TraitValue(value="rare", confidence=0.8, supporting_documents=12)},
                document_count=12, word_count=20000, confidence=0.8,
            ),
            "professional": VoiceContext(
                name="professional",
                traits={"contractions": TraitValue(value="frequent", confidence=0.1, supporting_documents=2)},
                document_count=2, word_count=800, confidence=0.1,
            ),
        },
    )


def test_the_context_for_the_mode_is_the_one_rendered():
    profile = _profile_with_contexts()
    academic = render_profile(profile, WritingMode.ACADEMIC)
    assert "IN ACADEMIC WRITING" in academic
    assert "IN PROFESSIONAL WRITING" not in academic


def test_global_and_context_are_composed_not_replaced():
    rendered = render_profile(_profile_with_contexts(), WritingMode.ACADEMIC)
    assert "GLOBAL TENDENCIES" in rendered
    assert "directness: high" in rendered           # global survives
    assert "contractions: rare" in rendered         # context adjusts
    assert "do not replace them" in rendered.lower() or "not replace them" in rendered


def test_weak_context_evidence_cannot_overpower_the_global_tendency():
    """The professional context here rests on two documents."""
    rendered = render_profile(_profile_with_contexts(), WritingMode.LINKEDIN)
    assert "possibly frequent" in rendered
    assert "thin evidence" in rendered
    assert "do not let this override the global tendency" in rendered


def test_a_missing_context_falls_back_to_global_explicitly():
    profile = VoiceProfile(
        author_name="", profile_name="x", version=1, generated_from="corpus_build",
        traits={"directness": TraitValue(value="high", confidence=0.9)},
    )
    rendered = render_profile(profile, WritingMode.ACADEMIC)
    assert "No academic context was built" in rendered
    assert "directness: high" in rendered


def test_rendering_frames_traits_as_a_distribution_not_a_template():
    rendered = render_profile(_profile_with_contexts(), WritingMode.LINKEDIN)
    assert "distribution, not a template" in rendered
    assert "Match the author's natural VARIATION" in rendered
    assert "Never invent a signature opening" in rendered
    assert "same trait should look different" in rendered


def test_rendering_states_that_voice_never_outranks_facts_or_constraints():
    rendered = render_profile(_profile_with_contexts(), WritingMode.ACADEMIC)
    assert "must not change facts" in rendered
    assert "citations" in rendered
    assert "identifiers" in rendered
    assert "outrank this profile" in rendered


def test_rendering_says_zero_change_is_acceptable():
    rendered = render_profile(_profile_with_contexts(), WritingMode.LINKEDIN)
    assert "change nothing" in rendered


def test_a_corpus_profile_never_renders_a_phrase_bank(store_root, build_corpus):
    profile = _corpus_profile(store_root, build_corpus)
    rendered = render_profile(profile, WritingMode.LINKEDIN)
    assert "representative_examples" not in rendered
    assert "preferred_phrases" not in rendered
    assert "favorite" not in rendered.lower()


def test_low_confidence_traits_are_marked_rather_than_presented_as_fact():
    profile = VoiceProfile(
        author_name="", profile_name="x", version=1, generated_from="corpus_build",
        traits={"humor": TraitValue(value="frequent", confidence=0.2, supporting_documents=2)},
    )
    rendered = render_profile(profile, WritingMode.CASUAL)
    assert "low confidence" in rendered
    assert "weak hint" in rendered


def test_user_overrides_are_rendered_as_outranking_everything():
    profile = _profile_with_contexts()
    profile.overrides = VoiceOverrides(
        preserve=["long flowing sentences"],
        avoid=["overly polished conclusions"],
        traits={"directness": "medium"},
    )
    rendered = render_profile(profile, WritingMode.LINKEDIN)
    assert "outrank everything above" in rendered
    assert "preserve: long flowing sentences" in rendered
    assert "avoid: overly polished conclusions" in rendered
    assert "directness must be medium" in rendered


def test_a_thin_corpus_is_disclosed_in_the_prompt(store_root, corpus_dir):
    from tests.voice.corpus.conftest import synthetic_prose
    for index in range(6):
        (corpus_dir / f"d{index}.md").write_text(synthetic_prose(index, 2), encoding="utf-8")
    profile = build_voice("thin", [corpus_dir], store_root=store_root,
                          deterministic_only=True).profile
    rendered = render_profile(profile, WritingMode.CASUAL)
    assert "EVIDENCE:" in rendered
    if profile.corpus_summary.sufficiency in ("limited", "insufficient"):
        assert "prefer leaving good prose alone" in rendered


def test_rendering_a_missing_profile_is_the_string_none():
    assert render_profile(None) == "None"
    assert _render_voice_profile(None) == "None"


def test_effective_trait_layering_order():
    profile = _profile_with_contexts()
    assert profile.effective_trait("contractions").value == "common"                # global
    assert profile.effective_trait("contractions", "academic").value == "rare"      # context
    profile.overrides = VoiceOverrides(traits={"contractions": "never"})
    assert profile.effective_trait("contractions", "academic").value == "never"     # user
    assert profile.effective_trait("contractions", "academic").source == "user"


# --- the humanizer receives it correctly -------------------------------

def test_the_humanizer_renders_the_context_for_the_document_mode(store_root, build_corpus):
    profile = _corpus_profile(store_root, build_corpus, "jane")
    profile.contexts["academic"] = VoiceContext(
        name="academic",
        traits={"contractions": TraitValue(value="rare", confidence=0.9)},
        document_count=10, word_count=15000, confidence=0.9,
    )
    store = VoiceStore("jane", root=store_root)
    (store.directory / "profile.json").write_text(profile.to_json(), encoding="utf-8")

    loaded = _load_voice_profile(str(store.directory / "profile.json"))
    academic = _render_voice_profile(loaded, WritingMode.ACADEMIC)
    linkedin = _render_voice_profile(loaded, WritingMode.LINKEDIN)
    assert "IN ACADEMIC WRITING" in academic
    assert "IN ACADEMIC WRITING" not in linkedin


def test_config_carries_the_voice_through_unchanged(store_root, build_corpus):
    _corpus_profile(store_root, build_corpus, "jane")
    reference = resolve_voice_option(voice="jane", voice_profile=None, root=store_root)
    config = HowlWriterConfig(voice_profile=reference)
    assert _load_voice_profile(config.voice_profile).profile_name == "jane"


def test_a_shared_style_is_a_distinct_type_from_a_personal_voice(store_root, build_corpus):
    corpus = build_corpus(14)
    personal = build_voice("person", [corpus], store_root=store_root,
                           deterministic_only=True).profile
    shared = build_voice("house-style", [corpus], store_root=store_root,
                         deterministic_only=True, profile_type="shared_style").profile
    assert personal.profile_type == "personal_voice"
    assert shared.profile_type == "shared_style"
    assert json.loads(personal.to_json())["profile_type"] == "personal_voice"


def test_structural_variance_rendered_in_voice_application():
    profile = VoiceProfile(
        author_name="test_author",
        version=1,
        generated_from="corpus_build",
        distributions=_corpus_distribution(),
    )
    rendered = render_profile(profile, WritingMode.LINKEDIN)
    assert "CONTEXTUAL STRUCTURAL VARIANCE" in rendered
    assert "DISTRIBUTION OVER CHECKLIST" in rendered
    assert "ANTI-HYPER-SYMMETRY" in rendered
    assert "paragraph length:" in rendered
    assert "sentence length:" in rendered


def _corpus_distribution():
    from howlwriter.domain.voice import VoiceDistributions
    return VoiceDistributions(
        sentence_length_mean=18.0,
        sentence_length_p10=8.0,
        sentence_length_p90=28.0,
        paragraph_words_mean=55.0,
        paragraph_words_p10=22.0,
        paragraph_words_p90=85.0,
        paragraph_sentences_mean=2.5,
        paragraph_sentences_p10=1.0,
        paragraph_sentences_p90=4.0,
        single_sentence_paragraph_rate=0.25,
        short_sentence_rate=0.20,
        long_sentence_rate=0.15,
    )


# --- structural spread must never render as a degenerate range --------


def _profile_with(distributions):
    return VoiceProfile(
        author_name="test_author",
        version=1,
        generated_from="corpus_build",
        distributions=distributions,
    )


def test_zeroed_percentiles_fall_back_to_the_mean_instead_of_rendering_a_range():
    """A 0-0 range is a contradiction, not a measurement.

    Zero is what a percentile becomes when it was never measured. Rendering it
    produced "paragraph length: typically 0-0 words (mean ~80 words)", which
    tells the model two incompatible things and buries the usable number inside
    the broken one.
    """
    from howlwriter.domain.voice import VoiceDistributions

    rendered = render_profile(
        _profile_with(VoiceDistributions(
            sentence_length_mean=19.9,
            sentence_length_p10=0.0,
            sentence_length_p90=0.0,
            paragraph_words_mean=80.0,
            paragraph_words_p10=0.0,
            paragraph_words_p90=0.0,
            paragraph_sentences_mean=4.0,
            paragraph_sentences_p10=0.0,
            paragraph_sentences_p90=0.0,
        )),
        WritingMode.LINKEDIN,
    )
    assert "0-0" not in rendered
    assert "paragraph length: around 80 words on average" in rendered
    assert "paragraph sentence count" not in rendered


def test_a_real_spread_still_renders_as_a_range():
    from howlwriter.domain.voice import VoiceDistributions

    rendered = render_profile(
        _profile_with(VoiceDistributions(
            paragraph_words_mean=55.0,
            paragraph_words_p10=22.0,
            paragraph_words_p90=85.0,
            paragraph_sentences_mean=2.5,
            paragraph_sentences_p10=1.0,
            paragraph_sentences_p90=4.0,
        )),
        WritingMode.LINKEDIN,
    )
    assert "typically 22-85 words" in rendered
    assert "typically 1-4 sentences" in rendered


def test_an_old_profile_without_percentiles_still_renders():
    """Profiles written before the spread fields existed must keep working."""
    profile = VoiceProfile.from_dict({
        "author_name": "x",
        "version": 1,
        "generated_from": "corpus_build",
        "distributions": {
            "sentence_length_mean": 18.0,
            "sentence_length_p10": 8.0,
            "sentence_length_p90": 28.0,
            "paragraph_words_mean": 55.0,
        },
    })
    rendered = render_profile(profile, WritingMode.LINKEDIN)
    assert "0-0" not in rendered
    assert "typically 8-28 words" in rendered
    assert "around 55 words on average" in rendered


# --- a split corpus must not render as an absolute --------------------


def test_a_trait_the_corpus_disagrees_on_renders_as_varying():
    """A plurality label is not a property of the author.

    Fourteen documents using parentheses and fourteen not still yields a single
    winning label. Stating it flatly is what put a parenthetical into every
    generated post, so the split has to survive into the prompt.
    """
    profile = VoiceProfile(
        author_name="x", version=1, generated_from="corpus_build",
        traits={
            "parenthetical_asides": TraitValue(
                value="frequent", confidence=0.66, agreement=0.47,
                secondary="rare", secondary_agreement=0.30,
                supporting_documents=28, supporting_words=40000,
            ),
        },
    )
    rendered = render_profile(profile, WritingMode.LINKEDIN)
    assert "parenthetical asides: VARIES" in rendered
    assert "frequent in about 47% of documents" in rendered
    assert "rare in about 30%" in rendered
    assert "turns a tendency into a tell" in rendered


def test_a_trait_the_corpus_agrees_on_still_renders_as_an_absolute():
    """The hedge is for split evidence only; consistent traits are unchanged."""
    profile = VoiceProfile(
        author_name="x", version=1, generated_from="corpus_build",
        traits={
            "rhetorical_questions": TraitValue(
                value="none", confidence=0.83, agreement=0.74,
                secondary="rare", secondary_agreement=0.20,
                supporting_documents=28, supporting_words=40000,
            ),
        },
    )
    rendered = render_profile(profile, WritingMode.LINKEDIN)
    assert "  - rhetorical questions: none" in rendered
    assert "VARIES" not in rendered
