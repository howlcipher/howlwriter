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

    verif_overrides = FULL_MINUS_SOURCE_VERIFICATION.to_config_overrides()
    assert verif_overrides["fact_checking_strength"] == "none"


def test_ablation_to_execution_manifest():
    manifest = FULL_MINUS_SOURCE_VERIFICATION.to_execution_manifest()
    assert "source_integrity" in manifest.bypassed_stages
    assert manifest.source_integrity is False
    assert manifest.writer is True

    flags = FULL_MINUS_SOURCE_VERIFICATION.to_pipeline_flags()
    assert flags["source_verification"] is False
    assert flags["voice"] is True


def test_baseline_runner_ablation_manifest_and_timings():
    from howlwriter.evaluation.baselines import BaselineRunner
    from howlwriter.evaluation.models import BenchmarkCase

    case = BenchmarkCase(
        id="test_abl_case",
        task="Write an analysis of zero trust architectures.",
        requirements={"required_sections": ["Overview", "Architecture"], "citations": "required"},
        source_corpus=[{"title": "Zero Trust Standard", "url": "https://example.org", "doi": "10.1000/182"}],
    )
    runner = BaselineRunner()

    # Full run
    full_output = runner.run_howlwriter_full(case)
    assert full_output.execution_manifest is not None
    assert len(full_output.execution_manifest.bypassed_stages) == 0
    assert full_output.stage_timings["verification"] > 0 or full_output.stage_timings["draft"] > 0

    # Ablation run: no source verification
    abl_output = runner.run_howlwriter_full(case, ablation=FULL_MINUS_SOURCE_VERIFICATION)
    assert abl_output.execution_manifest is not None
    assert "source_integrity" in abl_output.execution_manifest.bypassed_stages
    assert abl_output.stage_timings.get("verification", 0.0) == 0.0

