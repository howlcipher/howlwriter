"""Feeding an authorship outline into the academic pipeline without weakening it.

The temptation with a richer outline is to write a second pipeline for it. That
would be the wrong move: everything that makes the academic path trustworthy --
source relevance and sufficiency, evidence depth, identifier grounding, claim
verification, APA formatting, requirement classification, the soft target
against the hard ceiling, redundancy, consistency, quotation validation --
lives in the existing one, and a parallel path would have to re-earn all of it.

So the outline is translated into the `AssignmentSpec` the pipeline already
takes, and the pipeline runs unchanged. The outline's own guarantees -- verbatim
retention, ordering, claim-to-source assignment -- are added as checks AFTER it
returns, on the finished document, rather than as shortcuts through it.

The translation is deliberately lossy in one direction only. Everything the
spec understands is filled from the outline; everything the outline adds beyond
that is kept separately and checked separately. Nothing the spec would have
enforced is dropped along the way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from howlwriter.academic.spec import (
    AssignmentSpec,
    LengthConstraints,
    SourceRequirements,
)
from howlwriter.domain.outline import NodeKind, Outline, OutlineNode


@dataclass
class ClaimSourceLink:
    """One outline claim and the sources the author assigned to it.

    This is the thread the academic path needs end to end: outline claim ->
    research -> generated prose -> citation -> verification. Without it, a
    claim and the source meant to support it are two unrelated list entries.
    """

    claim_id: str
    claim_text: str
    source_ids: list[str] = field(default_factory=list)
    research_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "source_ids": list(self.source_ids),
            "research_ids": list(self.research_ids),
        }


def _outline_topics(outline: Outline) -> list[str]:
    """Section topics for the spec's flat outline list.

    Headings are the structure when the author gave any; otherwise required
    points stand in, so a paper written from claims alone still gets
    conformance checking rather than none.
    """
    headings = [n.text.strip() for n in outline.nodes_of(NodeKind.HEADING) if n.text.strip()]
    if headings:
        return headings
    return [
        n.text.strip()
        for n in outline.required_points()
        if n.text.strip() and n.kind is not NodeKind.PRESERVE
    ]


def _requirements(outline: Outline) -> list[str]:
    """Author instructions the pipeline's requirement classifier can act on."""
    requirements: list[str] = []
    for node in outline.nodes_of(NodeKind.STYLE_NOTE, NodeKind.ENDING):
        if node.text.strip():
            requirements.append(node.text.strip())
    for node in outline.nodes_of(NodeKind.REQUIRED_POINT):
        if node.text.strip():
            requirements.append(f"Address: {node.text.strip()}")
    for node in outline.nodes_of(NodeKind.EXAMPLE, NodeKind.EXPERIENCE):
        if node.text.strip():
            requirements.append(f"Include the author's example: {node.text.strip()}")
    return requirements


def spec_from_outline(
    outline: Outline,
    *,
    base: AssignmentSpec | None = None,
) -> AssignmentSpec:
    """Translate an outline into the spec the academic pipeline already takes.

    When a base spec is supplied its source and length requirements win, since
    those are assignment constraints and rank above the outline in the
    authority order.
    """
    spec = base or AssignmentSpec()

    spec.title = spec.title or outline.title or outline.topic
    spec.topic = spec.topic or outline.topic or outline.title
    spec.type = spec.type or "academic"

    if outline.target_words and (base is None or not base.target_words):
        spec.target_words = outline.target_words
    if outline.max_words:
        constraints = spec.length_constraints or LengthConstraints()
        # An outline may tighten a ceiling but never raise one the assignment set.
        existing = getattr(constraints, "max_words", None)
        if existing is None or outline.max_words < existing:
            constraints.max_words = outline.max_words
        spec.length_constraints = constraints
    if spec.source_requirements is None:
        spec.source_requirements = SourceRequirements()

    topics = _outline_topics(outline)
    if topics:
        spec.outline = list(dict.fromkeys(topics))

    requirements = _requirements(outline)
    if requirements:
        spec.requirements = list(spec.requirements) + [
            r for r in requirements if r not in spec.requirements
        ]

    if outline.voice_profile and not spec.voice_profile:
        spec.voice_profile = outline.voice_profile

    # The outline's own material has no home in the spec, so it travels in
    # metadata where the post-run checks can find it without the pipeline
    # having to know about it.
    spec.metadata = dict(spec.metadata or {})
    spec.metadata["howlwriter_outline"] = {
        "schema": outline.schema,
        "preserved_ids": [n.id for n in outline.preserved()],
        "claim_ids": [n.id for n in outline.claims()],
        "enforce_order": outline.enforce_order,
        "claim_source_links": [link.to_dict() for link in claim_source_links(outline)],
    }
    return spec


def claim_source_links(outline: Outline) -> list[ClaimSourceLink]:
    """Every claim with the sources and research the author tied to it."""
    research_by_claim: dict[str, list[str]] = {}
    for request in outline.research:
        for claim_id in request.supports_claims:
            research_by_claim.setdefault(claim_id, []).append(request.node_id)

    links: list[ClaimSourceLink] = []
    for node in outline.claims():
        links.append(
            ClaimSourceLink(
                claim_id=node.id,
                claim_text=node.text,
                source_ids=list(node.sources),
                research_ids=research_by_claim.get(node.id, []),
            )
        )
    return links


def unassigned_claims(outline: Outline) -> list[OutlineNode]:
    """Claims with neither a source nor a research request behind them.

    Reported rather than blocked. The pipeline's own claim verification decides
    whether a claim is supported by the evidence actually retrieved; this only
    points out the ones the author never pointed at anything.
    """
    return [
        node
        for node in outline.claims()
        if not node.sources
        and not any(node.id in r.supports_claims for r in outline.research)
    ]


def research_questions(outline: Outline) -> list[dict[str, Any]]:
    """Research requests in the shape the run record stores them."""
    return [
        {
            "node_id": request.node_id,
            "question": request.question,
            "required": request.required,
            "supports_claims": list(request.supports_claims),
        }
        for request in outline.research
    ]
