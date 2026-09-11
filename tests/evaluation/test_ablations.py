"""Unit tests for ablation definitions and configuration."""

from __future__ import annotations

from howlwriter.evaluation.ablation import (
    FULL_MINUS_HUMANIZER,
    FULL_MINUS_INDEPENDENT_REVIEW,
    FULL_MINUS_RED_PEN,
    FULL_MINUS_SOURCE_VERIFICATION,
    FULL_MINUS_VOICE,
    get_ablation,
)


def test_predefined_ablations():
    assert FULL_MINUS_SOURCE_VERIFICATION.disable_source_verification is True
    assert FULL_MINUS_VOICE.disable_voice is True
    assert FULL_MINUS_INDEPENDENT_REVIEW.disable_independent_review is True
    assert FULL_MINUS_RED_PEN.disable_red_pen is True
    assert FULL_MINUS_HUMANIZER.disable_humanizer is True


def test_get_ablation_normalization():
    assert get_ablation("no-source-verification") == FULL_MINUS_SOURCE_VERIFICATION
    assert get_ablation("NO_VOICE") == FULL_MINUS_VOICE
    assert get_ablation("no-red-pen") == FULL_MINUS_RED_PEN
    assert get_ablation("unknown-layer") is None


def test_ablation_config_overrides():
    overrides = FULL_MINUS_VOICE.to_config_overrides()
    assert overrides["voice_profile"] is None

    humanizer_overrides = FULL_MINUS_HUMANIZER.to_config_overrides()
    assert humanizer_overrides["humanization_strength"] == "none"
