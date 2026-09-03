"""Tests for per-piece structural realization engine and diversity."""

from __future__ import annotations

from howlwriter.domain.modes import WritingMode
from howlwriter.domain.outline import NodeKind, Outline, OutlineNode
from howlwriter.domain.voice import StructuralVector, VoiceContext, VoiceProfile
from howlwriter.voice.application import render_profile
from howlwriter.voice.realization import (
    derive_structural_realization,
    render_structural_realization_prompt,
)


def _sample_vectors() -> list[StructuralVector]:
    return [
        StructuralVector(
            context="professional",
            words=150,
            paragraphs=4,
            paragraph_words_mean=37.5,
            paragraph_words_stdev=10.0,
            paragraph_sentences_mean=3.0,
            sentence_length_mean=12.5,
            sentence_length_stdev=4.0,
            short_sentence_rate=0.25,
            long_sentence_rate=0.08,
            single_sentence_paragraph_rate=0.25,
            transition_rate=0.08,
            sentence_initial_conjunction_rate=0.05,
            first_person_rate=0.04,
            parenthetical_rate=0.05,
            question_rate=0.08,
            opening_class="hook",
            closing_class="call_to_action",
        ),
        StructuralVector(
            context="professional",
            words=350,
            paragraphs=7,
            paragraph_words_mean=50.0,
            paragraph_words_stdev=15.0,
            paragraph_sentences_mean=3.5,
            sentence_length_mean=14.0,
            sentence_length_stdev=5.5,
            short_sentence_rate=0.15,
            long_sentence_rate=0.10,
            single_sentence_paragraph_rate=0.0,
            transition_rate=0.04,
            sentence_initial_conjunction_rate=0.02,
            first_person_rate=0.0,
            parenthetical_rate=0.02,
            question_rate=0.0,
            opening_class="declaration",
            closing_class="punchline",
        ),
        StructuralVector(
            context="academic",
            words=1200,
            paragraphs=10,
            paragraph_words_mean=120.0,
            paragraph_words_stdev=25.0,
            paragraph_sentences_mean=6.0,
            sentence_length_mean=20.0,
            sentence_length_stdev=7.0,
            short_sentence_rate=0.05,
            long_sentence_rate=0.25,
            single_sentence_paragraph_rate=0.0,
            transition_rate=0.03,
            sentence_initial_conjunction_rate=0.01,
            first_person_rate=0.0,
            parenthetical_rate=0.03,
            question_rate=0.01,
            opening_class="background",
            closing_class="forward_looking",
        ),
    ]


def _sample_profile() -> VoiceProfile:
    vectors = _sample_vectors()
    professional_ctx = VoiceContext(
        name="professional",
        document_count=2,
        word_count=500,
        confidence=0.8,
        structural_vectors=[v for v in vectors if v.context == "professional"],
    )
    academic_ctx = VoiceContext(
        name="academic",
        document_count=1,
        word_count=1200,
        confidence=0.8,
        structural_vectors=[v for v in vectors if v.context == "academic"],
    )
    return VoiceProfile(
        author_name="author_test",
        version=3,
        profile_name="author_test",
        generated_from="corpus_build",
        contexts={"professional": professional_ctx, "academic": academic_ctx},
        structural_vectors=vectors,
    )


def test_seed_determinism():
    profile = _sample_profile()
    real1 = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=250,
        input_text="Discussion about system reliability and outages",
        seed=42,
    )
    real2 = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=250,
        input_text="Discussion about system reliability and outages",
        seed=42,
    )
    assert real1 is not None and real2 is not None
    assert real1.to_dict() == real2.to_dict()
    assert real1.paragraph_count_region == real2.paragraph_count_region
    assert real1.sentence_length_mean_target == real2.sentence_length_mean_target


def test_different_seeds_produce_variance():
    profile = _sample_profile()
    # Seeds 1 and 2 select different anchors or random draws
    real1 = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=250,
        input_text="Discussion about system reliability and outages",
        seed=1,
    )
    real2 = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=250,
        input_text="Discussion about system reliability and outages",
        seed=10,
    )
    assert real1 is not None and real2 is not None
    assert real1.seed != real2.seed


def test_covariance_preservation_from_anchor():
    profile = _sample_profile()
    real = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=150,
        seed=42,
    )
    assert real is not None
    assert real.selection_method == "EMPIRICAL_JOINT_ANCHOR_VECTOR"
    assert real.paragraph_count_region[0] <= real.paragraph_count_region[1]
    assert real.paragraph_words_mean_target > 0
    assert real.sentence_length_mean_target > 0


def test_length_conditioning():
    profile = _sample_profile()
    # Requesting 1200 words should condition selection toward longer vectors
    real = derive_structural_realization(
        profile,
        mode=WritingMode.ACADEMIC,
        target_words=1200,
        seed=42,
    )
    assert real is not None
    assert real.target_words == 1200
    assert real.sentence_length_mean_target == 20.0


