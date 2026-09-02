"""Turning an outline into writer instructions that keep their ranking.

The hard part is not listing what the user supplied. It is making the ordering
survive contact with a model that would rather write smoothly than write what
it was told. Three habits do most of the damage:

A model asked to "incorporate" a sentence will improve it. So preserved text is
given its own section, quoted exactly, with the reason stated -- not because a
model obeys reasons, but because the alternative is a rule it can read as
stylistic advice.

A model given a claim and a voice profile will merge them. So the authority
order is stated as an order, at the top, before any of the material it ranks.

A model given a structure and told to sound natural will reorder for rhythm. So
when the outline fixes an order, the prompt says the order is not available for
variation, and the deterministic coverage check verifies it afterwards. The
instruction is the request; the check is the guarantee.
"""

from __future__ import annotations

from howlwriter.domain.outline import (
    GenerationFreedom,
    NodeKind,
    Outline,
    OutlineNode,
)
from howlwriter.outline.freedom import FreedomAssessment

#: Ranking handed to the writer, and the same one `AuthorityLayer` encodes.
AUTHORITY_INSTRUCTION = """AUTHORITY ORDER -- when two things below conflict, the higher one wins:
1. Evidence and grounded fact.
2. Explicit assignment constraints (length, prohibitions, required sections).
3. The user's verbatim sentences. These are theirs; reproduce exactly.
4. The user's claims.
5. The user's conclusions.
6. The user's structure and ordering.
7. The user's examples and experiences.
8. Voice seeds from this outline.
9. The writing mode's own rules.
10. The context-specific voice profile.
11. The global voice profile.
12. Per-piece structural realization (soft guidance; outline and content win).
13. Your connective prose.
14. Your general stylistic preferences.

A lower item NEVER silently rewrites a higher one. If following a lower item
would require changing a higher one, follow the higher one and leave the lower
unsatisfied."""

#: The fabrication boundary. Personal voice is not licence to invent a life.
NO_FABRICATION_INSTRUCTION = """DO NOT INVENT THE AUTHOR'S LIFE.
You may develop the user's ideas. You may NOT invent facts about them: jobs,
employers, coworkers, clients, outages, incidents, meetings, interviews,
conversations, family events, education, timelines, or metrics. You may not
invent opinions and attribute them to the author.

If developing a point would require a personal specific the user did not
supply, do one of two things instead: make the point in general terms, or state
plainly in `gaps` below that the point needs a detail only the author has. Do
not fill the gap with a plausible invention. A convincing fabricated anecdote is
the worst possible output here -- it is indistinguishable from the real thing
and the author cannot stand behind it."""

_FREEDOM_GUIDANCE = {
    GenerationFreedom.HIGH: (
        "The user supplied little beyond direction, so most of this piece is "
        "yours to write. Develop it fully and coherently."
    ),
    GenerationFreedom.MEDIUM: (
        "The user fixed the structure and the points. Write the prose, but the "
        "argument and its order are theirs, not suggestions to improve on."
    ),
    GenerationFreedom.LOW: (
        "The user supplied most of the substance. Your job is connective prose, "
        "development, and transitions. Add as little new assertion as the piece "
        "can survive with."
    ),
    GenerationFreedom.MINIMAL: (
        "The user has essentially written this. Make the minimum necessary "
        "edits for coherence and correctness. If a passage already works, "
        "leave it exactly as it is. Wholesale rewriting is a failure here."
    ),
}


def _render_node(node: OutlineNode, depth: int = 0) -> list[str]:
    indent = "  " * depth
    label = node.kind.value.replace("_", " ").upper()
    lines: list[str] = []

    if node.kind is NodeKind.PRESERVE:
        lines.append(f'{indent}[{label} | {node.id}] reproduce EXACTLY, character for character:')
        lines.append(f'{indent}  "{node.text}"')
    elif node.kind is NodeKind.EXPERIENCE:
        lines.append(
            f"{indent}[{label} | {node.id}] the author's own experience. Use only "
            f"what is stated; add no detail: {node.text}"
        )
    elif node.kind is NodeKind.RESEARCH:
        lines.append(f"{indent}[{label} | {node.id}] must be answered by evidence: {node.text}")
    else:
        lines.append(f"{indent}[{label} | {node.id}] {node.text}")

    if node.target_words:
        lines.append(f"{indent}  (about {node.target_words} words)")
    if node.sources:
        lines.append(f"{indent}  (cite: {', '.join(node.sources)})")
    for child in node.children:
        lines.extend(_render_node(child, depth + 1))
    return lines


