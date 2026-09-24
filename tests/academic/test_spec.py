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


def test_formatting_block_round_trips_and_validates():
    from howlwriter.academic.spec import FormattingSpec, load_assignment_spec, validate_assignment_spec

    spec = load_assignment_spec(
        {
            "title": "Paper",
            "topic": "Topic",
            "formatting": {
                "line_spacing": 1.5,
                "page_numbers": True,
                "title_page": {"author": "Jane Student", "date": "2026-09-12"},
            },
        }
    )
    assert isinstance(spec.formatting, FormattingSpec)
    assert spec.formatting.line_spacing == 1.5
    assert spec.formatting.page_numbers is True
    assert spec.formatting.title_page == {"author": "Jane Student", "date": "2026-09-12"}
    assert validate_assignment_spec(spec) == []

    # Absent block uses the default academic profile.
    plain = load_assignment_spec({"title": "Paper", "topic": "Topic"})
    assert plain.formatting == FormattingSpec()
    assert plain.formatting.font_family == "Times New Roman"
    assert plain.formatting.font_size_pt == 12.0
    assert plain.formatting.line_spacing == 1.0
    assert plain.formatting.margin_top_in == 1.0


def test_maximum_sources_parses_and_validates():
    from howlwriter.academic.spec import validate_assignment_spec
    spec = load_assignment_spec({
        "title": "Discussion Post",
        "topic": "IoT Security",
        "source_requirements": {
            "minimum_sources": 3,
            "maximum_sources": 5,
        },
    })
    assert spec.source_requirements.minimum_sources == 3
    assert spec.source_requirements.maximum_sources == 5
    assert validate_assignment_spec(spec) == []


def test_source_requirements_defaults_have_no_maximum():
    spec = load_assignment_spec({"title": "Paper", "topic": "Topic"})
    assert spec.source_requirements.minimum_sources == 4
    assert spec.source_requirements.maximum_sources is None


def test_maximum_sources_validation_rejects_bad_values():
    from howlwriter.academic.spec import AssignmentSpec, SourceRequirements, validate_assignment_spec

    base = AssignmentSpec(title="Paper", topic="Topic")

    negative = base
    negative.source_requirements = SourceRequirements(minimum_sources=2, maximum_sources=-1)
    assert any("maximum_sources" in e for e in validate_assignment_spec(negative))

    contradictory = base
    contradictory.source_requirements = SourceRequirements(minimum_sources=6, maximum_sources=4)
    assert any("minimum_sources" in e and "maximum_sources" in e for e in validate_assignment_spec(contradictory))


def test_formatting_validation_rejects_unreasonable_values():
    from howlwriter.academic.spec import FormattingSpec, validate_assignment_spec
    from howlwriter.academic.spec import AssignmentSpec

    base = AssignmentSpec(title="Paper", topic="Topic")

    bad_font = base
    bad_font.formatting = FormattingSpec(font_family="")
    assert any("font_family" in e for e in validate_assignment_spec(bad_font))

    bad_size = base
    bad_size.formatting = FormattingSpec(font_size_pt=0)
    assert any("font_size_pt" in e for e in validate_assignment_spec(bad_size))

    bad_spacing = base
    bad_spacing.formatting = FormattingSpec(line_spacing=-1)
    assert any("line_spacing" in e for e in validate_assignment_spec(bad_spacing))

    bad_margin = base
    bad_margin.formatting = FormattingSpec(margin_left_in=-0.5)
    assert any("margin_left_in" in e for e in validate_assignment_spec(bad_margin))
