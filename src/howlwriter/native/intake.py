"""Build a Writer request straight from a HowlDream candidate export.

A Dream ``howl.candidate/v1`` handoff (from ``howldream export``) already
carries the idea's identity, objective, text, constraints and provenance.
This module maps it onto ``howlwriter.request/v1`` so no supervising agent
has to hand-write a Dream-to-Writer adapter. The copy slots to rewrite and
their canonical evidence come from the operator, because Dream does not
know the current copy of the target artifact.
"""

from __future__ import annotations

from typing import Any

from howlwriter.native.contracts import ContractError, WriterRequest

# Operations that credit Dream with authoring the idea. Anything else is a
# narrower role (it selected, clustered or reviewed text someone else wrote).
_ROLE_BY_TRANSFORMATION = (
    ("howldream_scoped_review", "REVIEWED"),
    ("idea_unit_selection", "SELECTED"),
)


def dream_role(candidate: dict[str, Any]) -> str:
    """The narrowest role Dream's own provenance supports for this candidate."""
    provenance = candidate.get("provenance") or {}
    participation = provenance.get("participation")
    if isinstance(participation, dict) and isinstance(participation.get("operation"), str):
        return participation["operation"]
    if isinstance(participation, list) and participation:
        last = participation[-1]
        if isinstance(last, dict) and isinstance(last.get("operation"), str):
            return last["operation"]
    transformations = provenance.get("transformations") or []
    for marker, role in _ROLE_BY_TRANSFORMATION:
        if marker in transformations:
            return role
    execution = provenance.get("execution") or {}
    if execution.get("inference_occurred") is True and not execution.get("mocked"):
        return "GENERATED"
    return "SELECTED"


def request_from_dream(
    candidate: dict[str, Any],
    spec: dict[str, Any],
) -> WriterRequest:
    """Map a Dream candidate plus an operator copy spec onto a Writer request.

    ``spec`` supplies ``items`` (the copy slots with current text and
    canonical evidence), ``audience`` and optionally ``tone``,
    ``length_constraints``, ``factual_constraints`` and ``title``.
    """
    if not isinstance(candidate, dict):
        raise ContractError("Dream candidate must be a JSON object")
    provenance = candidate.get("provenance") or {}
    if provenance.get("producer_component") != "howldream":
        raise ContractError("candidate provenance.producer_component must be howldream")
    if candidate.get("status") == "REJECTED":
        raise ContractError("Dream candidate is REJECTED and cannot be handed to Writer")
    authority = candidate.get("authority") or {"type": "ADVISORY", "executable": False}
    if authority.get("executable") is not False:
        raise ContractError("Dream candidate must be advisory and non-executable")
    if not isinstance(spec, dict):
        raise ContractError("copy spec must be a JSON object")

    hard_constraints = [c for c in provenance.get("hard_constraints") or [] if isinstance(c, str)]
    constraints = list(spec.get("factual_constraints") or []) + hard_constraints
    for contradiction in candidate.get("contradictions") or []:
        if isinstance(contradiction, str):
            constraints.append(f"Unresolved contradiction: {contradiction}")
    evidence_refs = list(candidate.get("evidence_refs") or [])
    for item in spec.get("items") or []:
        for evidence in (item or {}).get("evidence") or []:
            ref = (evidence or {}).get("ref")
            if isinstance(ref, str) and ref not in evidence_refs:
                evidence_refs.append(ref)

    return WriterRequest.from_dict({
        "source_idea_id": candidate.get("candidate_id"),
        "source_run_id": candidate.get("source_run_id"),
        "source_component": "howldream",
        "source_component_role": dream_role(candidate),
        "title": spec.get("title") or candidate.get("objective"),
        "problem": candidate.get("objective") or "",
        "proposal": candidate.get("text") or "",
        "audience": spec.get("audience"),
        "items": spec.get("items"),
        "canonical_evidence_refs": evidence_refs,
        "factual_constraints": constraints,
        "tone": spec.get("tone", "technical, direct, concise"),
        "length_constraints": spec.get("length_constraints", ""),
        "copy_implications": [
            a for a in candidate.get("assumptions") or [] if isinstance(a, str)
        ][:20],
    })


def request_from_operator(spec: dict[str, Any]) -> WriterRequest:
    """A request whose idea came from the operator rather than a component."""
    if not isinstance(spec, dict):
        raise ContractError("copy spec must be a JSON object")
    value = dict(spec)
    value.setdefault("source_component", "operator")
    value.setdefault("source_component_role", "OPERATOR_SUPPLIED")
    return WriterRequest.from_dict(value)
