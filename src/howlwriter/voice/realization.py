"""Per-Piece Structural Realization Engine.

Derives ONE plausible structural realization for a generated piece from:
  Author Corpus Distributions
  + Current Input
  + Outline Authority
  + Writing Mode
  + Context
  -> StructuralRealization

This replaces the static shared-band prompt ranges that caused model convergence.
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
    r"\b(I|I'm|I've|I'd|I'll|me|my|mine|we|we're|we've|our|ours|us)\b", re.I
)

#: Known mappings from WritingMode to VoiceProfile context names.
MODE_CONTEXT_MAP: dict[str, str] = {
    "linkedin": "professional",
    "short_form": "professional",
    "academic": "academic",
    "essay": "general",
    "article": "general",
    "technical": "professional",
}

#: Typical target word counts per mode when not explicitly supplied.
DEFAULT_TARGET_WORDS: dict[str, int] = {
    "linkedin": 220,
    "short_form": 250,
    "academic": 1200,
    "essay": 900,
    "article": 700,
    "technical": 600,
}


def derive_seed(
    profile_name: str,
    mode: str,
    input_text: str = "",
    outline_summary: str = "",
    target_words: int | None = None,
) -> int:
    """Deterministically derive a 32-bit positive integer seed from the run parameters.

    Ensures that identical inputs produce identical structural selections,
    while different inputs naturally explore different valid parts of the
    author's distribution.
    """
    hasher = hashlib.sha256()
    hasher.update(profile_name.encode("utf-8"))
    hasher.update(b"::")
    hasher.update(mode.encode("utf-8"))
    hasher.update(b"::")
    hasher.update(input_text[:500].encode("utf-8"))
    hasher.update(b"::")
    hasher.update(outline_summary.encode("utf-8"))
    hasher.update(b"::")
    hasher.update(str(target_words or 0).encode("utf-8"))
    digest = hasher.digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def derive_structural_realization(
    profile: VoiceProfile | None,
    mode: WritingMode | str | None = None,
    outline: Outline | None = None,
    target_words: int | None = None,
    input_text: str = "",
    seed: int | None = None,
    freedom: Any = None,
) -> StructuralRealization | None:
    """Derive soft structural targets for ONE piece from measured corpus evidence."""
    if profile is None:
        return None

    mode_str = mode.value if isinstance(mode, WritingMode) else (str(mode) if mode else "article")
    mode_str_clean = mode_str.lower().strip()

    # 1. Determine effective target words
    effective_target_words: int
    if target_words and target_words > 0:
        effective_target_words = target_words
    elif outline and getattr(outline, "target_words", None):
        effective_target_words = outline.target_words  # type: ignore[assignment]
    else:
        effective_target_words = DEFAULT_TARGET_WORDS.get(mode_str_clean, 500)

    # 2. Context resolution and evidence pool selection
    desired_context = MODE_CONTEXT_MAP.get(mode_str_clean, "general")
    ctx = profile.contexts.get(desired_context)
    source_context: str
    candidate_vectors: list[StructuralVector] = []

    if ctx is not None and ctx.document_count >= 3 and ctx.confidence >= 0.25 and ctx.structural_vectors:
        source_context = desired_context
        candidate_vectors = [v for v in ctx.structural_vectors if v.words > 0]
    elif profile.structural_vectors:
        source_context = (
            f"global (context '{desired_context}' insufficient: {ctx.document_count if ctx else 0} docs)"
            if ctx is not None
            else "global"
        )
        candidate_vectors = [v for v in profile.structural_vectors if v.words > 0]
    else:
        source_context = "global (distribution fallback)"
        candidate_vectors = []

    # 3. Seed initialization
    outline_repr = ""
    if outline:
        node_len = len(getattr(outline, "nodes", []))
        tw = getattr(outline, "target_words", "")
        outline_repr = f"nodes={node_len};target={tw}"

    actual_seed = seed
    if actual_seed is None:
        actual_seed = derive_seed(
            profile_name=profile.profile_name or "voice",
            mode=mode_str_clean,
            input_text=input_text,
            outline_summary=outline_repr,
            target_words=effective_target_words,
        )

    rng = random.Random(actual_seed)
    overrides: list[str] = []

    # 4. Length-conditioned anchor selection or quantile derivation
    if candidate_vectors:
        selection_method = "EMPIRICAL_ANCHOR_VECTOR"
        sample_count = len(candidate_vectors)

        # Length conditioning: prefer vectors reasonably compatible with target length if available
        close_length = [
            v for v in candidate_vectors
            if (effective_target_words * 0.5) <= v.words <= (effective_target_words * 2.0)
        ]
        length_compatible = [
            v for v in candidate_vectors
            if (effective_target_words * 0.25) <= v.words <= (effective_target_words * 4.0)
        ]
        if close_length:
            pool = close_length
        elif len(length_compatible) >= 2:
            pool = length_compatible
        else:
            pool = candidate_vectors
        anchor = rng.choice(pool)

        # Paragraph count & size calculation
        pwm = max(20.0, anchor.paragraph_words_mean if anchor.paragraph_words_mean > 0 else 55.0)
        if 0.5 <= (anchor.words / max(1, effective_target_words)) <= 2.0 and anchor.paragraphs >= 2:
            base_p = anchor.paragraphs
        else:
            base_p = max(2, round(effective_target_words / pwm))

        p_min = max(2, base_p - 1)
        p_max = max(p_min + 1, base_p + 1)
        paragraph_count_region = (p_min, p_max)
        paragraph_words_mean_target = round(pwm, 1)
        paragraph_sentences_mean_target = round(
            max(1.5, anchor.paragraph_sentences_mean if anchor.paragraph_sentences_mean > 0 else 3.0), 1
        )
        single_sentence_paragraph_eligible = anchor.single_sentence_paragraph_rate >= 0.08

        sentence_length_mean_target = round(
            anchor.sentence_length_mean if anchor.sentence_length_mean > 0 else 18.0, 1
        )
        sentence_length_stdev_target = round(
            anchor.sentence_length_stdev if anchor.sentence_length_stdev > 0 else 6.0, 1
        )

        short_rate = anchor.short_sentence_rate
        short_sentence_tendency = (
            "prominent" if short_rate >= 0.22 else ("moderate" if short_rate >= 0.10 else "minimal")
        )

        long_rate = anchor.long_sentence_rate
        long_sentence_tendency = (
            "prominent" if long_rate >= 0.22 else ("moderate" if long_rate >= 0.10 else "minimal")
        )

        trans_rate = anchor.transition_rate
        transition_density_tendency = (
            "moderate" if trans_rate >= 0.08 else ("light" if trans_rate >= 0.03 else "minimal")
        )

        opening_behavior = anchor.opening_class or "direct_thesis"
        ending_behavior = anchor.closing_class or "declarative_stop"

    else:
        # Bounded fallback when no structural vectors exist in legacy profile
        selection_method = "BOUNDED_DISTRIBUTION_SAMPLE"
        dist = profile.distributions
        sample_count = profile.corpus_summary.included_documents if profile.corpus_summary else 0

        pwm = dist.paragraph_words_mean if (dist and dist.paragraph_words_mean > 0) else 60.0
        base_p = max(2, round(effective_target_words / max(20.0, pwm)))
        paragraph_count_region = (max(2, base_p - 1), max(3, base_p + 1))
        paragraph_words_mean_target = round(pwm, 1)
        paragraph_sentences_mean_target = round(dist.paragraph_sentences_mean if dist else 3.0, 1)
        single_sentence_paragraph_eligible = (
            (dist.single_sentence_paragraph_rate >= 0.08) if dist else False
        )
        sentence_length_mean_target = round(dist.sentence_length_mean if dist else 18.0, 1)
        sentence_length_stdev_target = round(dist.sentence_length_stdev if dist else 6.0, 1)
        short_sentence_tendency = "moderate"
        long_sentence_tendency = "moderate"
        transition_density_tendency = "minimal"
        opening_behavior = "direct_thesis"
        ending_behavior = "declarative_stop"

    # 5. Zero-inflated behavioral choices: presence check then intensity
    # First Person
    fp_dist = profile.rate_distributions.get("first_person_rate")
    if fp_dist and fp_dist.document_presence_rate > 0:
        first_person_eligible = rng.random() < fp_dist.document_presence_rate
        if first_person_eligible and fp_dist.has_spread:
            first_person_target_rate = round(
                rng.uniform(fp_dist.when_present_p10 or 0.5, fp_dist.when_present_p90 or 3.5), 2
            )
        elif first_person_eligible:
            first_person_target_rate = round(fp_dist.when_present_mean or 1.5, 2)
        else:
            first_person_target_rate = 0.0
    else:
        first_person_eligible = False
        first_person_target_rate = 0.0

    # Parentheticals
    paren_dist = profile.rate_distributions.get("parenthetical_rate")
    if paren_dist and paren_dist.document_presence_rate > 0:
        parenthetical_eligible = rng.random() < paren_dist.document_presence_rate
        parenthetical_target_count = 1 if parenthetical_eligible else 0
    else:
        parenthetical_eligible = False
        parenthetical_target_count = 0

    # Sentence Initial Conjunctions
    conj_dist = profile.rate_distributions.get("sentence_initial_conjunction_rate")
    if conj_dist and conj_dist.document_presence_rate > 0:
        sentence_initial_conjunction_eligible = rng.random() < conj_dist.document_presence_rate
    else:
        sentence_initial_conjunction_eligible = False

    # Questions
    q_dist = profile.rate_distributions.get("question_rate")
    if q_dist and q_dist.document_presence_rate > 0:
        question_eligible = rng.random() < q_dist.document_presence_rate
    else:
        question_eligible = False

    # 6. Outline & Content Authority Overrides
    if outline is not None:
        nodes = getattr(outline, "nodes", []) or []
        section_kinds = {
            NodeKind.HEADING,
            NodeKind.REQUIRED_POINT,
            "heading",
            "required_point",
            "section",
        }
        section_count = len(
            [
                n for n in nodes
                if getattr(n, "kind", None) in section_kinds
                or getattr(getattr(n, "kind", None), "value", None) in section_kinds
            ]
        )
        if section_count > paragraph_count_region[1]:
            old_region = paragraph_count_region
            paragraph_count_region = (section_count, section_count + 1)
            overrides.append(
                f"OUTLINE_SECTION_COUNT (outline requires {section_count} sections; "
                f"expanded from sampled {old_region})"
            )

    # 7. Current Input Vetoes
    has_personal_input = bool(_FIRST_PERSON_PATTERN.search(input_text))
    if has_personal_input:
        if not first_person_eligible:
            first_person_eligible = True
            first_person_target_rate = max(1.0, first_person_target_rate or 1.5)
            overrides.append("CURRENT_INPUT_PERSONAL_PRESERVED (input contains first-person pronouns)")
    elif mode_str_clean in ("academic", "technical") and first_person_eligible:
        first_person_eligible = False
        first_person_target_rate = 0.0
        overrides.append("IMPERSONAL_INPUT_VETO (impersonal technical input; suppressed first person)")

    # 8. Freedom / Near-Complete Draft Protection
    freedom_str = str(getattr(freedom, "value", freedom) or "").lower()
    if freedom_str == "minimal":
        overrides.append(
            "NEAR_COMPLETE_DRAFT_PRESERVED (minimal freedom; zero structural rewrite pressure)"
        )

    # User overrides from profile take absolute precedence
    if profile.overrides and profile.overrides.traits:
        ot = profile.overrides.traits
        if ot.get("first_person_presence") == "none":
            first_person_eligible = False
            first_person_target_rate = 0.0
            overrides.append("USER_OVERRIDE (first_person_presence: none)")
        elif ot.get("first_person_presence") in ("prominent", "frequent"):
            first_person_eligible = True
            first_person_target_rate = 3.0
            overrides.append("USER_OVERRIDE (first_person_presence: prominent)")

        if ot.get("parenthetical_asides") == "none":
            parenthetical_eligible = False
            parenthetical_target_count = 0
            overrides.append("USER_OVERRIDE (parenthetical_asides: none)")

    return StructuralRealization(
        source_context=source_context,
        sample_count=sample_count,
        selection_method=selection_method,
        seed=actual_seed,
        reproducible=True,
        target_words=effective_target_words,
        paragraph_count_region=paragraph_count_region,
        paragraph_words_mean_target=paragraph_words_mean_target,
        paragraph_sentences_mean_target=paragraph_sentences_mean_target,
        single_sentence_paragraph_eligible=single_sentence_paragraph_eligible,
        sentence_length_mean_target=sentence_length_mean_target,
        sentence_length_stdev_target=sentence_length_stdev_target,
        short_sentence_tendency=short_sentence_tendency,
        long_sentence_tendency=long_sentence_tendency,
        first_person_eligible=first_person_eligible,
        first_person_target_rate=first_person_target_rate,
        parenthetical_eligible=parenthetical_eligible,
        parenthetical_target_count=parenthetical_target_count,
        sentence_initial_conjunction_eligible=sentence_initial_conjunction_eligible,
        question_eligible=question_eligible,
        transition_density_tendency=transition_density_tendency,
        opening_behavior=opening_behavior,
        ending_behavior=ending_behavior,
        overrides=overrides,
    )


def render_structural_realization_prompt(realization: StructuralRealization) -> list[str]:
    """Render the soft per-piece structural realization into prompt instructions."""
    p_low, p_high = realization.paragraph_count_region
    lines: list[str] = [
        "STRUCTURAL REALIZATION FOR THIS PIECE (sampled from author's distribution; guidance only):",
        (
            f"  - structural shape: target roughly {p_low}-{p_high} paragraphs for this piece "
            "(subject to outline and argument requirements)"
        ),
        (
            f"  - paragraph weighting: aim for average blocks around "
            f"~{realization.paragraph_words_mean_target:.0f} words, varying naturally between "
            "focal and fuller blocks"
        ),
        (
            f"  - sentence rhythm: average ~{realization.sentence_length_mean_target:.0f} words/sentence, "
            f"with {realization.short_sentence_tendency} concise statements and "
            f"{realization.long_sentence_tendency} developed sentences"
        ),
    ]

    if realization.single_sentence_paragraph_eligible:
        lines.append(
            "  - focal paragraphs: a single-sentence paragraph is acceptable for deliberate emphasis "
            "if natural, but not required"
        )

    if realization.parenthetical_eligible:
        lines.append(
            "  - parenthetical asides: present for this piece (at most one concise aside, "
            "where it adds authentic nuance)"
        )
    else:
        lines.append(
            "  - parenthetical asides: absent for this piece (reflecting author's natural "
            "variation where most pieces use none)"
        )

    if realization.first_person_eligible:
        lines.append(
            "  - author stance: personal perspective and conversational pronouns ('I', 'we') "
            "are natural here"
        )
    else:
        lines.append(
            "  - author stance: objective or direct argument; do not invent unnecessary "
            "first-person framing"
        )

    if realization.sentence_initial_conjunction_eligible:
        lines.append(
            "  - sentence openings: an occasional sentence starting with a conjunction ('And', 'But') "
            "is acceptable if natural"
        )

    if realization.opening_behavior:
        lines.append(f"  - opening tendency: {realization.opening_behavior.replace('_', ' ')}")

    if realization.ending_behavior:
        lines.append(f"  - closing move: {realization.ending_behavior.replace('_', ' ')}")

    if any("NEAR_COMPLETE_DRAFT_PRESERVED" in o for o in realization.overrides):
        lines.append(
            "  - NEAR-COMPLETE DRAFT PRESERVATION: Existing draft structure strictly outranks "
            "voice realization; minimum necessary edit only."
        )

    lines.append(f"  - {realization.escape_clause}")
    return lines
