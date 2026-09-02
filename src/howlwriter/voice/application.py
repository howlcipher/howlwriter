"""Turning a VoiceProfile into prompt text, without turning it into a stencil.

This module is where the anti-cloning promise is either kept or broken. The
profile itself cannot hold a phrase from the corpus -- that was settled by the
schema -- but a rendering that says "sentence_length_mean: 24.3" invites the
model to write every sentence at 24 words, which reproduces the failure by a
different route.

So tendencies are rendered as ranges and habits rather than targets, the
instructions state plainly that a trait is a distribution to vary around
rather than a rule to hit, and the profile is explicitly ranked below facts,
constraints, and mode.

Contexts modify, they do not replace. A mode selects a context, that context's
traits are layered over the global ones, and a context built from thin
evidence is marked as such so it cannot read as more authoritative than the
global profile it is adjusting.
"""

from __future__ import annotations

from howlwriter.domain.modes import WritingMode
from howlwriter.domain.voice import TraitValue, VoiceProfile

#: Which context each writing mode draws on. A mode is a task; a context is a
#: register. LinkedIn writing and a work document share a register even though
#: they are different tasks, which is why both map to `professional` rather
#: than each getting a mode-specific voice.
MODE_CONTEXTS: dict[WritingMode, str] = {
    WritingMode.LINKEDIN: "professional",
    WritingMode.PROFESSIONAL: "professional",
    WritingMode.EMAIL: "professional",
    WritingMode.ACADEMIC: "academic",
    WritingMode.DOCUMENTATION: "academic",
    WritingMode.TECHNICAL: "professional",
    WritingMode.ARTICLE: "general",
    WritingMode.CASUAL: "general",
    WritingMode.CUSTOM: "general",
}

#: A context trait needs at least this much confidence before it is allowed
#: to override the global tendency. Below it the context is reported as
#: observed-but-thin, so weak context evidence cannot overpower a global
#: pattern that many more documents support.
MIN_CONTEXT_TRAIT_CONFIDENCE = 0.35

#: Traits below this confidence are shown as tentative rather than dropped:
#: hiding them would overstate how much the profile knows.
LOW_CONFIDENCE = 0.45


def context_for_mode(mode: object) -> str:
    """The voice context a writing mode should draw on."""
    if isinstance(mode, WritingMode):
        return MODE_CONTEXTS.get(mode, "general")
    if isinstance(mode, str):
        try:
            return MODE_CONTEXTS.get(WritingMode(mode.strip().lower()), "general")
        except ValueError:
            return "general"
    return "general"


def _describe_range(low: float | None, high: float | None, unit: str) -> str:
    if low is None or high is None:
        return ""
    return f"typically {low:.0f}-{high:.0f} {unit}, and deliberately not uniform"


def _trait_line(name: str, trait: TraitValue) -> str:
    label = name.replace("_", " ")
    line = f"  - {label}: {trait.value}"
    if trait.source == "user":
        return line + "  (set by you; overrides the corpus)"
    if trait.confidence < LOW_CONFIDENCE:
        return line + f"  (low confidence {trait.confidence:.2f}; treat as a weak hint)"
    return line


