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
            fragment_rate=0.15,
            opening_class="direct_entry",
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
            sentence_initial_conjunction_rate=0.0,
            first_person_rate=0.0,
            parenthetical_rate=0.0,
            question_rate=0.0,
            fragment_rate=0.0,
            opening_class="contextual_setup",
            closing_class="stops",
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
            fragment_rate=0.0,
            opening_class="contextual_setup",
            closing_class="restatement",
        ),
        StructuralVector(
            context="academic",
            words=1600,
            paragraphs=14,
            paragraph_words_mean=114.3,
            paragraph_words_stdev=30.0,
            paragraph_sentences_mean=5.0,
            sentence_length_mean=22.0,
            sentence_length_stdev=8.0,
            short_sentence_rate=0.03,
            long_sentence_rate=0.32,
            single_sentence_paragraph_rate=0.0,
            transition_rate=0.02,
            sentence_initial_conjunction_rate=0.0,
            first_person_rate=0.0,
            parenthetical_rate=0.05,
            question_rate=0.0,
            fragment_rate=0.0,
            opening_class="brief_setup",
            closing_class="concise",
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
        document_count=2,
        word_count=2800,
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
    realizations = [
        derive_structural_realization(
            profile,
            mode=WritingMode.LINKEDIN,
            target_words=250,
            seed=seed,
        )
        for seed in range(20)
    ]
    assert all(real is not None for real in realizations)
    # This asserts selected behavior differs, not merely that the seed field
    # echoes a different input.
    assert len(
        {
            (
                real.paragraph_words_mean_target,
                real.sentence_length_mean_target,
                real.opening_behavior,
            )
            for real in realizations
        }
    ) == 2


def test_covariance_preservation_from_anchor():
    profile = _sample_profile()
    observed = set()
    for seed in range(100):
        real = derive_structural_realization(
            profile,
            mode=WritingMode.LINKEDIN,
            target_words=250,
            seed=seed,
        )
        assert real is not None
        assert real.selection_method == "EMPIRICAL_JOINT_ANCHOR_VECTOR"
        observed.add(
            (
                real.paragraph_words_mean_target,
                real.sentence_length_mean_target,
                real.short_sentence_tendency,
                real.first_person_eligible,
                real.parenthetical_eligible,
                real.question_eligible,
                real.fragment_eligible,
                real.opening_behavior,
                real.ending_behavior,
            )
        )

    # Every cross-feature tuple is one of the two observed document vectors.
    # Independent marginal sampling would create additional combinations.
    assert observed == {
        (37.5, 12.5, "prominent", True, True, True, True,
         "direct_thesis", "recommendation"),
        (50.0, 14.0, "moderate", False, False, False, False,
         "contextual_statement", "declarative_stop"),
    }


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
    assert real.selected_anchor_context == "academic"
    assert real.sample_count == 2
    assert real.sentence_length_mean_target in (20.0, 22.0)


def test_short_professional_piece_cannot_select_long_academic_anchor():
    profile = _sample_profile()
    for seed in range(50):
        real = derive_structural_realization(
            profile,
            mode=WritingMode.LINKEDIN,
            target_words=150,
            seed=seed,
        )
        assert real is not None
        assert real.selected_anchor_context == "professional"
        assert real.paragraph_words_mean_target in (37.5, 50.0)


def test_one_compatible_document_is_not_misrepresented_as_a_sampling_pool():
    vector = _sample_vectors()[0]
    profile = VoiceProfile(
        author_name="one",
        profile_name="one",
        generated_from="corpus_build",
        structural_vectors=[vector],
    )
    real = derive_structural_realization(
        profile, mode=WritingMode.LINKEDIN, target_words=150, seed=1
    )
    assert real is not None
    assert real.selection_method == "NO_COMPATIBLE_EMPIRICAL_VECTOR"
    assert real.sample_count == 0
    assert real.guidance_level == "none"


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
        target_words=250,
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


def test_current_input_preserves_sparse_devices_even_when_anchor_lacks_them():
    profile = _sample_profile()
    # Seed 0 selects the zero-device professional anchor in this fixture.
    candidates = [
        derive_structural_realization(
            profile,
            mode=WritingMode.LINKEDIN,
            target_words=250,
            input_text=(
                "But I learned this the hard way (during an outage). "
                "Why repeat it? Not even close."
            ),
            seed=seed,
        )
        for seed in range(30)
    ]
    real = next(
        item
        for item in candidates
        if item is not None
        and any("CURRENT_INPUT_PARENTHETICAL_PRESERVED" in o for o in item.overrides)
    )
    assert real.first_person_eligible is True
    assert real.parenthetical_eligible is True
    assert real.question_eligible is True
    assert real.sentence_initial_conjunction_eligible is True
    assert real.fragment_eligible is True
    assert {
        override.split()[0] for override in real.overrides
        if override.startswith("CURRENT_INPUT_")
    } >= {
        "CURRENT_INPUT_PERSONAL_PRESERVED",
        "CURRENT_INPUT_PARENTHETICAL_PRESERVED",
        "CURRENT_INPUT_QUESTION_PRESERVED",
        "CURRENT_INPUT_CONJUNCTION_START_PRESERVED",
        "CURRENT_INPUT_FRAGMENT_PRESERVED",
    }


def test_near_complete_draft_reparagraphing_is_rejected_end_to_end(
    tmp_path, monkeypatch
):
    from howlwriter.config.defaults import default_config
    from howlwriter.domain.document import Document
    from howlwriter.pipeline.howl import run_howl_pipeline
    from src.control_plane.agent_execution import FakeAgentBackend

    paragraphs = [
        (
            "Production queues absorb short traffic bursts while keeping the "
            "worker pool bounded. Operators can observe queue depth, reject "
            "excess load, and preserve latency before one dependency spreads "
            "overload across the rest of the service graph."
        ),
        (
            "That boundary also makes capacity planning concrete. Arrival "
            "rates, service time, and the number of workers become measurable "
            "inputs instead of hidden assumptions, so teams can test behavior "
            "before a traffic spike turns into an incident."
        ),
        (
            "The implementation is intentionally ordinary. Set a finite "
            "limit, expose saturation, and choose an explicit rejection path. "
            "A small amount of visible backpressure is safer than an invisible "
            "backlog that consumes memory until the process fails."
        ),
    ]
    original = "\n\n".join(paragraphs)
    assert len(original.split()) > 100
    merged = " ".join(paragraphs)
    indented = "\n".join(f"  {line}" for line in merged.splitlines())
    backend = FakeAgentBackend(
        agent_id="same_provider",
        default_stdout=(
            "\x60\x60\x60yaml\n"
            f"resulting_text: |\n{indented}\n"
            "changes_made: []\n"
            "verdict: PASS\n"
            "differences: []\n"
            "rationale: no semantic change\n"
            "\x60\x60\x60"
        ),
    )
    path = tmp_path / "complete.md"
    path.write_text(original, encoding="utf-8")
    config = default_config()
    config.voice_profile = "synthetic-profile.json"
    monkeypatch.setattr(
        "howlwriter.humanize.rewriter._load_voice_profile",
        lambda _value: _sample_profile(),
    )

    result = run_howl_pipeline(
        path,
        config,
        custom_backend=backend,
        writing_mode=WritingMode.LINKEDIN,
    )

    assert result.final_document.text == Document.parse(original).text
    assert result.provenance.structural_realization["guidance_level"] == "none"
    guard = result.provenance.review["authority_guard"][0]
    assert guard["near_complete_structure_changed"] is True
    assert any("near-complete draft" in warning for warning in result.provenance.warnings)


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
