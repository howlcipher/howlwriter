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
from howlwriter.domain.structural_realization import StructuralRealization
from howlwriter.domain.voice import RateDistribution, TraitValue, VoiceProfile

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

#: Below this share of agreement, the winning label is a plurality rather than
#: a property, and the trait is rendered as varying between documents.
#:
#: Heuristic, not derived. The reasoning is that a label carrying less than
#: half the corpus weight is by definition contradicted by most of the corpus,
#: so 0.50 is the point where "this is how the author writes" stops being a
#: fair summary. It is deliberately not tuned against any one corpus; raising
#: it would hedge traits that are genuinely consistent, and lowering it would
#: restore the failure it exists to prevent, where a fourteen-to-fourteen
#: split renders as an unqualified instruction.
MIN_TRAIT_AGREEMENT = 0.50


#: How each zero-inflated behaviour is named and counted when rendered.
#:
#: The unit is not cosmetic. `features.py` measures some of these per hundred
#: words (pronouns, parentheses, contractions, semicolons, em dashes) and
#: others as a share of sentences or paragraphs (questions, fragments,
#: transitions, sentence-initial conjunctions, lists, headings). Rendering a
#: share of sentences as though it were a count per hundred words would state a
#: number that is wrong by an order of magnitude, so each entry carries its own
#: unit and the renderer never guesses.
_RATE_PRESENTATION: dict[str, tuple[str, str]] = {
    "first_person_rate": ("first person", "per100"),
    "second_person_rate": ("second person", "per100"),
    "parenthetical_rate": ("parentheses", "per100"),
    "contraction_rate": ("contractions", "per100"),
    "semicolon_rate": ("semicolons", "per100"),
    "em_dash_rate": ("em dashes", "per100"),
    "question_rate": ("questions", "share_sentences"),
    "exclamation_rate": ("exclamations", "share_sentences"),
    "transition_rate": ("transitional signposting", "share_sentences"),
    "sentence_initial_conjunction_rate": ("sentences opening on a conjunction", "share_sentences"),
    "fragment_rate": ("sentence fragments", "share_sentences"),
    "list_rate": ("lists", "share_paragraphs"),
    "heading_rate": ("headings", "share_paragraphs"),
}

#: Presence above this reads as "essentially always", below it as "rarely".
#: Between them the split itself is the finding worth reporting.
_ALWAYS_PRESENT = 0.95
_RARELY_PRESENT = 0.10


def _format_rate(value: float, unit: str) -> str:
    if unit == "per100":
        return f"{value:.1f}"
    return f"{value:.0%}"


def _rate_line(name: str, dist: RateDistribution) -> str:
    """One behaviour, described as presence plus intensity.

    Deliberately prose rather than a number pair. "first_person_rate: 1.01"
    invites the model to hit 1.01 in every piece, which is the averaging
    failure re-created at the prompt layer; saying that four pieces in ten use
    none of it describes a corpus the model can vary within.
    """
    label, unit = _RATE_PRESENTATION[name]
    presence = dist.document_presence_rate
    tail = ""
    if dist.has_spread:
        low = _format_rate(dist.when_present_p10, unit)
        high = _format_rate(dist.when_present_p90, unit)
        suffix = " per 100 words" if unit == "per100" else " of sentences" \
            if unit == "share_sentences" else " of paragraphs"
        tail = f"; where present, roughly {low} to {high}{suffix}"

    if presence >= _ALWAYS_PRESENT:
        return f"  - {label}: present in nearly every piece{tail}"
    if presence <= _RARELY_PRESENT:
        return f"  - {label}: absent from most pieces ({1 - presence:.0%}){tail}"
    return (
        f"  - {label}: absent from about {1 - presence:.0%} of pieces, "
        f"present in the rest{tail}"
    )


#: Presence gap below which a context is saying the same thing as the global
#: profile. Reporting it again would double-count one observation.
_PRESENCE_DIFFERENCE = 0.15