def render_profile(profile: VoiceProfile | None, mode: object = None) -> str:
    """Render a profile for the Humanizer prompt.

    Handles both schema generations: a legacy hand-written profile renders its
    scalar fields and its representative examples exactly as before, while a
    corpus-built profile renders traits, the selected context, and overrides.
    """
    if profile is None:
        return "None"

    if not profile.is_corpus_built:
        return _render_legacy(profile)

    context_name = context_for_mode(mode)
    context = profile.contexts.get(context_name)
    lines: list[str] = []

    lines.append(f"personal voice: {profile.profile_name or 'unnamed'}")
    lines.append(
        "This describes how this author TENDS to write. It is a distribution, "
        "not a template."
    )
    lines.append("")

    # --- how to use it ---
    lines += [
        "HOW TO APPLY THIS VOICE:",
        "- These are tendencies across many documents, not rules for this one.",
        "- Realize each trait in a way that suits THIS topic, draft, and purpose. "
        "The same trait should look different in different pieces.",
        "- Match the author's natural VARIATION, not their average. Writing every "
        "sentence at the mean length is a failure, not a match.",
        "- Never invent a signature opening, a catchphrase, or a recurring closing move.",
        "- In conversational and social modes, preserve natural conversational pronouns "
        "('I', 'you', 'your business', 'we') when present; do not convert them to stiff formalisms.",
        "- Assertive qualification means stating conclusions clearly, NOT stripping "
        "legitimate epistemic hedging ('probably', 'may', 'if') or turning nuanced "
        "hypotheses into blunt absolutes.",
        "- The voice governs expression only. It must not change facts, evidence, "
        "citations, quotations, numbers, dates, identifiers, or logical order.",
        "- Explicit instructions, length limits, and mode rules outrank this profile "
        "in every case.",
        "- If the draft already reads like this author, change nothing.",
        "",
    ]

    # --- global tendencies ---
    if profile.traits:
        lines.append("GLOBAL TENDENCIES:")
        for name, trait in sorted(profile.traits.items()):
            lines.append(_trait_line(name, trait))
        lines.append("")

    # --- measured ranges, expressed as spread ---
    distributions = profile.distributions
    if distributions is not None:
        spread: list[str] = []
        sentence_range = _describe_range(
            distributions.sentence_length_p10, distributions.sentence_length_p90, "words"
        )
        if sentence_range:
            spread.append(f"  - sentence length: {sentence_range}")
        if distributions.paragraph_words_mean:
            spread.append(
                f"  - paragraph length: around {distributions.paragraph_words_mean:.0f} "
                "words on average, with real variation between short and long"
            )
        if spread:
            lines.append("MEASURED SPREAD (match the range, do not converge on the middle):")
            lines.extend(spread)
            lines.append("")

    # --- context adjustments ---
    if context is not None and context.traits:
        strong = {
            name: trait for name, trait in context.traits.items()
            if trait.confidence >= MIN_CONTEXT_TRAIT_CONFIDENCE
        }
        weak = {
            name: trait for name, trait in context.traits.items()
            if trait.confidence < MIN_CONTEXT_TRAIT_CONFIDENCE
        }
        lines.append(
            f"IN {context_name.upper()} WRITING this author differs from the above "
            f"(based on {context.document_count} document(s), "
            f"{context.word_count:,} words):"
        )
        for name, trait in sorted(strong.items()):
            lines.append(_trait_line(name, trait))
        for name, trait in sorted(weak.items()):
            lines.append(
                f"  - {name.replace('_', ' ')}: possibly {trait.value} "
                "(thin evidence; do not let this override the global tendency)"
            )
        lines.append(
            "  These adjust the global tendencies for this context. They do not "
            "replace them, and they never override the mode's own rules."
        )
        lines.append("")
    elif context_name:
        lines.append(
            f"No {context_name} context was built for this voice, so apply the global "
            "tendencies within the mode's rules."
        )
        lines.append("")

    # --- user overrides, which win ---
    overrides = profile.overrides
    if overrides is not None and (overrides.preserve or overrides.avoid or overrides.traits):
        lines.append("AUTHOR'S EXPLICIT INSTRUCTIONS (these outrank everything above):")
        for item in overrides.preserve:
            lines.append(f"  - preserve: {item}")
        for item in overrides.avoid:
            lines.append(f"  - avoid: {item}")
        for name, value in sorted(overrides.traits.items()):
            lines.append(f"  - {name.replace('_', ' ')} must be {value}")
        if overrides.notes:
            lines.append(f"  - note: {overrides.notes}")
        lines.append("")

    # --- honesty about the evidence ---
    summary = profile.corpus_summary
    validation = profile.validation
    if summary is not None or validation is not None:
        parts: list[str] = []
        if summary is not None:
            parts.append(
                f"built from {summary.included_documents} document(s), "
                f"{summary.training_words:,} words; corpus {summary.sufficiency}"
            )
        if validation is not None and validation.overall_confidence != "UNKNOWN":
            parts.append(f"overall confidence {validation.overall_confidence}")
        lines.append("EVIDENCE: " + "; ".join(parts) + ".")
        if summary is not None and summary.sufficiency in ("limited", "insufficient"):
            lines.append(
                "The corpus is small, so treat these tendencies as weak signals and "
                "prefer leaving good prose alone."
            )

    return "\n".join(lines).rstrip()


def _render_legacy(profile: VoiceProfile) -> str:
    """Render a pre-corpus profile exactly as the Humanizer always has.

    Hand-written profiles chose their representative examples deliberately, so
    they keep them. Only corpus-built profiles are held to the no-examples
    rule, because only they were derived from writing the user did not
    individually approve for this purpose.
    """
    from howlwriter.domain.voice import VoiceExample

    parts: list[str] = []
    if profile.author_name:
        parts.append(f"author_name: {profile.author_name}")
    if profile.formality is not None:
        parts.append(f"formality: {profile.formality}")
    if profile.sentence_length_mean is not None:
        parts.append(f"sentence_length_mean: {profile.sentence_length_mean:.1f}")
    if profile.sentence_length_stdev is not None:
        parts.append(f"sentence_length_stdev: {profile.sentence_length_stdev:.1f}")
    if profile.paragraph_length_mean is not None:
        parts.append(f"paragraph_length_mean: {profile.paragraph_length_mean:.1f}")
    if profile.contraction_rate is not None:
        parts.append(f"contraction_rate: {profile.contraction_rate:.2f}")
    if profile.fragment_rate is not None:
        parts.append(f"fragment_rate: {profile.fragment_rate:.2f}")
    if profile.rhetorical_question_rate is not None:
        parts.append(f"rhetorical_question_rate: {profile.rhetorical_question_rate:.2f}")
    if profile.preferred_phrases:
        parts.append(f"preferred_phrases: {', '.join(profile.preferred_phrases)}")
    if profile.disliked_phrases:
        parts.append(f"disliked_phrases: {', '.join(profile.disliked_phrases)}")
    if profile.structural_notes:
        parts.append(f"structural_notes: {profile.structural_notes}")
    examples = [
        ex.text if isinstance(ex, VoiceExample) else str(ex.get("text", ""))
        for ex in profile.representative_examples[:3]
    ]
    if examples:
        parts.append("representative_examples:")
        for example in examples:
            parts.append(f"  - {example}")
    return "\n".join(parts) if parts else "Empty VoiceProfile"
