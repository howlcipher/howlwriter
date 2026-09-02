"""How much of the finished piece the model was left to invent.

The product claim this supports is that supplying more authorship buys more
control. That claim is worth nothing unless it can be checked, so freedom is
DERIVED from the outline rather than declared by whoever ran the command. A
user who writes nine claims and three verbatim sentences gets LOW whether or
not anyone remembered to say so.

Two axes, deliberately kept apart because they fail differently.

COVERAGE is how much of the intended length the user already wrote. It is the
dominant signal at the top of the range: when someone hands over a near
complete draft, the model's job is editing, and no amount of structural
sparseness changes that.

STRUCTURE is how many independent authorship decisions the user made -- claims,
required points, ordering, an ending, examples. It is what separates a
structured outline from a bare idea when neither supplies much prose.

Neither is a measurement of the output. Both are facts about the input, which
is the only thing the system can honestly report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.domain.outline import (
    GenerationFreedom,
    NodeKind,
    Outline,
)

#: Share of the target length already supplied as user prose, at or above which
#: the task is editing rather than writing.
NEAR_COMPLETE_COVERAGE = 0.70

#: Coverage at or above which the model is joining user prose rather than
#: producing the body of the piece.
SUBSTANTIAL_COVERAGE = 0.30

#: Authorship decisions counted toward the structure signal.
_STRUCTURE_KINDS = (
    NodeKind.THESIS,
    NodeKind.CLAIM,
    NodeKind.REQUIRED_POINT,
    NodeKind.HEADING,
    NodeKind.EXAMPLE,
    NodeKind.EXPERIENCE,
    NodeKind.ENDING,
    NodeKind.TRANSITION,
    NodeKind.PRESERVE,
)

#: Structure counts at which the outline stops being a sketch and starts being
#: a specification. Heuristic, and documented as one: they were chosen so the
#: five worked examples in the milestone brief -- sparse idea, minimal outline,
#: structured outline, authorship-rich outline, near-complete draft -- land on
#: the five states in order. They are not derived from anything.
#:
#: The high threshold is deliberately far above the moderate one. Counting
#: alone cannot separate a structured outline from an authorship-rich one: nine
#: claims and an ordering is a lot of structure, but the model still writes
#: every sentence. What actually separates them is CONCRETE AUTHORED MATERIAL
#: -- passages the user wrote and examples they supplied -- so that, not the
#: count, is the primary route to LOW.
RICH_STRUCTURE = 12
MODERATE_STRUCTURE = 4

#: When no target length is given, this stands in so coverage stays meaningful
#: rather than dividing by nothing. Roughly a short article.
_ASSUMED_TARGET_WORDS = 600


@dataclass
class FreedomAssessment:
    """The verdict and every input that produced it.

    The inputs travel with the verdict so a provenance reader can disagree with
    the thresholds without having to re-derive the counts.
    """

    freedom: GenerationFreedom
    supplied_words: int = 0
    target_words: int = 0
    coverage: float = 0.0
    structure_signals: int = 0
    preserved_sentences: int = 0
    claims: int = 0
    required_points: int = 0
    examples: int = 0
    voice_seeds: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "freedom": self.freedom.value,
            "supplied_words": self.supplied_words,
            "target_words": self.target_words,
            "coverage": round(self.coverage, 4),
            "structure_signals": self.structure_signals,
            "preserved_sentences": self.preserved_sentences,
            "claims": self.claims,
            "required_points": self.required_points,
            "examples": self.examples,
            "voice_seeds": self.voice_seeds,
            "reasons": list(self.reasons),
        }


def assess_freedom(outline: Outline) -> FreedomAssessment:
    """Derive the generation-freedom state from what the outline supplies."""
    supplied = outline.supplied_words()
    target = outline.target_words or outline.max_words or _ASSUMED_TARGET_WORDS
    coverage = (supplied / target) if target else 0.0

    structure_nodes = outline.nodes_of(*_STRUCTURE_KINDS)
    signals = len(structure_nodes)
    if outline.enforce_order and len(outline.required_points()) > 1:
        # Fixing the order is itself an authorship decision, and a substantive
        # one: it is the difference between "cover these" and "argue this way".
        signals += 1

    assessment = FreedomAssessment(
        freedom=GenerationFreedom.HIGH,
        supplied_words=supplied,
        target_words=target,
        coverage=coverage,
        structure_signals=signals,
        preserved_sentences=len(outline.preserved()),
        claims=len(outline.claims()),
        required_points=len(outline.required_points()),
        examples=len(outline.nodes_of(NodeKind.EXAMPLE, NodeKind.EXPERIENCE)),
        voice_seeds=len(outline.voice_seeds()),
    )

    if coverage >= NEAR_COMPLETE_COVERAGE:
        assessment.freedom = GenerationFreedom.MINIMAL
        assessment.reasons.append(
            f"user prose already covers {coverage:.0%} of the target length, "
            "so the remaining task is editing rather than writing"
        )
        return assessment

    # Concrete authored material: passages the user wrote, and examples only
    # they could supply. These are what make an outline authorship-rich rather
    # than merely detailed.
    concrete = assessment.preserved_sentences + assessment.examples
    if (
        coverage >= SUBSTANTIAL_COVERAGE
        or signals >= RICH_STRUCTURE
        or (concrete >= 2 and signals >= MODERATE_STRUCTURE)
    ):
        assessment.freedom = GenerationFreedom.LOW
        if coverage >= SUBSTANTIAL_COVERAGE:
            assessment.reasons.append(
                f"user prose covers {coverage:.0%} of the target length"
            )
        if concrete >= 2 and signals >= MODERATE_STRUCTURE:
            assessment.reasons.append(
                f"{assessment.preserved_sentences} preserved passage(s) and "
                f"{assessment.examples} supplied example(s) sit inside "
                f"{signals} authorship decisions, so the model is joining the "
                "author's material rather than producing the substance"
            )
        elif signals >= RICH_STRUCTURE:
            assessment.reasons.append(
                f"{signals} authorship decisions supplied "
                f"({assessment.claims} claim(s), "
                f"{assessment.preserved_sentences} preserved passage(s))"
            )
        return assessment

    if signals >= MODERATE_STRUCTURE:
        assessment.freedom = GenerationFreedom.MEDIUM
        assessment.reasons.append(
            f"{signals} authorship decisions supplied, but little user prose "
            f"({coverage:.0%} of target)"
        )
        return assessment

    assessment.reasons.append(
        f"only {signals} authorship decision(s) and {supplied} word(s) of user "
        "prose supplied, so most of the piece is the model's"
    )
    return assessment