def _presence_differs(
    context_dist: RateDistribution,
    global_dist: RateDistribution | None,
) -> bool:
    if context_dist.documents_measured <= 0:
        return False
    if global_dist is None:
        return True
    gap = abs(context_dist.document_presence_rate - global_dist.document_presence_rate)
    return gap >= _PRESENCE_DIFFERENCE


def _render_rate_distributions(
    rates: dict[str, RateDistribution],
) -> list[str]:
    lines: list[str] = []
    renderable = [
        (name, dist)
        for name, dist in sorted(rates.items())
        if name in _RATE_PRESENTATION and dist.documents_measured > 0
    ]
    if not renderable:
        return lines
    lines.append(
        "PRESENCE ACROSS PIECES (how often the author reaches for a habit at "
        "all, and how hard when they do):"
    )
    lines.append(
        "  (These are two separate facts. A habit absent from half the corpus "
        "is not a habit to use at half strength everywhere -- it is one to use "
        "fully in some pieces and not at all in others. Let this piece fall "
        "where its subject puts it; do not average, and do not treat any "
        "figure below as a target to hit.)"
    )
    for name, dist in renderable:
        lines.append(_rate_line(name, dist))
    lines.append("")
    return lines


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


def _has_spread(low: float | None, high: float | None) -> bool:
    """Whether a p10/p90 pair actually describes a range.

    A missing percentile and a percentile of zero have to be treated the same
    way. `0.0` is what a stale feature cache leaves behind when a field is
    restored from a record written before that field existed, and it is also
    what a degenerate corpus produces. Rendering it anyway yields
    "typically 0-0 words (mean ~80 words)", which is worse than saying nothing:
    it hands the model a contradiction and buries the usable mean inside it.
    """
    if low is None or high is None:
        return False
    return high > low > 0


def _describe_range(low: float | None, high: float | None, unit: str) -> str:
    if not _has_spread(low, high):
        return ""
    return f"typically {low:.0f}-{high:.0f} {unit}, and deliberately not uniform"


def _is_split(trait: TraitValue) -> bool:
    """Whether the corpus disagrees with itself about this trait.

    Two ways that happens. The plurality can be too thin to speak for the
    corpus (below `MIN_TRAIT_AGREEMENT`), or it can be no plurality at all --
    a dead heat that `_label_agreement` resolved alphabetically so rebuilds
    stay stable. The second case can clear any agreement threshold and still be
    meaningless, so it is checked separately.
    """
    if trait.source == "user":
        return False
    if not trait.secondary or trait.secondary == trait.value:
        return False
    if getattr(trait, "tied", False):
        return True
    return bool(trait.agreement and trait.agreement < MIN_TRAIT_AGREEMENT)


def _trait_line(name: str, trait: TraitValue) -> str:
    label = name.replace("_", " ")
    if trait.source == "user":
        return f"  - {label}: {trait.value}  (set by you; overrides the corpus)"

    # A plurality label is not a property of the author. Stating one as though
    # it were is how a trait becomes a signature: a corpus split evenly between
    # documents that use parentheses and documents that do not renders as
    # "frequent", and every generated piece then carries one. Saying the
    # tendency varies is both the honest reading of the evidence and the thing
    # that lets some pieces come out without the trait at all.
    if getattr(trait, "tied", False):
        # Naming a winner here would report a tie-break as a finding. The two
        # labels are given in the order the sort produced, with no claim that
        # the first one leads.
        line = (
            f"  - {label}: SPLIT -- the corpus divides evenly between "
            f"{trait.value} ({trait.agreement:.0%}) and {trait.secondary} "
            f"({trait.secondary_agreement:.0%}); neither is this author's "
            "tendency, so let the piece decide"
        )
    elif _is_split(trait):
        line = (
            f"  - {label}: VARIES -- {trait.value} in about "
            f"{trait.agreement:.0%} of documents, {trait.secondary} in about "
            f"{trait.secondary_agreement:.0%}"
        )
    else:
        line = f"  - {label}: {trait.value}"

    if trait.confidence < LOW_CONFIDENCE:
        return line + f"  (low confidence {trait.confidence:.2f}; treat as a weak hint)"
    return line


