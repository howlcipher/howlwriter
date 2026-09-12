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

Status = Literal["READY", "NEEDS_REVIEW", "BLOCKED", "REJECTED"]
MeaningPreservationStatus = Literal["PASS", "FLAGGED", "NOT_EVALUATED"]


@dataclass
class ChangeRecord(DataClassSerializationMixin):
    description: str
    reason: str = ""


@dataclass
class WritingReport(DataClassSerializationMixin):
    status: Status = "NEEDS_REVIEW"
    run_id: str | None = None
    mode: str | None = None
    writer_provider: str | None = None
    researcher_provider: str | None = None
    humanizer_provider: str | None = None
    meaning_reviewer_provider: str | None = None
    reviewer_independence: str | None = None
    voice_match: float | None = None
    unsupported_claims: int | None = None
    contradicted_claims: int | None = None
    verified_claims: int | None = None
    supported_claims: int | None = None
    partially_supported_claims: int | None = None
    sources_used: int | None = None
    sources_retrieved: int | None = None
    sources_required: int | None = None
    citation_errors: int | None = None
    citation_warnings: int | None = None
    citation_style: str | None = None
    in_text_citations: int | None = None
    reference_entries: int | None = None
    target_words: int | None = None
    min_words: int | None = None
    max_words: int | None = None
    actual_body_words: int | None = None
    word_count_status: str | None = None
    required_outline_topics: int | None = None
    present_outline_topics: int | None = None
    outline_status: str | None = None
    banned_words: int | None = None
    ai_style_warnings: int | None = None
    lint_before_count: int | None = None
    lint_after_count: int | None = None
    meaning_preservation: MeaningPreservationStatus = "NOT_EVALUATED"
    semantic_meaning_status: str | None = None
    writer_duration_seconds: float | None = None
    researcher_duration_seconds: float | None = None
    humanizer_duration_seconds: float | None = None
    meaning_reviewer_duration_seconds: float | None = None
    total_duration_seconds: float | None = None
    changes: list[ChangeRecord] = field(default_factory=list)
    change_count: int | None = None
    sources: list[Source] = field(default_factory=list)
    # Constraint-aware pass observability
    constraint_summary: dict[str, Any] = field(default_factory=dict)

    def render_text(self) -> str:
        report_title = (
            "HOWLWRITER ACADEMIC REPORT"
            if self.mode == "academic" or self.target_words is not None
            else "HOWLWRITER REPORT"
        )
        lines = [report_title, ""]

        if self.run_id:
            lines.append(f"Run ID:                {self.run_id}")
        if self.mode:
            lines.append(f"Mode:                  {self.mode}")
        if self.writer_provider:
            lines.append(f"Writer:                {self.writer_provider}")
        if self.researcher_provider:
            lines.append(f"Researcher:            {self.researcher_provider}")
        if self.humanizer_provider:
            lines.append(f"Humanizer:             {self.humanizer_provider}")
        if self.meaning_reviewer_provider:
            lines.append(f"Meaning Reviewer:      {self.meaning_reviewer_provider}")
        if self.reviewer_independence:
            lines.append(f"Reviewer Independence: {self.reviewer_independence}")
        has_header_info = any([
            self.run_id,
            self.mode,
            self.writer_provider,
            self.researcher_provider,
            self.humanizer_provider,
            self.meaning_reviewer_provider,
            self.reviewer_independence,
        ])
        if has_header_info:
            lines.append("")

        if (
            self.writer_duration_seconds is not None
            or self.researcher_duration_seconds is not None
            or self.humanizer_duration_seconds is not None
            or self.meaning_reviewer_duration_seconds is not None
            or self.total_duration_seconds is not None
        ):
            lines.append("Latency:")
            if self.researcher_duration_seconds is not None:
                lines.append(
                    f"  Researcher:          {self.researcher_duration_seconds:.1f}s"
                )
            if self.writer_duration_seconds is not None:
                lines.append(
                    f"  Writer:              {self.writer_duration_seconds:.1f}s"
                )
            if self.humanizer_duration_seconds is not None:
                lines.append(
                    f"  Humanizer:           {self.humanizer_duration_seconds:.1f}s"
                )
            if self.meaning_reviewer_duration_seconds is not None:
                lines.append(
                    f"  Meaning Review:      {self.meaning_reviewer_duration_seconds:.1f}s"
                )
            if self.total_duration_seconds is not None:
                lines.append(
                    f"  Total:               {self.total_duration_seconds:.1f}s"
                )
            lines.append("")

        # Academic Word Count Section
        if self.target_words is not None:
            lines.append("Word Count:")
            lines.append(f"  Target Words:        {self.target_words}")
            if self.min_words is not None and self.max_words is not None:
                lines.append(f"  Allowed Range:       {self.min_words}–{self.max_words}")
            if self.actual_body_words is not None:
                lines.append(f"  Actual Body Words:   {self.actual_body_words}")
            if self.word_count_status is not None:
                lines.append(f"  Status:              {self.word_count_status}")
            lines.append("")

        # Academic Outline Section
        if self.required_outline_topics is not None:
            lines.append("Outline Conformance:")
            lines.append(f"  Required Topics:     {self.required_outline_topics}")
            if self.present_outline_topics is not None:
                lines.append(f"  Present Topics:      {self.present_outline_topics}")
            if self.outline_status is not None:
                lines.append(f"  Status:              {self.outline_status}")
            lines.append("")

        # Academic Sources Section
        if self.sources_retrieved is not None or self.sources_used is not None:
            lines.append("Sources:")
            if self.sources_retrieved is not None:
                lines.append(f"  Retrieved:           {self.sources_retrieved}")
            if self.sources_used is not None:
                lines.append(f"  Used In Paper:       {self.sources_used}")
            if self.sources_required is not None:
                lines.append(f"  Minimum Required:    {self.sources_required}")
            lines.append("")

        # Academic Claims Section
        if (
            self.supported_claims is not None
            or self.partially_supported_claims is not None
            or self.unsupported_claims is not None
            or self.contradicted_claims is not None
        ):
            lines.append("Claims Verification:")
            if self.supported_claims is not None:
                lines.append(f"  Supported:           {self.supported_claims}")
            if self.partially_supported_claims is not None:
                lines.append(f"  Partially Supported: {self.partially_supported_claims}")
            if self.unsupported_claims is not None:
                lines.append(f"  Unsupported:         {self.unsupported_claims}")
            if self.contradicted_claims is not None:
                lines.append(f"  Contradicted:        {self.contradicted_claims}")
            lines.append("")

        has_citation_section = (
            self.citation_style is not None
            or self.in_text_citations is not None
            or self.reference_entries is not None
        )
        if has_citation_section:
            lines.append("Citations & References:")
            if self.citation_style is not None:
                lines.append(f"  Style:               {self.citation_style.upper()}")
            if self.in_text_citations is not None:
                lines.append(f"  In-Text Citations:   {self.in_text_citations}")
            if self.reference_entries is not None:
                lines.append(f"  Reference Entries:   {self.reference_entries}")
            if self.citation_warnings is not None:
                lines.append(f"  Warnings:            {self.citation_warnings}")
            lines.append("")

        if self.lint_before_count is not None or self.lint_after_count is not None:
            lines.append("Deterministic Lint:")
            if self.lint_before_count is not None:
                lines.append(f"  Before:              {self.lint_before_count} findings")
            if self.lint_after_count is not None:
                lines.append(f"  After:               {self.lint_after_count} findings")
            lines.append("")

        metrics: list[tuple[str, int | float | None]] = [
            ("Voice match", self.voice_match),
            ("Banned words", self.banned_words),
            ("AI-style warnings", self.ai_style_warnings),
        ]
        has_metrics = any(v is not None for _, v in metrics)
        if has_metrics:
            for label, value in metrics:
                if value is None:
                    continue
                rendered = f"{value:.0%}" if label == "Voice match" else str(value)
                lines.append(f"{label:<28}{rendered}")

        if self.semantic_meaning_status is not None:
            lines.append("Meaning Preservation:")
            lines.append(f"  Deterministic:       {self.meaning_preservation}")
            lines.append(f"  Semantic Review:     {self.semantic_meaning_status}")
        elif self.meaning_preservation != "NOT_EVALUATED":
            lines.append(f"{'Meaning preservation':<28}{self.meaning_preservation}")

        if self.changes:
            lines.append("")
            lines.append("Changes:")
            for change in self.changes:
                if change.reason:
                    lines.append(f"- [{change.reason}] {change.description}")
                else:
                    lines.append(f"- {change.description}")

        if self.constraint_summary:
            lines.append("")
            lines.append("Constraint-Aware Pass:")
            for key, value in self.constraint_summary.items():
                lines.append(f"  {key}: {value}")

        if self.sources and self.sources_retrieved is None:
            lines.append("")
            lines.append("Sources:")
            for index, source in enumerate(self.sources, start=1):
                lines.append(f"[{index}] {source.title}")

        lines.append("")
        lines.append(f"STATUS: {self.status}")
        return "\n".join(lines)