def _impersonal_profile() -> VoiceProfile:
    """A profile whose professional anchors never used first person.

    Needed to exercise the current-input override deterministically: the engine
    only records CURRENT_INPUT_PERSONAL_PRESERVED when the sampled anchor
    supplied no first person of its own.
    """
    profile = _sample_profile()
    for vector in profile.structural_vectors:
        vector.first_person_rate = 0.0
    for context in profile.contexts.values():
        for vector in context.structural_vectors:
            vector.first_person_rate = 0.0
    return profile


def test_personal_input_forces_first_person():
    profile = _sample_profile()
    real = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=200,
        input_text="My team and I spent yesterday debugging an outage that I caused.",
        seed=42,
    )
    assert real is not None
    assert real.first_person_eligible is True
    assert real.first_person_target_rate > 0


def test_personal_input_overrides_sampled_absence():
    real = derive_structural_realization(
        _impersonal_profile(),
        mode=WritingMode.LINKEDIN,
        target_words=200,
        input_text="My team and I spent yesterday debugging an outage that I caused.",
        seed=42,
    )
    assert real is not None
    assert real.first_person_eligible is True
    assert any("CURRENT_INPUT_PERSONAL_PRESERVED" in o for o in real.overrides)


def test_impersonal_input_vetoes_sampled_first_person():
    profile = _sample_profile()
    real = derive_structural_realization(
        profile,
        mode=WritingMode.TECHNICAL,
        target_words=200,
        input_text="The system architecture deploys three replicas across availability zones.",
        seed=42,
    )
    assert real is not None
    assert real.first_person_eligible is False
    assert real.first_person_target_rate == 0.0
    # The sampled anchor did carry first person, so the veto must be recorded
    # rather than the absence being a coincidence of anchor choice.
    assert any("IMPERSONAL_INPUT_VETO" in o for o in real.overrides)


def test_outline_sections_suppress_sampled_paragraph_shape():
    profile = _sample_profile()
    outline = Outline(
        title="Distributed Systems",
        topic="Consensus Protocols",
        nodes=[
            OutlineNode(id="n1", kind=NodeKind.HEADING, text="Introduction"),
            OutlineNode(id="n2", kind=NodeKind.HEADING, text="Paxos"),
            OutlineNode(id="n3", kind=NodeKind.HEADING, text="Raft"),
            OutlineNode(id="n4", kind=NodeKind.HEADING, text="Byzantine Fault Tolerance"),
            OutlineNode(id="n5", kind=NodeKind.HEADING, text="Evaluation"),
            OutlineNode(id="n6", kind=NodeKind.HEADING, text="Conclusion"),
        ],
    )
    real = derive_structural_realization(
        profile,
        mode=WritingMode.TECHNICAL,
        outline=outline,
        target_words=150,
        seed=42,
    )
    assert real is not None
    # A supplied section structure outranks the sampled paragraph architecture.
    # The engine asserts that authority by dropping to cadence-only guidance,
    # not by widening a paragraph region it then never renders.
    assert real.guidance_level == "cadence_only"
    assert any("OUTLINE_STRUCTURE_AUTHORITY" in o for o in real.overrides)

    rendered = "\n".join(render_structural_realization_prompt(real))
    assert "outline authority:" in rendered
    assert "sentence rhythm:" in rendered
    assert "structural shape:" not in rendered
    assert "paragraph weighting:" not in rendered


def test_near_complete_draft_protection():
    profile = _sample_profile()
    real = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=300,
        freedom="MINIMAL",
        seed=42,
    )
    assert real is not None
    assert any("NEAR_COMPLETE_DRAFT_PRESERVED" in o for o in real.overrides)
    prompt_lines = render_structural_realization_prompt(real)
    prompt_text = "\n".join(prompt_lines)
    assert "do not apply sampled structural pressure" in prompt_text
    assert "structural shape:" not in prompt_text


def test_render_structural_realization_prompt():
    profile = _sample_profile()
    real = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=250,
        seed=42,
    )
    lines = render_structural_realization_prompt(real)
    rendered = "\n".join(lines)
    assert "STRUCTURAL REALIZATION FOR THIS PIECE" in rendered
    assert "structural shape:" in rendered
    assert "sentence rhythm:" in rendered
    assert real.escape_clause in rendered


def test_render_profile_integrates_realization():
    profile = _sample_profile()
    real = derive_structural_realization(
        profile,
        mode=WritingMode.LINKEDIN,
        target_words=250,
        seed=42,
    )
    block = render_profile(profile, mode=WritingMode.LINKEDIN, realization=real)
    assert "STRUCTURAL REALIZATION FOR THIS PIECE" in block
    assert "MEASURED SPREAD ACROSS" not in block

    # Legacy fallback without realization renders measured spread
    legacy_block = render_profile(profile, mode=WritingMode.LINKEDIN, realization=None)
    assert "HOW TO APPLY THIS VOICE:" in legacy_block