def render_profile(
    profile: VoiceProfile | None,
    mode: object = None,
    realization: StructuralRealization | None = None,
) -> str:
    """Render a profile for the Humanizer prompt.

    Handles both schema generations: a legacy hand-written profile renders its
    scalar fields and its representative examples exactly as before, while a
    corpus-built profile renders traits, the selected context, and overrides.

    When `realization` is supplied, per-piece soft structural targets are rendered
    instead of static corpus-wide ranges, breaking model attractor convergence.
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
        "- CONTEXTUAL STRUCTURAL VARIANCE: Match the author's natural variation between documents. "
        "Do NOT force every generated document into a uniform shape, paragraph count, or rhythm. "
        "If the author uses a mix of punchy short focus paragraphs and fuller analytical paragraphs, "
        "reflect that mix naturally based on the idea's requirements.",
        "- DISTRIBUTION OVER CHECKLIST: Trait rates (e.g. sentence-initial conjunctions, fragments, "
        "parentheticals, questions, transitions) are overall corpus frequencies, NOT per-paragraph quotas. "
        "A 10% rate means an occasional occurrence across a piece, NOT every sentence or every paragraph. "
        "Do NOT force a feature merely because it exists in the profile.",
        "- ANTI-HYPER-SYMMETRY: Avoid mechanically regular paragraph structures "
        "(e.g. 4 consecutive paragraphs with identical sentence counts or word counts, "
        "rigid thesis -> explanation -> explanation -> conclusion blocks, or repeated opening formulas).",
        "- Never invent fake anecdotes, deliberate misspellings, grammar errors, or contrived quirks.",
        "- Never invent a signature opening, a catchphrase, or a recurring closing move.",
        "- In conversational and social modes, preserve natural conversational pronouns "
        "('I', 'you', 'your business', 'we') and contractions ('isn't', 'don't', 'can't') when natural; "
        "do not convert them to stiff third-person formalisms ('enterprises', 'one', 'market participants').",
        "- ANTI-THESAURUS RULE: High formality or advanced vocabulary tendencies mean conceptual clarity "
        "and precise reasoning, NOT thesaurus upgrades. NEVER replace normal conversational words "
        "('developers', 'build', 'use', 'companies', 'cheap', 'replaceable', 'moat') with hyper-formal "
        "or academic jargon ('substitutability', 'commoditization', 'utilize', 'construct', "
        "'vulnerable to substitution').",
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
        if any(_is_split(trait) for trait in profile.traits.values()):
            lines.append(
                "  (A trait marked VARIES is one the corpus is split on. Choose "
                "whichever side suits this piece and let other pieces differ; "
                "applying it every time is what turns a tendency into a tell.)"
            )
        for name, trait in sorted(profile.traits.items()):
            lines.append(_trait_line(name, trait))
        lines.append("")

    if realization is not None:
        from howlwriter.voice.realization import render_structural_realization_prompt

        lines.extend(render_structural_realization_prompt(realization))
        lines.append("")
    else:
        # --- measured ranges, expressed as spread ---
        distributions = profile.distributions
        if distributions is not None:
            spread: list[str] = []
            sentence_range = _describe_range(
                distributions.sentence_length_p10, distributions.sentence_length_p90, "words"
            )
            if sentence_range:
                spread.append(f"  - sentence length: {sentence_range}")
            if _has_spread(distributions.paragraph_words_p10, distributions.paragraph_words_p90):
                mean_w = distributions.paragraph_words_mean or 0
                spread.append(
                    f"  - paragraph length: typically {distributions.paragraph_words_p10:.0f}-"
                    f"{distributions.paragraph_words_p90:.0f} words (mean ~{mean_w:.0f} words), "
                    "with real variation between short focal paragraphs and fuller blocks"
                )
            elif distributions.paragraph_words_mean:
                spread.append(
                    f"  - paragraph length: around {distributions.paragraph_words_mean:.0f} "
                    "words on average, with real variation between short and long"
                )
            if _has_spread(
                distributions.paragraph_sentences_p10, distributions.paragraph_sentences_p90
            ):
                mean_s = distributions.paragraph_sentences_mean or 0
                spread.append(
                    f"  - paragraph sentence count: typically {distributions.paragraph_sentences_p10:.0f}-"
                    f"{distributions.paragraph_sentences_p90:.0f} sentences (mean ~{mean_s:.1f})"
                )
            if (
                distributions.single_sentence_paragraph_rate
                and distributions.single_sentence_paragraph_rate > 0.10
            ):
                rate = distributions.single_sentence_paragraph_rate
                spread.append(
                    f"  - single-sentence paragraphs: present (~{rate:.0%} of paragraphs), "
                    "used selectively for focal emphasis rather than every block"
                )
            if distributions.short_sentence_rate and distributions.long_sentence_rate:
                s_rate = distributions.short_sentence_rate
                l_rate = distributions.long_sentence_rate
                spread.append(
                    f"  - sentence cadence mix: blends concise statements (<=9 words: ~{s_rate:.0%}) "
                    f"with developed sentences (>=28 words: ~{l_rate:.0%})"
                )
            if spread:
                lines.append("MEASURED SPREAD (match the range, do not converge on the middle):")
                lines.extend(spread)
                lines.append("")

        lines.extend(_render_rate_distributions(profile.rate_distributions))

    # --- context adjustments ---
    if context is not None and (context.traits or context.distributions):
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
            label = name.replace("_", " ")
            if getattr(trait, "tied", False):
                # Thin evidence and a dead heat are different problems, and the
                # caveat only fixes the first. Saying "possibly prominent"
                # about a trait the slice split evenly between prominent and
                # absent still names a winner that does not exist.
                lines.append(
                    f"  - {label}: SPLIT even in this context -- "
                    f"{trait.value} and {trait.secondary} in equal measure "
                    "(thin evidence either way; do not let this override the "
                    "global tendency)"
                )
            else:
                lines.append(
                    f"  - {label}: possibly {trait.value} "
                    "(thin evidence; do not let this override the global tendency)"
                )
        # Context-specific structural spread if available with confidence
        if context.confidence >= MIN_CONTEXT_TRAIT_CONFIDENCE and context.distributions:
            cd = context.distributions
            ctx_spread = []
            if _has_spread(cd.get("paragraph_words_p10"), cd.get("paragraph_words_p90")):
                ctx_spread.append(
                    f"  - context paragraph length: typically {cd['paragraph_words_p10']:.0f}-"
                    f"{cd['paragraph_words_p90']:.0f} words"
                )
            elif cd.get("paragraph_words_mean") is not None:
                ctx_spread.append(
                    f"  - context paragraph length mean: ~{cd['paragraph_words_mean']:.0f} words"
                )
            if _has_spread(cd.get("sentence_length_p10"), cd.get("sentence_length_p90")):
                ctx_spread.append(
                    f"  - context sentence length: typically {cd['sentence_length_p10']:.0f}-"
                    f"{cd['sentence_length_p90']:.0f} words"
                )
            if ctx_spread:
                lines.append("  Context Structural Cadence:")
                lines.extend(ctx_spread)
        # Context presence rates are reported only where the context itself is
        # well enough evidenced to adjust the global profile, and only where
        # they actually DIFFER from it. A thin slice repeating the global
        # presence rate would read as independent confirmation of a number it
        # simply inherited.
        if context.confidence >= MIN_CONTEXT_TRAIT_CONFIDENCE and context.rate_distributions:
            differing = {
                name: dist
                for name, dist in context.rate_distributions.items()
                if _presence_differs(dist, profile.rate_distributions.get(name))
            }
            ctx_rates = _render_rate_distributions(differing)
            if ctx_rates:
                lines.append("  Context presence (differs from the global figures above):")
                lines.extend(ctx_rates[2:-1])
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
