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
from typing import Any, Literal

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source

# Keeps a pathological run from burying the rest of the report.
_MAX_RENDERED_WARNINGS = 10

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
    citation_warning_messages: list[str] = field(default_factory=list)
    unmatched_in_text_citations: list[str] = field(default_factory=list)
    citation_style: str | None = None
    in_text_citations: int | None = None
    reference_entries: int | None = None
    target_words: int | None = None
    min_words: int | None = None
    max_words: int | None = None
    hard_max_words: int | None = None
    target_pages_min: float | None = None
    target_pages_max: float | None = None
    max_pages: float | None = None
    actual_body_words: int | None = None
    word_count_status: str | None = None
    required_outline_topics: int | None = None
    present_outline_topics: int | None = None
    outline_status: str | None = None
    required_criteria_count: int | None = None
    present_criteria_count: int | None = None
    requirements_coverage_status: str | None = None
    prohibition_requirements_count: int | None = None
    prohibition_requirements_passed: int | None = None
    other_prohibition_requirements_count: int | None = None
    length_requirement_items_count: int | None = None
    length_requirement_items_passed: int | None = None
    style_requirements_count: int | None = None
    style_requirements_passed: int | None = None
    banned_words: int | None = None
    ai_style_warnings: int | None = None
    quotation_warnings: int | None = None
    identifier_warnings: int | None = None
    freshness_warnings: int | None = None
    freshness_findings: list[Any] = field(default_factory=list)
    redundancy_findings_count: int | None = None
    lint_before_count: int | None = None
    lint_after_count: int | None = None
    meaning_preservation: MeaningPreservationStatus = "NOT_EVALUATED"
    semantic_meaning_status: str | None = None
    consistency_review_status: str | None = None
    consistency_findings_count: int | None = None
    writer_duration_seconds: float | None = None
    researcher_duration_seconds: float | None = None
    humanizer_duration_seconds: float | None = None
    meaning_reviewer_duration_seconds: float | None = None
    total_duration_seconds: float | None = None
    changes: list[ChangeRecord] = field(default_factory=list)
    change_count: int | None = None
    sources: list[Source] = field(default_factory=list)

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
            if self.target_pages_min is not None and self.target_pages_max is not None:
                lines.append(
                    f"  Target Pages:        {self.target_pages_min:g}–{self.target_pages_max:g}"
                )
            if self.max_pages is not None:
                lines.append(f"  Maximum Pages:       {self.max_pages:g}")
            lines.append(f"  Target Words:        {self.target_words}")
            if self.min_words is not None and self.max_words is not None:
                lines.append(f"  Allowed Range:       {self.min_words}–{self.max_words}")
            if self.hard_max_words is not None:
                lines.append(f"  Hard Maximum Words:  {self.hard_max_words}")
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

        # Requirements Coverage Section -- required_criteria_count/
        # present_criteria_count/requirements_coverage_status reflect ONLY
        # positive-content requirements (see academic/requirements.py);
        # prohibition/length/style requirements are scored by their own
        # dedicated validators and reported in the lines below instead of
        # being folded into this same word-overlap coverage fraction.
        if (
            self.required_criteria_count is not None
            or self.prohibition_requirements_count is not None
            or self.other_prohibition_requirements_count is not None
            or self.length_requirement_items_count is not None
            or self.style_requirements_count is not None
        ):
            lines.append("Requirements Coverage:")
            if self.required_criteria_count is not None:
                lines.append(f"  Required Criteria:   {self.required_criteria_count}")
                if self.present_criteria_count is not None:
                    lines.append(
                        f"  Coverage:            {self.present_criteria_count}/{self.required_criteria_count}"
                    )
                if self.requirements_coverage_status is not None:
                    lines.append(f"  Status:              {self.requirements_coverage_status}")
            if self.prohibition_requirements_count is not None:
                lines.append(
                    f"  Prohibitions:        {self.prohibition_requirements_passed}/"
                    f"{self.prohibition_requirements_count} passed"
                )
            if self.other_prohibition_requirements_count is not None:
                lines.append(
                    f"  Other Prohibitions:  {self.other_prohibition_requirements_count} "
                    "not automatically validated"
                )
            if self.length_requirement_items_count is not None:
                lines.append(
                    f"  Length Requirements: {self.length_requirement_items_passed}/"
                    f"{self.length_requirement_items_count} passed"
                )
            if self.style_requirements_count is not None:
                lines.append(
                    f"  Style Requirements:  {self.style_requirements_passed}/"
                    f"{self.style_requirements_count} passed"
                )
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
            or self.quotation_warnings is not None
            or self.identifier_warnings is not None
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
            if self.quotation_warnings is not None:
                lines.append(f"  Quotation Warnings:  {self.quotation_warnings}")
            if self.identifier_warnings is not None:
                lines.append(f"  Identifier Warnings: {self.identifier_warnings}")
            if self.freshness_warnings is not None:
                lines.append(f"  Freshness Warnings:  {self.freshness_warnings}")
            lines.append("")

        if self.freshness_findings:
            lines.append("Source Freshness Warnings:")
            for f in self.freshness_findings:
                if isinstance(f, dict):
                    src = f.get("source_title") or f.get("source_id", "Unknown Source")
                    status = f.get("freshness_status", "UNKNOWN")
                    sup = f.get("superseded_by")
                    claim_text = f.get("claim_text")
                    action = f.get("action")
                else:
                    src = getattr(f, "source_title", None) or getattr(f, "source_id", "Unknown Source")
                    status = getattr(f, "freshness_status", "UNKNOWN")
                    if hasattr(status, "value"):
                        status = status.value
                    sup = getattr(f, "superseded_by", None)
                    claim_text = getattr(f, "claim_text", "")
                    action = getattr(f, "action", "")

                lines.append(f"  Source:        {src}")
                lines.append(f"  Status:        {status}")
                if sup:
                    lines.append(f"  Superseded by: {sup}")
                if claim_text:
                    lines.append(f'  Claim:         "{claim_text}"')
                if action:
                    lines.append(f"  Action:        {action}")
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
            if self.unmatched_in_text_citations:
                lines.append(
                    f"  Unresolved Citations: {len(self.unmatched_in_text_citations)}"
                )
            # A count alone leaves the writer with no way to act on a failed
            # citation check, so the messages themselves are listed here.
            for message in self.citation_warning_messages[:_MAX_RENDERED_WARNINGS]:
                lines.append(f"    - {message}")
            remaining = len(self.citation_warning_messages) - _MAX_RENDERED_WARNINGS
            if remaining > 0:
                lines.append(f"    ... {remaining} more")
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
            ("Redundancy findings", self.redundancy_findings_count),
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

        if self.consistency_review_status is not None:
            lines.append("")
            lines.append("Consistency Review:")
            lines.append(f"  Verdict:             {self.consistency_review_status}")
            if self.consistency_findings_count is not None:
                lines.append(f"  Findings:            {self.consistency_findings_count}")

        if self.changes:
            lines.append("")
            lines.append("Changes:")
            for change in self.changes:
                if change.reason:
                    lines.append(f"- [{change.reason}] {change.description}")
                else:
                    lines.append(f"- {change.description}")

        if self.sources and self.sources_retrieved is None:
            lines.append("")
            lines.append("Sources:")
            for index, source in enumerate(self.sources, start=1):
                lines.append(f"[{index}] {source.title}")

        lines.append("")
        lines.append(f"STATUS: {self.status}")
        return "\n".join(lines)
