"""The end-of-run Writing Report.

Every metric field is Optional. render_text() omits a metric line entirely
when its value is None, rather than printing a fake 0 or N/A -- printing
"unsupported claims: 0" when fact-checking never ran would falsely claim
verification happened. This is the concrete mechanism behind the project's
"no fake precision" rule: a metric that cannot be honestly computed yet is
left out, not approximated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source

Status = Literal["READY", "NEEDS_REVIEW", "BLOCKED"]
MeaningPreservationStatus = Literal["PASS", "FLAGGED", "NOT_EVALUATED"]


@dataclass
class ChangeRecord(DataClassSerializationMixin):
    description: str


@dataclass
class WritingReport(DataClassSerializationMixin):
    status: Status = "NEEDS_REVIEW"
    voice_match: float | None = None
    unsupported_claims: int | None = None
    contradicted_claims: int | None = None
    verified_claims: int | None = None
    sources_used: int | None = None
    citation_errors: int | None = None
    banned_words: int | None = None
    ai_style_warnings: int | None = None
    meaning_preservation: MeaningPreservationStatus = "NOT_EVALUATED"
    changes: list[ChangeRecord] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    def render_text(self) -> str:
        lines = ["HOWLWRITER REPORT", ""]
        metrics: list[tuple[str, int | float | None]] = [
            ("Voice match", self.voice_match),
            ("Unsupported claims", self.unsupported_claims),
            ("Contradicted claims", self.contradicted_claims),
            ("Verified claims", self.verified_claims),
            ("Sources used", self.sources_used),
            ("Citation errors", self.citation_errors),
            ("Banned words", self.banned_words),
            ("AI-style warnings", self.ai_style_warnings),
        ]
        for label, value in metrics:
            if value is None:
                continue
            rendered = f"{value:.0%}" if label == "Voice match" else str(value)
            lines.append(f"{label:<28}{rendered}")
        if self.meaning_preservation != "NOT_EVALUATED":
            lines.append(f"{'Meaning preservation':<28}{self.meaning_preservation}")

        if self.changes:
            lines.append("")
            lines.append("Changes:")
            lines.extend(f"- {change.description}" for change in self.changes)

        if self.sources:
            lines.append("")
            lines.append("Sources:")
            for index, source in enumerate(self.sources, start=1):
                lines.append(f"[{index}] {source.title}")

        lines.append("")
        lines.append(f"STATUS: {self.status}")
        return "\n".join(lines)
