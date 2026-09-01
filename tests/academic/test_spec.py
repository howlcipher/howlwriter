"""Tests for academic assignment specification parsing and validation."""

import pytest

from howlwriter.academic.spec import load_assignment_spec


def test_valid_assignment_spec_yaml():
    yaml_content = """
title: Zero Trust and Autonomous AI Agents
type: academic
topic: >
  Examine how autonomous AI agents complicate identity,
  authorization, and access control in enterprise environments.
target_words: 2000
word_tolerance_percent: 10
citation_style: apa7
source_requirements:
  minimum_sources: 6
  prefer_primary_sources: true
  scholarly_or_authoritative: true
requirements:
  - Support factual claims with citations
  - Do not fabricate sources
outline:
  - Introduction
  - Identity challenges
  - Conclusion
"""
    spec = load_assignment_spec(yaml_content)
    assert spec.title == "Zero Trust and Autonomous AI Agents"
    assert "autonomous AI agents" in spec.topic
    assert spec.target_words == 2000
    assert spec.word_tolerance_percent == 10.0
    assert spec.citation_style == "apa7"
    assert spec.source_requirements.minimum_sources == 6
    assert spec.source_requirements.prefer_primary_sources is True
    assert len(spec.requirements) == 2
    assert len(spec.outline) == 3


def test_spec_defaults_and_title_derivation():
    # Only topic provided: title derived automatically
    spec = load_assignment_spec({
        "topic": "Evaluating Post-Quantum Cryptography Migrations in Financial Core Banking Systems",
    })
    assert spec.title.startswith("Evaluating Post-Quantum Cryptography")
    assert spec.target_words == 2000
    assert spec.word_tolerance_percent == 10.0
    assert spec.citation_style == "apa7"
    assert spec.source_requirements.minimum_sources == 4


def test_invalid_assignment_specs_raise_clear_errors():
    # Empty title and topic
    with pytest.raises(ValueError, match="must include a title or topic"):
        load_assignment_spec({"type": "academic"})

    # Non-positive target words
    with pytest.raises(ValueError, match="target_words must be a positive integer"):
        load_assignment_spec({"title": "Test", "target_words": 0})

    with pytest.raises(ValueError, match="target_words must be a positive integer"):
        load_assignment_spec({"title": "Test", "target_words": -500})

    # Invalid tolerance percent
    with pytest.raises(ValueError, match="word_tolerance_percent must be between 0 and 100"):
        load_assignment_spec({"title": "Test", "word_tolerance_percent": 150})

    # Unsupported citation style
    with pytest.raises(ValueError, match="Unsupported citation_style"):
        load_assignment_spec({"title": "Test", "citation_style": "chicago"})

    # Invalid root type (e.g. YAML list instead of mapping)
    with pytest.raises(ValueError, match="must be a mapping/dict"):
        load_assignment_spec("- item 1\n- item 2")


def test_length_constraints_backward_compat_default():
    # A legacy spec with no length_constraints key must parse and validate
    # identically to today -- no hard ceiling, no page range.
    spec = load_assignment_spec({"title": "Test", "target_words": 1200})
    assert spec.length_constraints.max_words is None
    assert spec.length_constraints.max_pages is None
    assert spec.length_constraints.target_page_min is None
    assert spec.length_constraints.target_page_max is None
    assert spec.length_constraints.words_per_page == 275.0


def test_length_constraints_page_based_parses_from_dict():
    spec = load_assignment_spec({
        "title": "CYBR 601 Attack Chain Lab",
        "target_words": 2000,
        "length_constraints": {
            "max_pages": 10,
            "target_page_min": 6,
            "target_page_max": 9,
        },
    })
    assert spec.length_constraints.max_pages == 10
    assert spec.length_constraints.target_page_min == 6
    assert spec.length_constraints.target_page_max == 9
    assert spec.length_constraints.words_per_page == 275.0


def test_length_constraints_contradictory_range_raises():
    with pytest.raises(ValueError, match="contradictory range"):
        load_assignment_spec({
            "title": "Test",
            "length_constraints": {
                "target_page_min": 6,
                "target_page_max": 9,
                "max_words": 100,
            },
        })
