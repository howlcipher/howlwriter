"""Constraint extraction from AssignmentSpec and HowlWriterConfig."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.serialization import DataClassSerializationMixin

DEFAULT_WORDS_PER_PAGE = 275


@dataclass
class ConstraintSet(DataClassSerializationMixin):
    """Explicit output constraints for a writing task.

    These are deliberately distinct from style preferences. When present,
    they outrank optional detail and elaboration.
    """

    target_words: int | None = None
    max_words: int | None = None
    target_pages: int | None = None
    max_pages: int | None = None
    required_sections: list[str] = field(default_factory=list)
    required_items: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    prohibited_content: list[str] = field(default_factory=list)
    source_fidelity: str = "grounded"  # grounded | strict | lenient
    output_only_requirements: list[str] = field(default_factory=list)
    compression_notes: str = ""

    def has_length_constraint(self) -> bool:
        return any(
            v is not None
            for v in (
                self.target_words,
                self.max_words,
                self.target_pages,
                self.max_pages,
            )
        )

    def has_rubric_constraint(self) -> bool:
        return any(
            [
                self.required_sections,
                self.required_items,
                self.required_evidence,
                self.prohibited_content,
                self.output_only_requirements,
                self.compression_notes,
            ]
        )

    def effective_max_words(self, words_per_page: int = DEFAULT_WORDS_PER_PAGE) -> int | None:
        limits: list[int] = []
        if self.max_words:
            limits.append(self.max_words)
        if self.max_pages:
            limits.append(self.max_pages * words_per_page)
        return min(limits) if limits else None

    def effective_target_words(
        self, words_per_page: int = DEFAULT_WORDS_PER_PAGE
    ) -> int | None:
        if self.target_words:
            return self.target_words
        if self.target_pages:
            return self.target_pages * words_per_page
        max_words = self.effective_max_words(words_per_page)
        if max_words:
            # Aim below the hard maximum; do not default to consuming it.
            return int(max_words * 0.75)
        return None

    def render_text(self) -> str:
        """Human-readable constraint summary for prompts."""
        lines: list[str] = []
        target = self.effective_target_words()
        hard = self.effective_max_words()
        if target is not None:
            lines.append(f"Target body words: ~{target}")
        if hard is not None:
            lines.append(f"Hard maximum body words: {hard}")
        if self.target_pages is not None:
            lines.append(f"Target pages: ~{self.target_pages}")
        if self.max_pages is not None:
            lines.append(f"Hard maximum pages: {self.max_pages}")
        if self.required_sections:
            lines.append("Required sections:")
            for s in self.required_sections:
                lines.append(f"  - {s}")
        if self.required_items:
            lines.append("Required rubric items (preserve at least one clear instance of each):")
            for item in self.required_items:
                lines.append(f"  - {item}")
        if self.required_evidence:
            lines.append("Required evidence:")
            for e in self.required_evidence:
                lines.append(f"  - {e}")
        if self.prohibited_content:
            lines.append("Prohibited content / unsupported identifiers:")
            for p in self.prohibited_content:
                lines.append(f"  - {p}")
        if self.output_only_requirements:
            lines.append("Output-only requirements:")
            for r in self.output_only_requirements:
                lines.append(f"  - {r}")
        if self.source_fidelity:
            lines.append(f"Source fidelity mode: {self.source_fidelity}")
        if self.compression_notes:
            lines.append(f"Compression guidance: {self.compression_notes}")
        return "\n".join(lines) if lines else "No explicit constraints supplied."


def extract_constraints_from_config(config: HowlWriterConfig) -> ConstraintSet:
    """Build a ConstraintSet from general HowlWriterConfig fields."""
    output_only: list[str] = []
    if config.compression_notes:
        output_only.append(config.compression_notes)
    return ConstraintSet(
        target_words=config.target_words,
        max_words=config.max_words,
        target_pages=config.target_pages,
        max_pages=config.max_pages,
        required_items=list(config.required_items),
        prohibited_content=list(config.prohibited_content),
        source_fidelity=config.source_fidelity or "grounded",
        output_only_requirements=output_only,
        compression_notes=config.compression_notes or "",
    )


def cast_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]