def render_outline_prompt(
    outline: Outline,
    assessment: FreedomAssessment,
    *,
    voice_block: str = "",
    mode_rules: str = "",
) -> str:
    """The user prompt sent to the writer role for an outline-guided run."""
    lines: list[str] = []

    lines.append("Write a complete piece from the author's outline below.")
    lines.append("")
    lines.append(AUTHORITY_INSTRUCTION)
    lines.append("")
    lines.append(NO_FABRICATION_INSTRUCTION)
    lines.append("")

    lines.append(f"GENERATION FREEDOM: {assessment.freedom.value}")
    lines.append(_FREEDOM_GUIDANCE[assessment.freedom])
    lines.append("")

    if outline.title:
        lines.append(f"TITLE: {outline.title}")
    if outline.topic:
        lines.append(f"TOPIC: {outline.topic}")
    if outline.mode:
        lines.append(f"MEDIUM: {outline.mode}")
    if outline.target_words:
        lines.append(f"TARGET LENGTH: about {outline.target_words} words")
    if outline.max_words:
        lines.append(f"HARD MAXIMUM: {outline.max_words} words. Never exceed this.")
    lines.append("")

    preserved = outline.preserved()
    if preserved:
        lines.append(
            "VERBATIM PASSAGES -- reproduce each of these EXACTLY as written, "
            "including punctuation and capitalisation. They are the author's "
            "own sentences. Do not improve, shorten, merge, or re-punctuate "
            "them. You may place them where they read best and write around "
            "them freely:"
        )
        for node in preserved:
            lines.append(f'  [{node.id}] "{node.text}"')
        lines.append("")

    lines.append("OUTLINE:")
    for node in outline.nodes:
        lines.extend(_render_node(node))
    lines.append("")

    if outline.enforce_order and len(outline.required_points()) > 1:
        lines.append(
            "ORDER IS FIXED. Present the required points in the order listed "
            "above. This ordering is the author's argument, not a formatting "
            "preference, and it is not available for stylistic variation."
        )
        lines.append("")

    seeds = outline.voice_seeds()
    if seeds:
        lines.append(
            "VOICE SEEDS -- sentences the author wrote for THIS piece. Match "
            "their register and cadence; they outrank the historical voice "
            "profile below. Do not quote or reuse them verbatim unless they "
            "are also listed as verbatim passages, and do not repeat their "
            "phrasing:"
        )
        for node in seeds:
            lines.append(f'  "{node.text}"')
        lines.append("")

    if outline.research:
        lines.append("RESEARCH REQUIRED before the related claims can be made:")
        for request in outline.research:
            marker = "required" if request.required else "optional"
            lines.append(f"  [{request.node_id}] ({marker}) {request.question}")
        lines.append("")

    notes = outline.nodes_of(NodeKind.STYLE_NOTE)
    if notes:
        lines.append("STYLE NOTES FROM THE AUTHOR (these outrank the voice profile):")
        for node in notes:
            lines.append(f"  - {node.text}")
        lines.append("")

    if mode_rules:
        lines.append(mode_rules)
        lines.append("")

    if voice_block:
        lines.append(
            "VOICE PROFILE -- how this author tends to write. It ranks BELOW "
            "everything above: it governs expression only and must never "
            "change a claim, an ordering, or a verbatim passage. Where the "
            "outline's own sentences suggest a different register than the "
            "profile, follow the outline."
        )
        lines.append(voice_block)
        lines.append("")

    lines.append(
        "OUTPUT FORMAT:\n"
        "Return a ```yaml code block containing:\n"
        "```yaml\n"
        "body_markdown: |\n"
        "  <the complete piece>\n"
        "added_claims:\n"
        "  - claim: \"<any factual assertion you added that the outline did not supply>\"\n"
        "    basis: \"<why you believe it, or 'general knowledge'>\"\n"
        "gaps:\n"
        "  - \"<any point that needed a personal detail the author did not supply>\"\n"
        "warnings: []\n"
        "```\n"
        "List every factual assertion you added under `added_claims`, including "
        "ones you consider obvious. An empty list means you added none, and it "
        "will be checked."
    )
    return "\n".join(lines)
