"""Choose one evidence-backed structural shape for one generated piece.

The realization layer samples a complete document vector, not independent
feature marginals. That distinction is the contract: an observed combination
of paragraph shape, cadence, and sparse habits may be offered as soft guidance;
a synthetic combination that never occurred in the corpus may not.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any

from howlwriter.domain.modes import WritingMode
from howlwriter.domain.outline import NodeKind, Outline
from howlwriter.domain.structural_realization import StructuralRealization
from howlwriter.domain.voice import StructuralVector, VoiceProfile

_FIRST_PERSON_PATTERN = re.compile(
    r"\b(I|I'm|I've|I'd|I'll|me|my|mine|we|we're|we've|our|ours|us)\b",
    re.I,
)
_PARENTHETICAL_PATTERN = re.compile(r"\([^()]{1,200}\)")
_CONJUNCTION_START_PATTERN = re.compile(
    r"(?:^|(?<=[.!?])\s+)(?:And|But|Or|Yet|So)\b",
    re.I,
)
_LIST_SHAPE_PATTERN = re.compile(
    r"(?:^\s*(?:[-*+•]|\d+[.)])\s+|\b(?:bullet(?:ed)?|numbered)\s+list\b|"
    r"\bchecklist\b)",
    re.I | re.M,
)
_HEADING_SHAPE_PATTERN = re.compile(
    r"(?:^\s*#{1,6}\s+|\b(?:with|using|use)\s+(?:clear\s+)?"
    r"(?:headings|sections)\b)",
    re.I | re.M,
)

# One document is evidence of one document, not a distribution from which
# different legitimate shapes can be selected.
MIN_CONTEXT_POOL = 2

# Paragraph measurements from list- or heading-dominated documents describe
# that format, not interchangeable prose blocks. Applying their density while
# suppressing the list/heading relationship creates a synthetic structure even
# though the row itself is empirical.
MAX_UNREQUESTED_LIST_RATE = 0.20
MAX_UNREQUESTED_HEADING_RATE = 0.20

# Writing modes and voice contexts are different concepts. Keep this mapping
# aligned with voice.application.MODE_CONTEXTS.
MODE_CONTEXT_MAP: dict[str, str] = {
    "linkedin": "professional",
    "professional": "professional",
    "email": "professional",
    "academic": "academic",
    "documentation": "academic",
    "technical": "professional",
    "article": "general",
    "casual": "general",
    "custom": "general",
}

DEFAULT_TARGET_WORDS: dict[str, int] = {
    "linkedin": 220,
    "professional": 600,
    "email": 250,
    "academic": 1200,
    "documentation": 800,
    "technical": 600,
    "article": 700,
    "casual": 350,
    "custom": 500,
}

_COMPATIBLE_CONTEXTS: dict[str, set[str]] = {
    "professional": {"professional", "general", "unknown", "mixed", ""},
    "academic": {"academic"},
    "general": {"general", "professional", "unknown", "mixed", ""},
}

_OPENING_CLASSES = {
    "direct_entry": "direct_thesis",
    "brief_setup": "contextual_statement",
    "contextual_setup": "contextual_statement",
    "personal_context": "personal_observation",
    "direct_thesis": "direct_thesis",
    "contextual_statement": "contextual_statement",
    "personal_observation": "personal_observation",
    "anecdotal_entry": "anecdotal_entry",
    "question": "question",
}
_CLOSING_CLASSES = {
    "stops": "declarative_stop",
    "concise": "declarative_stop",
    "restatement": "summary",
    "call_to_action": "recommendation",
    "declarative_stop": "declarative_stop",
    "summary": "summary",
    "recommendation": "recommendation",
    "implication": "implication",
    "personal_reflection": "personal_reflection",
    "qualified_conclusion": "qualified_conclusion",
    "question": "question",
}


def _reasoning_guidance(reasoning_shape: str) -> str:
    """Turn an empirical move sequence into a broad family, not a checklist."""
    moves = set(reasoning_shape.split(">"))
    if "experience" in moves:
        return "experience-led reflection"
    if "problem" in moves and "recommendation" in moves:
        return "problem-to-recommendation development"
    if "recommendation" in moves:
        return "claim developed toward a recommendation"
    if "contrast" in moves:
        return "contrast-led development"
    if "example" in moves:
        return "example-led explanation"
    if "mechanism" in moves:
        return "claim developed through causal mechanism"
    if "implication" in moves:
        return "claim developed toward an implication"
    if "question" in moves:
        return "question-led exploration"
    return "explanatory development" if reasoning_shape else ""


def derive_seed(
    profile_name: str,
    mode: str,
    input_text: str = "",
    outline_summary: str = "",
    target_words: int | None = None,
) -> int:
    """Derive a stable seed from every selection input, without storing prose."""
    hasher = hashlib.sha256()
    for value in (
        profile_name,
        mode,
        input_text,
        outline_summary,
        str(target_words or 0),
    ):
        hasher.update(value.encode("utf-8"))
        hasher.update(b"::")
    return int.from_bytes(hasher.digest()[:4], "big") & 0x7FFFFFFF


def _length_pools(
    vectors: list[StructuralVector], target_words: int
) -> tuple[list[StructuralVector], list[StructuralVector]]:
    close = [
        vector
        for vector in vectors
        if target_words * 0.5 <= vector.words <= target_words * 2.0
    ]
    wide = [
        vector
        for vector in vectors
        if target_words * 0.25 <= vector.words <= target_words * 4.0
    ]
    return close, wide


def _outline_fingerprint(outline: Outline | None) -> str:
    if outline is None:
        return ""
    try:
        payload = outline.to_json()
    except AttributeError:
        payload = repr(outline)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_freedom(outline: Outline | None, freedom: Any) -> str:
    value = getattr(freedom, "value", freedom)
    if value is None and outline is not None:
        from howlwriter.outline.freedom import assess_freedom

        value = assess_freedom(outline).freedom.value
    return str(value or "").strip().lower()


def _section_count(outline: Outline | None) -> int:
    if outline is None:
        return 0
    return len(
        [
            node
            for node in outline.all_nodes()
            if node.kind in (NodeKind.HEADING, NodeKind.REQUIRED_POINT)
        ]
    )


def _select_pool(
    profile: VoiceProfile,
    desired_context: str,
    target_words: int,
    *,
    allow_list_shape: bool,
    allow_heading_shape: bool,
) -> tuple[list[StructuralVector], int, int, str, str, str, str]:
    """Return a context-, length-, and document-format-compatible pool."""
    all_vectors = [vector for vector in profile.structural_vectors if vector.words > 0]
    raw_context_vectors = [
        vector for vector in all_vectors if vector.context == desired_context
    ]
    compatible_names = _COMPATIBLE_CONTEXTS.get(
        desired_context, {desired_context, "unknown", "mixed", ""}
    )
    raw_global_vectors = [v for v in all_vectors if v.context in compatible_names]

    def format_compatible(vector: StructuralVector) -> bool:
        if (
            not allow_list_shape
            and vector.list_rate > MAX_UNREQUESTED_LIST_RATE
        ):
            return False
        if (
            not allow_heading_shape
            and vector.heading_rate > MAX_UNREQUESTED_HEADING_RATE
        ):
            return False
        return True

    context_vectors = [v for v in raw_context_vectors if format_compatible(v)]
    global_vectors = [v for v in raw_global_vectors if format_compatible(v)]

    if allow_list_shape and allow_heading_shape:
        format_conditioning = "LIST_AND_HEADING_SHAPES_AUTHORIZED"
    elif allow_list_shape:
        format_conditioning = "LIST_SHAPE_AUTHORIZED;UNREQUESTED_HEADINGS_EXCLUDED"
    elif allow_heading_shape:
        format_conditioning = "HEADING_SHAPE_AUTHORIZED;UNREQUESTED_LISTS_EXCLUDED"
    else:
        format_conditioning = "UNREQUESTED_LIST_AND_HEADING_SHAPES_EXCLUDED"

    context_close, context_wide = _length_pools(context_vectors, target_words)
    global_close, global_wide = _length_pools(global_vectors, target_words)

    # Exact register plus close length is strongest. A larger compatible
    # global pool is preferable to pretending one exact-context document is a
    # distribution. No branch samples from fewer than MIN_CONTEXT_POOL
    # documents.
    choices = (
        (
            context_close if len(context_close) >= MIN_CONTEXT_POOL else [],
            len(raw_context_vectors),
            len(context_vectors),
            desired_context,
            "CONTEXT_CLOSE_0.5X_TO_2X",
            "",
        ),
        (
            global_close if len(global_close) >= MIN_CONTEXT_POOL else [],
            len(raw_global_vectors),
            len(global_vectors),
            "global",
            "GLOBAL_CLOSE_0.5X_TO_2X",
            "GLOBAL_LENGTH_COMPATIBLE_FALLBACK",
        ),
        (
            context_wide if len(context_wide) >= MIN_CONTEXT_POOL else [],
            len(raw_context_vectors),
            len(context_vectors),
            desired_context,
            "CONTEXT_WIDE_0.25X_TO_4X",
            "NO_CLOSE_LENGTH_MATCH",
        ),
        (
            global_wide if len(global_wide) >= MIN_CONTEXT_POOL else [],
            len(raw_global_vectors),
            len(global_vectors),
            "global",
            "GLOBAL_WIDE_0.25X_TO_4X",
            "GLOBAL_WIDE_LENGTH_FALLBACK",
        ),
    )
    for (
        pool,
        candidate_count,
        format_eligible_count,
        source,
        conditioning,
        fallback,
    ) in choices:
        if pool:
            return (
                pool,
                candidate_count,
                format_eligible_count,
                source,
                conditioning,
                format_conditioning,
                fallback,
            )

    return (
        [],
        len(raw_context_vectors) or len(raw_global_vectors),
        len(context_vectors) or len(global_vectors),
        desired_context,
        "NO_LENGTH_COMPATIBLE_VECTOR",
        format_conditioning,
        "NO_STRUCTURAL_GUIDANCE",
    )


def _no_guidance_realization(
    *,
    desired_context: str,
    candidate_count: int,
    seed: int,
    target_words: int,
    freedom: str,
    length_conditioning: str,
    format_conditioning: str,
    format_eligible_count: int,
    fallback_behavior: str,
) -> StructuralRealization:
    return StructuralRealization(
        source_context=desired_context,
        candidate_count=candidate_count,
        sample_count=0,
        selection_method="NO_COMPATIBLE_EMPIRICAL_VECTOR",
        length_conditioning=length_conditioning,
        format_conditioning=format_conditioning,
        fallback_behavior=fallback_behavior,
        format_eligible_count=format_eligible_count,
        seed=seed,
        reproducible=True,
        model_generation_deterministic=False,
        target_words=target_words,
        opening_behavior="",
        ending_behavior="",
        generation_freedom=freedom,
        guidance_level="none",
        overrides=[
            "NO_COMPATIBLE_EMPIRICAL_VECTOR "
            "(voice supplied no context-and-length-compatible structural anchor)"
        ],
    )


def derive_structural_realization(
    profile: VoiceProfile | None,
    mode: WritingMode | str | None = None,
    outline: Outline | None = None,
    target_words: int | None = None,
    input_text: str = "",
    seed: int | None = None,
    freedom: Any = None,
) -> StructuralRealization | None:
    """Derive one reproducible, joint empirical realization for a piece."""
    if profile is None:
        return None

    mode_value = mode.value if isinstance(mode, WritingMode) else str(mode or "custom")
    mode_name = mode_value.lower().strip()
    effective_target = int(
        target_words
        or (outline.target_words if outline and outline.target_words else 0)
        or DEFAULT_TARGET_WORDS.get(mode_name, 500)
    )
    desired_context = MODE_CONTEXT_MAP.get(mode_name, "general")
    freedom_name = _resolve_freedom(outline, freedom)
    actual_seed = seed
    if actual_seed is None:
        actual_seed = derive_seed(
            profile.profile_name or "voice",
            mode_name,
            input_text,
            _outline_fingerprint(outline),
            effective_target,
        )

    outline_has_headings = bool(
        outline and any(node.kind == NodeKind.HEADING for node in outline.all_nodes())
    )
    authority_text = input_text
    if outline is not None:
        authority_text = "\n".join(
            [input_text, *[node.text for node in outline.all_nodes() if node.text]]
        )
    allow_list_shape = bool(_LIST_SHAPE_PATTERN.search(authority_text))
    allow_heading_shape = bool(
        outline_has_headings
        or _HEADING_SHAPE_PATTERN.search(authority_text)
        or mode_name == "documentation"
    )

    (
        pool,
        candidate_count,
        format_eligible_count,
        source_context,
        conditioning,
        format_conditioning,
        fallback,
    ) = _select_pool(
        profile,
        desired_context,
        effective_target,
        allow_list_shape=allow_list_shape,
        allow_heading_shape=allow_heading_shape,
    )
    if not pool:
        return _no_guidance_realization(
            desired_context=desired_context,
            candidate_count=candidate_count,
            seed=actual_seed,
            target_words=effective_target,
            freedom=freedom_name,
            length_conditioning=conditioning,
            format_conditioning=format_conditioning,
            format_eligible_count=format_eligible_count,
            fallback_behavior=fallback,
        )

    anchor = random.Random(actual_seed).choice(pool)
    paragraph_mean = anchor.paragraph_words_mean
    if paragraph_mean <= 0:
        paragraph_mean = anchor.words / max(1, anchor.paragraphs)
    paragraph_mean = max(1.0, paragraph_mean)
    base_paragraphs = max(1, round(effective_target / paragraph_mean))
    paragraph_region = (max(1, base_paragraphs - 1), base_paragraphs + 1)

    short_tendency = (
        "prominent"
        if anchor.short_sentence_rate >= 0.22
        else "moderate"
        if anchor.short_sentence_rate >= 0.10
        else "minimal"
    )
    long_tendency = (
        "prominent"
        if anchor.long_sentence_rate >= 0.22
        else "moderate"
        if anchor.long_sentence_rate >= 0.10
        else "minimal"
    )
    transition_tendency = (
        "moderate"
        if anchor.transition_rate >= 0.08
        else "light"
        if anchor.transition_rate >= 0.03
        else "minimal"
    )

    section_count = _section_count(outline)
    if freedom_name == "minimal":
        guidance_level = "none"
    elif freedom_name == "low" or section_count >= 2:
        guidance_level = "cadence_only"
    else:
        guidance_level = "full"

    overrides: list[str] = []
    if section_count:
        overrides.append(
            "OUTLINE_STRUCTURE_AUTHORITY "
            f"({section_count} supplied section/required-point node(s); "
            "sampled paragraph shape cannot alter semantic order)"
        )
    if guidance_level == "cadence_only":
        overrides.append(
            "AUTHORSHIP_RICH_OUTLINE "
            "(sampled paragraph/opening/closing shape suppressed; cadence only)"
        )
    elif guidance_level == "none":
        overrides.append(
            "NEAR_COMPLETE_DRAFT_PRESERVED "
            "(minimal freedom; no sampled structural rewrite pressure)"
        )

    first_person = anchor.first_person_rate > 0
    first_person_rate = round(anchor.first_person_rate, 2) if first_person else 0.0
    parenthetical = anchor.parenthetical_rate > 0
    parenthetical_count = (
        max(1, round(anchor.parenthetical_rate * effective_target / 100.0))
        if parenthetical
        else 0
    )
    conjunction_start = anchor.sentence_initial_conjunction_rate > 0
    question = anchor.question_rate > 0
    fragment = anchor.fragment_rate > 0

    # Persistent profile overrides are explicit user choices, but wording that
    # already exists in the current input still wins over a sampled absence.
    if profile.overrides and profile.overrides.traits:
        traits = profile.overrides.traits
        if traits.get("first_person_presence") == "none":
            first_person = False
            first_person_rate = 0.0
            overrides.append("USER_OVERRIDE (first_person_presence: none)")
        elif traits.get("first_person_presence") in ("prominent", "frequent"):
            first_person = True
            first_person_rate = max(3.0, first_person_rate)
            overrides.append("USER_OVERRIDE (first_person_presence: prominent)")
        if traits.get("parenthetical_asides") == "none":
            parenthetical = False
            parenthetical_count = 0
            overrides.append("USER_OVERRIDE (parenthetical_asides: none)")

    has_personal = bool(_FIRST_PERSON_PATTERN.search(authority_text))
    has_parenthetical = bool(_PARENTHETICAL_PATTERN.search(authority_text))
    has_question = "?" in authority_text
    has_conjunction_start = bool(_CONJUNCTION_START_PATTERN.search(authority_text))
    if authority_text.strip():
        from howlwriter.voice.corpus.features import extract_features

        has_fragment = extract_features(authority_text).fragment_rate > 0
    else:
        has_fragment = False

    if has_personal:
        if not first_person:
            overrides.append(
                "CURRENT_INPUT_PERSONAL_PRESERVED "
                "(current author text overrides sampled/profile absence)"
            )
        first_person = True
        first_person_rate = max(1.0, first_person_rate)
    elif authority_text.strip() and first_person:
        first_person = False
        first_person_rate = 0.0
        overrides.append(
            "IMPERSONAL_INPUT_VETO "
            "(sampled first person cannot invent an author experience)"
        )

    if has_parenthetical and not parenthetical:
        parenthetical = True
        parenthetical_count = max(
            1, len(_PARENTHETICAL_PATTERN.findall(authority_text))
        )
        overrides.append("CURRENT_INPUT_PARENTHETICAL_PRESERVED")
    if has_question and not question:
        question = True
        overrides.append("CURRENT_INPUT_QUESTION_PRESERVED")
    if has_conjunction_start and not conjunction_start:
        conjunction_start = True
        overrides.append("CURRENT_INPUT_CONJUNCTION_START_PRESERVED")
    if has_fragment and not fragment:
        fragment = True
        overrides.append("CURRENT_INPUT_FRAGMENT_PRESERVED")

    # In formal/technical work, absent sparse devices are not an invitation to
    # add them. In sparse social prompts they remain optional evidence, never
    # quotas; cadence-only/none rendering suppresses them entirely.
    formal_input = mode_name in {
        "academic",
        "technical",
        "documentation",
        "professional",
        "email",
    }
    if formal_input and authority_text.strip():
        if not has_parenthetical:
            parenthetical = False
            parenthetical_count = 0
        if not has_question:
            question = False
        if not has_conjunction_start:
            conjunction_start = False
        if not has_fragment:
            fragment = False

    return StructuralRealization(
        source_context=source_context,
        selected_anchor_context=anchor.context or "unknown",
        candidate_count=candidate_count,
        sample_count=len(pool),
        selection_method="EMPIRICAL_JOINT_ANCHOR_VECTOR",
        length_conditioning=conditioning,
        format_conditioning=format_conditioning,
        fallback_behavior=fallback,
        format_eligible_count=format_eligible_count,
        seed=actual_seed,
        reproducible=True,
        model_generation_deterministic=False,
        target_words=effective_target,
        paragraph_count_region=paragraph_region,
        paragraph_words_mean_target=round(paragraph_mean, 1),
        paragraph_sentences_mean_target=round(
            anchor.paragraph_sentences_mean or 3.0, 1
        ),
        single_sentence_paragraph_eligible=(
            anchor.single_sentence_paragraph_rate > 0
        ),
        sentence_length_mean_target=round(anchor.sentence_length_mean or 18.0, 1),
        sentence_length_stdev_target=round(
            anchor.sentence_length_stdev or 6.0, 1
        ),
        short_sentence_tendency=short_tendency,
        long_sentence_tendency=long_tendency,
        first_person_eligible=first_person,
        first_person_target_rate=first_person_rate,
        parenthetical_eligible=parenthetical,
        parenthetical_target_count=parenthetical_count,
        sentence_initial_conjunction_eligible=conjunction_start,
        question_eligible=question,
        fragment_eligible=fragment,
        transition_density_tendency=transition_tendency,
        opening_behavior=_OPENING_CLASSES.get(anchor.opening_class, ""),
        ending_behavior=_CLOSING_CLASSES.get(anchor.closing_class, ""),
        reasoning_shape=anchor.reasoning_shape,
        overrides=overrides,
        generation_freedom=freedom_name,
        guidance_level=guidance_level,
    )


def render_structural_realization_prompt(
    realization: StructuralRealization,
) -> list[str]:
    """Render evidence as optional guidance without turning it into a quota."""
    lines = [
        "STRUCTURAL REALIZATION FOR THIS PIECE "
        "(one empirical document anchor; guidance only):"
    ]
    if realization.guidance_level == "none":
        lines.extend(
            [
                "  - current-authority result: do not apply sampled structural "
                "pressure; preserve the supplied draft and its paragraphing",
                f"  - {realization.escape_clause}",
            ]
        )
        return lines

    lines.append(
        "  - sentence rhythm: the selected real document used about "
        f"{realization.sentence_length_mean_target:.0f} words per sentence, "
        f"with {realization.short_sentence_tendency} concise statements and "
        f"{realization.long_sentence_tendency} developed sentences; vary as "
        "clarity requires"
    )
    if realization.guidance_level == "cadence_only":
        lines.extend(
            [
                "  - outline authority: use this cadence only; retain the "
                "author's section order, paragraph architecture, opening, and ending",
                f"  - {realization.escape_clause}",
            ]
        )
        return lines

    low, high = realization.paragraph_count_region
    lines.extend(
        [
            "  - structural shape: the empirical anchor scales to roughly "
            f"{low}-{high} paragraphs at this target length; treat this as a "
            "starting region, never a count to hit",
            "  - paragraph weighting: the anchor averaged about "
            f"{realization.paragraph_words_mean_target:.0f} words per block; "
            "preserve natural unevenness and let the argument set every break",
        ]
    )

    if realization.single_sentence_paragraph_eligible:
        lines.append(
            "  - focal paragraphs: the anchor contained a single-sentence "
            "paragraph; one is permissible when the idea earns it, never required"
        )
    if realization.parenthetical_eligible:
        lines.append(
            "  - parentheticals: the anchor used them; retain any already in "
            "the input, but do not add one merely to match the anchor"
        )
    if realization.first_person_eligible:
        lines.append(
            "  - author stance: retain the personal perspective already "
            "authorized by the current input; never invent an anecdote"
        )
    else:
        lines.append(
            "  - author stance: do not invent first-person experience or an "
            "authorial role absent from the current input"
        )
    if realization.sentence_initial_conjunction_eligible:
        lines.append(
            "  - conjunction starts: permissible where they already sound "
            "natural; do not insert one to satisfy this realization"
        )
    if realization.question_eligible:
        lines.append(
            "  - questions: permissible when the current argument genuinely "
            "asks one; do not manufacture a rhetorical question"
        )
    if realization.fragment_eligible:
        lines.append(
            "  - fragments: a deliberate fragment is permissible for natural "
            "emphasis; do not manufacture one"
        )
    if realization.transition_density_tendency != "minimal":
        lines.append(
            "  - transitions: the anchor's signposting was "
            f"{realization.transition_density_tendency}; use only transitions "
            "the logic needs"
        )
    if realization.opening_behavior:
        lines.append(
            "  - opening tendency: "
            f"{realization.opening_behavior.replace('_', ' ')}; the prompt or "
            "outline wins if it supplies an opening"
        )
    if realization.ending_behavior:
        lines.append(
            "  - closing tendency: "
            f"{realization.ending_behavior.replace('_', ' ')}; do not force it "
            "over the argument's natural endpoint"
        )
    reasoning_guidance = _reasoning_guidance(realization.reasoning_shape)
    if reasoning_guidance:
        lines.append(
            "  - development tendency: the anchor used "
            f"{reasoning_guidance}; borrow that broad movement only when it "
            "fits this argument, never as a paragraph-by-paragraph checklist"
        )
    lines.append(f"  - {realization.escape_clause}")
    return lines
