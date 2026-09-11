"""Ablation configurations for isolating HowlWriter subsystem contributions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from howlwriter.domain.serialization import DataClassSerializationMixin


@dataclass
class AblationConfiguration(DataClassSerializationMixin):
    """Declarative feature-flag configuration to disable specific HowlWriter layers."""

    name: str
    description: str
    disable_source_verification: bool = False
    disable_source_authority: bool = False
    disable_voice: bool = False
    disable_independent_review: bool = False
    disable_red_pen: bool = False
    disable_meaning_preservation: bool = False
    disable_provenance_constraints: bool = False
    disable_humanizer: bool = False
    disable_outline_enforcement: bool = False

    def to_config_overrides(self) -> dict[str, Any]:
        """Returns dictionary of config overrides corresponding to this ablation."""
        overrides: dict[str, Any] = {}
        if self.disable_voice:
            overrides["voice_profile"] = None
        if self.disable_humanizer:
            overrides["humanization_strength"] = "none"
        if self.disable_red_pen:
            overrides["editing_strength"] = "none"
        return overrides


# Canonical predefined ablations
FULL_MINUS_SOURCE_VERIFICATION = AblationConfiguration(
    name="no_source_verification",
    description="Full HowlWriter pipeline with research source reachability and claim verification bypassed.",
    disable_source_verification=True,
)

FULL_MINUS_VOICE = AblationConfiguration(
    name="no_voice",
    description="Full HowlWriter pipeline with personal voice profile and structural realization disabled.",
    disable_voice=True,
)

FULL_MINUS_INDEPENDENT_REVIEW = AblationConfiguration(
    name="no_independent_review",
    description="Full HowlWriter pipeline running reviews without provider-independence constraints.",
    disable_independent_review=True,
)

FULL_MINUS_RED_PEN = AblationConfiguration(
    name="no_red_pen",
    description="Full HowlWriter pipeline with Red Pen adversarial critique disabled.",
    disable_red_pen=True,
)

FULL_MINUS_MEANING_PRESERVATION = AblationConfiguration(
    name="no_meaning_preservation",
    description="Full HowlWriter pipeline with semantic and heuristic meaning preservation review disabled.",
    disable_meaning_preservation=True,
)

FULL_MINUS_PROVENANCE = AblationConfiguration(
    name="no_provenance_constraints",
    description="Full HowlWriter pipeline with model-added claim provenance tracking disabled.",
    disable_provenance_constraints=True,
)

FULL_MINUS_HUMANIZER = AblationConfiguration(
    name="no_humanizer",
    description="Full HowlWriter pipeline skipping the humanizer and safe-rewriter stages.",
    disable_humanizer=True,
)

PREDEFINED_ABLATIONS: dict[str, AblationConfiguration] = {
    "no_source_verification": FULL_MINUS_SOURCE_VERIFICATION,
    "no_voice": FULL_MINUS_VOICE,
    "no_independent_review": FULL_MINUS_INDEPENDENT_REVIEW,
    "no_red_pen": FULL_MINUS_RED_PEN,
    "no_meaning_preservation": FULL_MINUS_MEANING_PRESERVATION,
    "no_provenance_constraints": FULL_MINUS_PROVENANCE,
    "no_humanizer": FULL_MINUS_HUMANIZER,
}


def get_ablation(name: str) -> AblationConfiguration | None:
    """Resolve an ablation by name (normalized)."""
    norm = name.strip().lower().replace("-", "_")
    return PREDEFINED_ABLATIONS.get(norm)
