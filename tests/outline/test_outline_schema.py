"""The outline format: what loads, what is rejected, and what each kind means.

The failures worth guarding here are the quiet ones. A misspelled node kind
that silently becomes a generic note, a preserved sentence duplicated so
retention cannot be verified, a research request pointing at a claim that does
not exist -- each produces a run that looks fine and delivers less than the
user asked for.
"""

from __future__ import annotations

import json

import pytest
import yaml

from howlwriter.domain.outline import (
    OUTLINE_SCHEMA_VERSION,
    AuthorityLayer,
    NodeKind,
    Outline,
    load_outline,
    validate_outline,
)

_MINIMAL = {
    "schema": OUTLINE_SCHEMA_VERSION,
    "topic": "AI moats",
    "nodes": [
        {"kind": "preserve", "text": "Using AI isn't really a moat."},
        {"kind": "claim", "text": "Implementation cost created friction."},
        {"kind": "required_point", "text": "proprietary data and distribution"},
    ],
}


def test_yaml_and_json_produce_the_same_outline(tmp_path):
    yaml_path = tmp_path / "o.yaml"
    json_path = tmp_path / "o.json"
    yaml_path.write_text(yaml.safe_dump(_MINIMAL), encoding="utf-8")
    json_path.write_text(json.dumps(_MINIMAL), encoding="utf-8")

    from_yaml = load_outline(yaml_path)
    from_json = load_outline(json_path)

    assert from_yaml.to_dict() == from_json.to_dict()


def test_every_node_gets_a_stable_id_without_the_user_writing_one():
    outline = load_outline(_MINIMAL)
    ids = [node.id for node in outline.all_nodes()]
    assert ids == ["preserve_1", "claim_1", "required_point_1"]
    assert len(set(ids)) == len(ids)


def test_explicit_ids_are_kept_and_not_renumbered_over():
    outline = load_outline(
        {
            "topic": "x",
            "nodes": [
                {"kind": "claim", "id": "moat_claim", "text": "one"},
                {"kind": "claim", "text": "two"},
            ],
        }
    )
    ids = [n.id for n in outline.all_nodes()]
    assert "moat_claim" in ids
    assert len(set(ids)) == 2


def test_nested_children_are_rebuilt_as_nodes_not_dicts():
    outline = load_outline(
        {
            "topic": "x",
            "nodes": [
                {
                    "kind": "heading",
                    "text": "Section",
                    "children": [{"kind": "claim", "text": "nested claim"}],
                }
            ],
        }
    )
    nodes = outline.all_nodes()
    assert len(nodes) == 2
    assert nodes[1].kind is NodeKind.CLAIM
    assert nodes[1].text == "nested claim"


def test_an_unknown_kind_is_rejected_rather_than_silently_generalised():
    with pytest.raises(ValueError, match="unknown outline node kind"):
        load_outline({"topic": "x", "nodes": [{"kind": "wishful", "text": "y"}]})


def test_duplicate_preserved_text_is_rejected():
    """Two identical verbatim passages make retention impossible to verify."""
    errors = validate_outline(
        Outline(
            nodes=[
                _node("preserve", "the same sentence", "a"),
                _node("preserve", "the same sentence", "b"),
            ]
        )
    )
    assert any("more than once" in e for e in errors)


def test_max_words_below_target_is_rejected():
    errors = validate_outline(Outline(topic="x", target_words=800, max_words=400))
    assert any("below target_words" in e for e in errors)


def test_research_pointing_at_an_unknown_claim_is_rejected():
    from howlwriter.domain.outline import ResearchRequest

    outline = Outline(
        topic="x",
        nodes=[_node("claim", "real claim", "claim_1")],
        research=[
            ResearchRequest(
                question="find evidence", supports_claims=["claim_9"], node_id="r1"
            )
        ],
    )
    errors = validate_outline(outline)
    assert any("unknown claim" in e for e in errors)


def test_an_unsupported_schema_version_is_reported():
    errors = validate_outline(Outline(schema="outline/v99", topic="x"))
    assert any("unsupported outline schema" in e for e in errors)


def test_validation_reports_every_problem_not_just_the_first():
    outline = Outline(
        schema="outline/v99",
        target_words=900,
        max_words=100,
        nodes=[_node("claim", "", "empty_claim")],
    )
    errors = validate_outline(outline)
    assert len(errors) >= 3


# --- authority ----------------------------------------------------------

def test_authority_ranks_user_verbatim_above_every_profile_layer():
    assert AuthorityLayer.USER_VERBATIM < AuthorityLayer.CONTEXTUAL_PROFILE
    assert AuthorityLayer.USER_VERBATIM < AuthorityLayer.GLOBAL_PROFILE
    assert AuthorityLayer.USER_CLAIM < AuthorityLayer.WRITING_MODE
    assert AuthorityLayer.EVIDENCE < AuthorityLayer.USER_CLAIM
    assert AuthorityLayer.MODEL_STYLE_PREFERENCE == max(AuthorityLayer)


def test_a_voice_seed_outranks_the_stored_profile_but_not_the_users_claims():
    assert AuthorityLayer.USER_CLAIM < AuthorityLayer.USER_VOICE_SEED
    assert AuthorityLayer.USER_VOICE_SEED < AuthorityLayer.CONTEXTUAL_PROFILE


def test_node_kinds_map_to_their_authority():
    outline = load_outline(_MINIMAL)
    by_id = {n.id: n for n in outline.all_nodes()}
    assert by_id["preserve_1"].authority is AuthorityLayer.USER_VERBATIM
    assert by_id["claim_1"].authority is AuthorityLayer.USER_CLAIM
    assert by_id["required_point_1"].authority is AuthorityLayer.USER_STRUCTURE


# --- what counts as required --------------------------------------------

def test_instructions_and_voice_seeds_are_not_required_points():
    """An instruction describes work; a voice seed is register evidence.

    Requiring either to appear in the output would turn it into a phrase to
    reproduce, which is the opposite of what both are for.
    """
    outline = load_outline(
        {
            "topic": "x",
            "nodes": [
                {"kind": "claim", "text": "a real claim"},
                {"kind": "expand", "text": "develop the previous point"},
                {"kind": "voice_seed", "text": "I keep seeing this framed badly."},
                {"kind": "optional_point", "text": "a nice-to-have"},
                {"kind": "source", "text": "S001"},
            ],
        }
    )
    required = {node.kind for node in outline.required_points()}
    assert required == {NodeKind.CLAIM}


def test_supplied_words_counts_user_prose_and_not_instructions():
    outline = load_outline(
        {
            "topic": "x",
            "nodes": [
                {"kind": "claim", "text": "one two three"},
                {"kind": "expand", "text": "an instruction that is much longer than the claim"},
            ],
        }
    )
    assert outline.supplied_words() == 3


def _node(kind: str, text: str, node_id: str):
    from howlwriter.domain.outline import OutlineNode

    return OutlineNode(kind=NodeKind(kind), text=text, id=node_id)
