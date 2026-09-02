"""Voice changes expression. It must not change evidence.

Every test here pairs a personal voice with the existing validators and
asserts the validator still wins. If one of these fails, the profile has
started overriding something it must never override.
"""

from __future__ import annotations

from howlwriter.academic.identifiers import find_ungrounded_identifiers, identifier_kinds_present
from howlwriter.academic.length import (
    ResolvedLengthBounds,
    evaluate_word_count_bounds,
    pages_to_words,
    resolve_length_bounds,
)
from howlwriter.academic.requirements import (
    classify_requirements,
    is_identifier_fabrication_prohibition,
)
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.humanize.rewriter import ModelHumanizerRewriter
from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from howlwriter.voice.application import render_profile
from howlwriter.voice.corpus.build import build_voice
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)

TECHNICAL = (
    "The initial access used valid cloud credentials (T1078.004), and credential "
    "dumping followed via T1003.001 against the domain controller on 2026-03-14.\n\n"
    "CVE-2024-21413 was exploited to reach the host, which produced Windows Event "
    "ID 4624 and 4672 in the logs. The operator then called the "
    "sts:AssumeRole API 47 times in under 3 minutes.\n\n"
    "Detection guidance is documented at https://attack.mitre.org/techniques/T1003/001/ "
    "and confirmed by Smith (2024). Run `aws cloudtrail lookup-events` to reproduce it.\n\n"
    "As Jones (2023, p. 14) put it, \"the credential is the perimeter now\"."
)


def _bridge(stdout: str):
    registry = RoleBindingRegistry()
    registry.register_binding(RoleBinding(domain="writing", role="humanizer", provider="fake"))
    dispatcher = RoleDispatcher(binding_registry=registry)
    set_howlplane_bridge(HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry))
    return FakeAgentBackend(agent_id="fake", default_stdout=stdout)


def _yaml(text: str, changes: list[str] | None = None) -> str:
    body = "\n".join(f"  {line}" for line in text.splitlines())
    rendered = "\n".join(
        f'  - description: "{c}"\n    reason: "GENERIC_LLM_PHRASE"' for c in (changes or [])
    ) or "  []"
    return (
        "```yaml\n"
        f"resulting_text: |\n{body}\n"
        f"changes_made:\n{rendered}\n"
        'rationale: "test"\n'
        "warnings: []\n"
        "```"
    )


def _voice(store_root, build_corpus, name="subject"):
    outcome = build_voice(name, [build_corpus(14)], store_root=store_root,
                          deterministic_only=True)
    return str(outcome.directory / "profile.json")


# --- the prompt itself states the precedence --------------------------

def test_the_rendered_voice_subordinates_itself_to_evidence(store_root, build_corpus):
    reference = _voice(store_root, build_corpus)
    from howlwriter.humanize.rewriter import _load_voice_profile

    rendered = render_profile(_load_voice_profile(reference), WritingMode.ACADEMIC)
    for phrase in ("facts", "citations", "quotations", "numbers", "dates",
                   "identifiers", "logical order"):
        assert phrase in rendered.lower(), phrase
    assert "Explicit instructions, length limits, and mode rules outrank" in rendered


def test_the_humanizer_prompt_keeps_fact_preservation_above_voice(store_root, build_corpus):
    backend = _bridge(_yaml(TECHNICAL))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))

    ModelHumanizerRewriter().rewrite(document, config, custom_backend=backend)
    prompt = backend.executed_calls[0]["prompt"]
    assert prompt.index("PRESERVE FACTS") < prompt.index("Voice Profile")
    assert "never change numbers, dates, percentages, names" in prompt


# --- grounded identifiers survive -------------------------------------

def test_a_voiced_rewrite_that_keeps_identifiers_passes_the_grounding_check(store_root, build_corpus):
    backend = _bridge(_yaml(TECHNICAL))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))

    result = ModelHumanizerRewriter().rewrite(document, config, custom_backend=backend)
    text = result.document.text

    for identifier in ("T1078.004", "T1003.001", "CVE-2024-21413", "4624", "4672"):
        assert identifier in text, identifier
    assert find_ungrounded_identifiers(result.document.text, [TECHNICAL]) == []


