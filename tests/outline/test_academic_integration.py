"""An outline must constrain the academic pipeline, never route around it.

Everything that makes the academic path trustworthy -- source relevance and
sufficiency, evidence depth, identifier grounding, claim verification, APA
formatting, requirement classification, the soft target against the hard
ceiling, redundancy, consistency, quotation validation -- lives in that
pipeline. The risk a richer outline introduces is a second path that quietly
skips some of it, so these tests check that the outline arrives as an
assignment spec and that its own guarantees are added on top rather than
substituted in.
"""

from __future__ import annotations

from howlwriter.academic.outline_bridge import (
    claim_source_links,
    research_questions,
    spec_from_outline,
    unassigned_claims,
)
from howlwriter.academic.spec import AssignmentSpec, LengthConstraints
from howlwriter.domain.outline import load_outline

_ACADEMIC = {
    "schema": "outline/v1",
    "title": "Credential abuse and detection difficulty",
    "mode": "academic",
    "target_words": 1800,
    "max_words": 2000,
    "nodes": [
        {"kind": "heading", "text": "Introduction"},
        {
            "kind": "thesis",
            "id": "claim_1",
            "text": "Valid credentials complicate detection.",
            "sources": ["source_04"],
        },
        {"kind": "heading", "text": "Detection challenges"},
        {
            "kind": "claim",
            "id": "claim_2",
            "text": "Behavioural baselines degrade under legitimate variance.",
        },
        {"kind": "claim", "id": "claim_3", "text": "Alert fatigue compounds the problem."},
        {"kind": "preserve", "text": "Detection is not a solved problem."},
        {"kind": "style_note", "text": "APA 7 formatting throughout."},
    ],
    "research": [
        {
            "question": "Find evidence about detection difficulty with valid credentials.",
            "required": True,
            "supports_claims": ["claim_2"],
            "node_id": "research_1",
        }
    ],
}


def test_the_outline_becomes_an_assignment_spec():
    spec = spec_from_outline(load_outline(_ACADEMIC))

    assert isinstance(spec, AssignmentSpec)
    assert spec.title == "Credential abuse and detection difficulty"
    assert spec.target_words == 1800
    assert spec.length_constraints.max_words == 2000
    assert spec.outline == ["Introduction", "Detection challenges"]


def test_assignment_constraints_outrank_the_outline():
    """An assignment's own limits are higher in the authority order."""
    base = AssignmentSpec(
        title="Set by the assignment",
        target_words=1200,
        length_constraints=LengthConstraints(max_words=1500),
    )
    spec = spec_from_outline(load_outline(_ACADEMIC), base=base)

    assert spec.title == "Set by the assignment"
    assert spec.target_words == 1200
    # The outline may tighten a ceiling but never raise one the assignment set.
    assert spec.length_constraints.max_words == 1500


def test_an_outline_may_tighten_but_not_loosen_the_hard_ceiling():
    base = AssignmentSpec(length_constraints=LengthConstraints(max_words=5000))
    spec = spec_from_outline(load_outline(_ACADEMIC), base=base)
    assert spec.length_constraints.max_words == 2000


def test_required_points_and_style_notes_become_requirements():
    spec = spec_from_outline(load_outline(_ACADEMIC))
    assert any("APA 7" in r for r in spec.requirements)


def test_claims_are_traceable_to_their_sources_and_research():
    outline = load_outline(_ACADEMIC)
    links = {link.claim_id: link for link in claim_source_links(outline)}

    assert links["claim_1"].source_ids == ["source_04"]
    assert links["claim_2"].research_ids == ["research_1"]
    assert links["claim_2"].source_ids == []


def test_claims_pointing_at_nothing_are_reported_not_blocked():
    """The pipeline's own verification decides support; this only flags gaps."""
    unassigned = unassigned_claims(load_outline(_ACADEMIC))
    assert [n.id for n in unassigned] == ["claim_3"]


def test_research_requests_are_carried_through_in_a_recordable_shape():
    questions = research_questions(load_outline(_ACADEMIC))
    assert questions[0]["node_id"] == "research_1"
    assert questions[0]["required"] is True
    assert questions[0]["supports_claims"] == ["claim_2"]


def test_the_outline_travels_in_metadata_for_the_post_run_checks():
    spec = spec_from_outline(load_outline(_ACADEMIC))
    carried = spec.metadata["howlwriter_outline"]

    assert carried["schema"] == "outline/v1"
    assert carried["preserved_ids"]
    assert set(carried["claim_ids"]) == {"claim_1", "claim_2", "claim_3"}
    assert len(carried["claim_source_links"]) == 3


def test_the_bridge_never_relaxes_a_source_requirement():
    """Source sufficiency is the check most costly to weaken accidentally."""
    base = AssignmentSpec()
    base.source_requirements.minimum_sources = 6
    spec = spec_from_outline(load_outline(_ACADEMIC), base=base)
    assert spec.source_requirements.minimum_sources == 6


def test_the_bridge_writes_no_pipeline_stage_of_its_own():
    """Structural guarantee: translation only, no parallel pipeline."""
    import inspect

    from howlwriter.academic import outline_bridge

    source = inspect.getsource(outline_bridge)
    for forbidden in ("execute_writing_role", "run_academic_pipeline", "AcademicResearcher"):
        assert forbidden not in source


def test_preserved_passages_reach_the_academic_writer():
    """AssignmentSpec has no verbatim concept, so the bridge has to supply one.

    Without this the academic writer never learns a passage was marked
    preserve. Observed on a live run: a preserved sentence scored 0.14 overlap
    in the finished paper, so the guarantee that holds byte-for-byte in the
    general pipeline was silently absent from the academic one.
    """
    spec = spec_from_outline(load_outline(_ACADEMIC))
    verbatim = [r for r in spec.requirements if "EXACTLY" in r]

    assert len(verbatim) == 1
    assert "Detection is not a solved problem." in verbatim[0]
    # Stated first, ahead of style notes and topics, because it is the one
    # instruction whose failure is unrecoverable.
    assert spec.requirements[0] == verbatim[0]


def test_the_authors_claims_reach_the_academic_writer():
    spec = spec_from_outline(load_outline(_ACADEMIC))
    claims = [r for r in spec.requirements if r.startswith("Assert and support")]

    assert len(claims) == 3
    assert any("Valid credentials complicate detection" in c for c in claims)


def test_every_preserved_node_survives_translation():
    """One dropped preserve is one broken promise; count them."""
    outline = load_outline(_ACADEMIC)
    spec = spec_from_outline(outline)
    assert len([r for r in spec.requirements if "EXACTLY" in r]) == len(outline.preserved())
