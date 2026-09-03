"""StructuralRealization: the soft structural shape derived for ONE piece.

This object represents the core architectural departure from the v1 voice system:
a corpus distribution is a pool of evidence to draw from, NOT an instruction to
every generated document.

Instead of telling every generation:
    "paragraph length: typically 22-115 words (mean ~80 words)"
which acts as an attractor pulling all outputs toward the center (e.g. 5 paragraphs
every time), the system derives ONE plausible structural realization from the
author's actual distribution.

Crucial design invariants:
1. SOFT GUIDANCE: Content requirements, outline requirements, and factual truth
   strictly outrank structural realization. If 6 paragraphs are required to satisfy
   an outline, 6 paragraphs are written.
2. COVARIANCE PRESERVATION: Realizations are anchored to real document behavior
   rather than independently synthesizing impossible extremes.
3. REPRODUCIBILITY: Realization derivation is fully deterministic given a seed or
   input hash.
4. PRIVACY: Holds only structural statistics and abstract labels; never holds raw
   prose, corpus filenames, or local paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from howlwriter.domain.serialization import DataClassSerializationMixin


@dataclass
class StructuralRealization(DataClassSerializationMixin):
    """The structural region and stylistic cadence selected for ONE piece."""

    # --- Origin and Provenance ---
    source_context: str = "global"
    selected_anchor_context: str = ""
    candidate_count: int = 0
    sample_count: int = 0
    selection_method: str = "EMPIRICAL_JOINT_ANCHOR_VECTOR"
    length_conditioning: str = ""
    format_conditioning: str = ""
    fallback_behavior: str = ""
    format_eligible_count: int = 0
    seed: int | None = None
    reproducible: bool = True
    model_generation_deterministic: bool = False

    # --- Length and Paragraph Architecture ---
    target_words: int | None = None
    paragraph_count_region: tuple[int, int] = (3, 5)
    paragraph_words_mean_target: float = 50.0
    paragraph_sentences_mean_target: float = 3.0
    single_sentence_paragraph_eligible: bool = False

    # --- Sentence Cadence ---
    sentence_length_mean_target: float = 18.0
    sentence_length_stdev_target: float = 6.0
    short_sentence_tendency: str = "moderate"   # minimal | moderate | prominent
    long_sentence_tendency: str = "moderate"    # minimal | moderate | prominent

    # --- Zero-Inflated Behavioral Selection ---
    first_person_eligible: bool = False
    first_person_target_rate: float | None = None
    parenthetical_eligible: bool = False
    parenthetical_target_count: int = 0
    sentence_initial_conjunction_eligible: bool = False
    question_eligible: bool = False
    fragment_eligible: bool = False
    transition_density_tendency: str = "minimal"  # minimal | light | moderate | signposted

    # --- Opening and Ending Moves ---
    opening_behavior: str = "direct_thesis"
    ending_behavior: str = "declarative_stop"
    reasoning_shape: str = ""

    # --- Authority and Escape Guardrails ---
    overrides: list[str] = field(default_factory=list)
    generation_freedom: str = ""
    guidance_level: str = "full"  # full | cadence_only | none
    escape_clause: str = (
        "Content requirements, outline points, and factual clarity strictly "
        "outrank this structural guidance. Do not force paragraph counts if "
        "the content or outline requires a different structure."
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuralRealization:
        rebuilt = super().from_dict(data)
        if isinstance(rebuilt.paragraph_count_region, list):
            rebuilt.paragraph_count_region = (
                int(rebuilt.paragraph_count_region[0]),
                int(rebuilt.paragraph_count_region[1]),
            )
        return rebuilt