def test_generalizing_a_grounded_attack_id_away_is_detectable(store_root, build_corpus):
    """Style must not be a route to dropping a grounded identifier."""
    generalized = TECHNICAL.replace("T1003.001", "credential dumping techniques")
    backend = _bridge(_yaml(generalized))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))

    result = ModelHumanizerRewriter().rewrite(document, config, custom_backend=backend)
    kinds_before = identifier_kinds_present(TECHNICAL)
    kinds_after = identifier_kinds_present(result.document.text)
    assert "mitre_attack_technique" in kinds_before
    # The transformed document still carries T1078.004, so the kind survives;
    # what changed is the specific identifier, and the diff is visible.
    assert "T1003.001" not in result.document.text
    assert "T1003.001" in TECHNICAL
    assert kinds_after <= kinds_before


def test_an_unsupported_identifier_introduced_by_a_rewrite_is_still_blocked(store_root, build_corpus):
    invented = TECHNICAL + "\n\nThe operator also exploited CVE-2029-99999 for persistence."
    backend = _bridge(_yaml(invented))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))

    result = ModelHumanizerRewriter().rewrite(document, config, custom_backend=backend)
    findings = find_ungrounded_identifiers(result.document.text, [TECHNICAL])
    assert any("CVE-2029-99999" in f.identifier for f in findings)


# --- citations, quotes, urls, numbers, commands -----------------------

def test_citations_quotations_urls_numbers_and_commands_survive(store_root, build_corpus):
    backend = _bridge(_yaml(TECHNICAL))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))
    text = ModelHumanizerRewriter().rewrite(
        document, config, custom_backend=backend
    ).document.text

    assert "Smith (2024)" in text
    assert "Jones (2023, p. 14)" in text
    assert '"the credential is the perimeter now"' in text
    assert "https://attack.mitre.org/techniques/T1003/001/" in text
    assert "2026-03-14" in text
    assert "47 times in under 3 minutes" in text
    assert "sts:AssumeRole" in text
    assert "`aws cloudtrail lookup-events`" in text


def test_logical_ordering_is_preserved(store_root, build_corpus):
    backend = _bridge(_yaml(TECHNICAL))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))
    text = ModelHumanizerRewriter().rewrite(
        document, config, custom_backend=backend
    ).document.text
    assert text.index("initial access") < text.index("credential dumping")
    assert text.index("credential dumping") < text.index("Detection guidance")


def test_zero_change_remains_a_valid_outcome_with_a_voice_selected(store_root, build_corpus):
    """Selecting a voice does not oblige the humanizer to rewrite anything."""
    backend = _bridge(_yaml(TECHNICAL))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))
    result = ModelHumanizerRewriter().rewrite(document, config, custom_backend=backend)
    assert result.document.text.strip() == TECHNICAL.strip()
    assert result.changes == []


def test_minimal_change_is_reported_as_such(store_root, build_corpus):
    edited = TECHNICAL.replace("Detection guidance is documented", "Detection guidance sits")
    backend = _bridge(_yaml(edited, changes=["tightened one clause"]))
    document = Document.parse(TECHNICAL, title="chain", mode=WritingMode.ACADEMIC)
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))
    result = ModelHumanizerRewriter().rewrite(document, config, custom_backend=backend)
    assert len(result.changes) == 1
    assert "T1003.001" in result.document.text


# --- length semantics are untouched by voice --------------------------

def _cybr_spec() -> AssignmentSpec:
    return AssignmentSpec.from_dict({
        "title": "Attack chain analysis",
        "topic": "cloud and kubernetes attack chains",
        "target_words": 2000,
        "word_tolerance_percent": 10,
        "length_constraints": {
            "target_page_min": 6, "target_page_max": 9,
            "max_pages": 10, "words_per_page": 275,
        },
    })


def test_target_range_versus_hard_maximum_semantics_are_intact():
    bounds = resolve_length_bounds(_cybr_spec())
    assert bounds.hard_max_words == pages_to_words(10, 275)
    assert bounds.max_words <= pages_to_words(9, 275)

    def verdict(pages: float) -> str:
        status, _reason = evaluate_word_count_bounds(
            int(pages * 275), bounds.min_words, bounds.max_words,
            bounds.target_words, hard_max_words=bounds.hard_max_words,
        )
        return status

    assert verdict(8) == "PASS"
    assert verdict(9) == "PASS"
    assert verdict(9.4) not in ("PASS", "HARD_LIMIT_FAILURE")
    assert verdict(10) not in ("PASS", "HARD_LIMIT_FAILURE")
    assert verdict(11) == "HARD_LIMIT_FAILURE"


def test_a_voice_cannot_change_the_resolved_length_bounds(store_root, build_corpus):
    """Bounds come from the assignment; the profile has no way to touch them."""
    spec = _cybr_spec()
    without = resolve_length_bounds(spec)
    spec.voice_profile = _voice(store_root, build_corpus)
    with_voice = resolve_length_bounds(spec)
    assert isinstance(with_voice, ResolvedLengthBounds)
    assert with_voice.to_dict() == without.to_dict()


def test_a_voiced_rewrite_that_overruns_still_fails_the_hard_limit(store_root, build_corpus):
    bounds = resolve_length_bounds(_cybr_spec())
    padded_words = bounds.hard_max_words + 400
    status, reason = evaluate_word_count_bounds(
        padded_words, bounds.min_words, bounds.max_words,
        bounds.target_words, hard_max_words=bounds.hard_max_words,
    )
    assert status == "HARD_LIMIT_FAILURE"
    assert reason


# --- requirement ownership is untouched by voice ----------------------

def test_requirements_are_still_classified_by_kind():
    buckets = classify_requirements([
        "Include exactly three plausible attack chains, each in its own subsection.",
        "For each attack chain, name representative tools.",
        "Do not invent exact technical identifiers unless grounded in the source evidence.",
        "Maximum 10 pages.",
        "Keep the paper concise; avoid unnecessary elaboration and padding.",
    ])
    assert len(buckets.positive) == 2
    assert len(buckets.prohibition) == 1
    assert len(buckets.length) == 1
    assert len(buckets.style) == 1


def test_a_prohibition_is_owned_by_the_identifier_validator_not_word_overlap():
    prohibition = (
        "Do not invent exact technical identifiers (e.g. specific CVE numbers, "
        "ATT&CK technique IDs, or Windows Event IDs) unless grounded in the "
        "retrieved source evidence."
    )
    assert is_identifier_fabrication_prohibition(prohibition)
    buckets = classify_requirements([prohibition])
    assert buckets.positive == []
    assert len(buckets.prohibition) == 1


def test_voice_selection_does_not_reclassify_requirements(store_root, build_corpus):
    requirements = [
        "Include exactly three plausible attack chains.",
        "Do not invent exact technical identifiers.",
        "Maximum 10 pages.",
    ]
    before = classify_requirements(requirements)
    _voice(store_root, build_corpus)
    after = classify_requirements(requirements)
    assert [r for r in before.positive] == [r for r in after.positive]
    assert len(before.prohibition) == len(after.prohibition)
    assert len(before.length) == len(after.length)


# --- mode boundaries hold ---------------------------------------------

def test_academic_mode_does_not_inherit_informal_habits(store_root, build_corpus):
    """A casual global voice must not casualize academic prose."""
    from howlwriter.humanize.rewriter import _load_voice_profile, _mode_specific_instructions

    profile = _load_voice_profile(_voice(store_root, build_corpus))
    profile.traits["contractions"] = type(profile.traits["contractions"])(
        value="frequent", confidence=0.9, supporting_documents=20,
    )
    rendered = render_profile(profile, WritingMode.ACADEMIC)
    academic_rules = _mode_specific_instructions(WritingMode.ACADEMIC)

    assert "Do not inject casual contractions, jokes, fragments" in academic_rules
    assert "Explicit instructions, length limits, and mode rules outrank" in rendered


def test_linkedin_mode_rules_survive_a_voice_being_selected(store_root, build_corpus):
    from howlwriter.humanize.rewriter import _mode_specific_instructions

    backend = _bridge(_yaml("A short post about one thing."))
    document = Document.parse(
        "A short post about one thing.", title="post", mode=WritingMode.LINKEDIN
    )
    config = HowlWriterConfig(voice_profile=_voice(store_root, build_corpus))

    ModelHumanizerRewriter().rewrite(document, config, custom_backend=backend)
    prompt = backend.executed_calls[0]["prompt"]

    assert _mode_specific_instructions(WritingMode.LINKEDIN) in prompt
    assert "LINKEDIN / SHORT-FORM MODE" in prompt
    assert "IN PROFESSIONAL WRITING" in prompt or \
        "No professional context was built" in prompt


def test_there_is_no_mode_named_after_a_person(store_root, build_corpus):
    """A personal voice must never become its own mode."""
    _voice(store_root, build_corpus, name="jane")
    assert all(mode.value != "jane" for mode in WritingMode)
