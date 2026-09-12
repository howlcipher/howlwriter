"""Model-backed constraint enforcement pass.

The enforcer takes a draft plus an explicit ConstraintSet, runs lightweight
deterministic pre-checks, and asks the configured writer model to produce a
revised draft that satisfies the constraints without sacrificing required
rubric evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.constraints.specs import ConstraintSet
from howlwriter.constraints.validators import (
    HeadingConsistencyValidator,
    RedundancyDetector,
    SequenceValidator,
    UnsupportedSpecificityValidator,
    ValidationReport,
)
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.report import ChangeRecord
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole


@dataclass
class ConstraintEnforcementResult(DataClassSerializationMixin):
    document: Document
    changes: list[ChangeRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    target_words: int | None = None
    max_words: int | None = None
    actual_words: int | None = None
    rubric_items_detected: int = 0
    rubric_items_preserved: int = 0
    redundancy_removed: int = 0
    unsupported_specificity_generalized: int = 0
    sequence_repairs: int = 0
    heading_mismatches_flagged: int = 0
    rationale: str = ""
    provider: str = ""
    model: str | None = None
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ConstraintEnforcer:
    """Enforces explicit user constraints on a draft document."""

    role: WritingRole = WritingRole.WRITER

    def enforce(
        self,
        document: Document,
        constraints: ConstraintSet,
        sources: list[Source] | None = None,
        config: HowlWriterConfig | None = None,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        run_id: str | None = None,
    ) -> ConstraintEnforcementResult:
        """Run deterministic pre-checks and invoke the writer model to revise the draft."""
        bridge = get_howlplane_bridge()
        if not bridge.is_role_configured(self.role) and custom_backend is None:
            # No writer model available; skip enforcement rather than fail.
            return ConstraintEnforcementResult(
                document=document,
                rationale="Constraint enforcer skipped: no writer model configured.",
            )

        validation_report = self._build_validation_report(document)
        source_block = self._render_sources(sources)
        prompt = self._build_prompt(document, constraints, validation_report, source_block)

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            context={
                "title": document.title,
                "mode": document.mode,
                "task": "constraint_enforcement",
                "run_id": run_id,
            },
            timeout_seconds=600,
            cwd=cwd,
            custom_backend=custom_backend,
        )

        if not result.success:
            err = result.error_message or "Constraint enforcer failed"
            return ConstraintEnforcementResult(
                document=document,
                warnings=[f"Constraint enforcer provider '{result.provider}' failed: {err}"],
                provider=result.provider,
                model=result.model,
                duration_seconds=result.duration_seconds,
            )

        structured = result.structured_output or {}
        body = structured.get("body_markdown") or result.raw_output.strip()
        if not body or not isinstance(body, str) or not body.strip():
            return ConstraintEnforcementResult(
                document=document,
                warnings=["Constraint enforcer returned empty body. Original draft retained."],
                provider=result.provider,
                model=result.model,
                duration_seconds=result.duration_seconds,
            )

        new_doc = Document.parse(body, title=document.title, mode=document.mode)
        changes = self._parse_changes(structured.get("changes_made"))
        warnings = [str(w) for w in structured.get("warnings", []) if isinstance(w, str)]

        return ConstraintEnforcementResult(
            document=new_doc,
            changes=changes,
            warnings=warnings,
            target_words=constraints.effective_target_words(),
            max_words=constraints.effective_max_words(),
            actual_words=len(re.findall(r"\b[\w'-]+\b", body)),
            rubric_items_detected=len(constraints.required_items) + len(constraints.required_evidence),
            rubric_items_preserved=int(structured.get("rubric_items_preserved", 0)),
            redundancy_removed=int(structured.get("redundancy_removed", 0)),
            unsupported_specificity_generalized=int(
                structured.get("unsupported_specificity_generalized", 0)
            ),
            sequence_repairs=int(structured.get("sequence_repairs", 0)),
            heading_mismatches_flagged=len(validation_report.heading_mismatch),
            rationale=str(structured.get("rationale", "")),
            provider=result.provider,
            model=result.model,
            duration_seconds=result.duration_seconds,
            metadata=result.metadata,
        )

    def _build_validation_report(self, document: Document) -> ValidationReport:
        return ValidationReport(
            redundancy=RedundancyDetector().detect(document),
            sequence=SequenceValidator().validate(document),
            specificity=UnsupportedSpecificityValidator().validate(document),
            heading_mismatch=HeadingConsistencyValidator().validate(document),
        )

    @staticmethod
    def _render_sources(sources: list[Source] | None) -> str:
        if not sources:
            return "No retrieved sources supplied."
        lines = []
        for s in sources or []:
            lines.append(f"[{s.id}] {s.title}")
            if s.authors:
                lines.append(f"  Authors: {', '.join(s.authors)}")
            if s.doi:
                lines.append(f"  DOI: {s.doi}")
            if s.url:
                lines.append(f"  URL: {s.url}")
            if s.retrieved_text:
                snippet = s.retrieved_text.replace('\n', ' ')[:300]
                lines.append(f"  Evidence: {snippet}...")
        return "\n".join(lines)

    def _build_prompt(
        self,
        document: Document,
        constraints: ConstraintSet,
        report: ValidationReport,
        source_block: str,
    ) -> str:
        mode_label = (
            document.mode.value
            if isinstance(document.mode, WritingMode)
            else (str(document.mode) if document.mode else "standard")
        )
        max_words = constraints.effective_max_words()
        target_words = constraints.effective_target_words()

        length_line = ""
        if max_words is not None and target_words is not None:
            length_line = (
                f"Aim for approximately {target_words} body words. "
                f"Hard maximum: {max_words} body words. Do not casually consume the full maximum."
            )
        elif max_words is not None:
            length_line = (
                f"Hard maximum: {max_words} body words. "
                "Target well below this maximum unless explicitly instructed otherwise."
            )
        elif target_words is not None:
            length_line = f"Target approximately {target_words} body words."

        return "\n".join(
            [
                "You are executing the CONSTRAINT ENFORCER / EDITOR role for HowlWriter.",
                "Given a draft and explicit constraints, revise the draft to fully satisfy the",
                "constraints while preserving every unique rubric requirement.",
                "",
                "PRIORITY ORDER (highest first):",
                "1. Safety / factual integrity",
                "2. Explicit user constraints (length, scope, format, prohibited content)",
                "3. Rubric / task requirements",
                "4. Semantic and logical correctness",
                "5. Source preservation requirements",
                "6. Style preferences",
                "7. Optional elaboration",
                "",
                f"WRITING MODE: {mode_label}",
                "",
                "CONSTRAINTS:",
                constraints.render_text() or "None supplied.",
                "",
                "LENGTH GUIDANCE:",
                length_line or "No explicit length target supplied; preserve concision.",
                "",
                "REVISION RULES:",
                "- Explicit constraints outrank optional detail.",
                "- Satisfy each rubric criterion once. Do not repeatedly prove the same point.",
                "- If a required table/matrix already demonstrates tools, telemetry, or mappings,",
                "  do not restate that row verbatim in the following prose. Keep only unique analysis.",
                "- Compress repeated mechanics, rationale, tools, or detection material rather than deleting",
                "  the evidence entirely.",
                "- For sequential artifacts (attack chains, procedures, workflows, timelines):",
                "  ensure each stage follows from the previous state. A later stage must not grant access",
                "  that an earlier stage already assumed. Actors cannot use capabilities before acquiring them.",
                "- Generalize unsupported specificity. Do not invent exact MITRE IDs, CVEs, Windows Event IDs,",
                "  AWS/Azure/GCP finding names, command syntax, API names, publication dates, citations, URLs,",
                "  regulatory references, entropy thresholds, jitter percentages, or exact telemetry claims.",
                "  If a precise identifier is not in the supplied sources or verified knowledge,",
                "  replace it with a grounded general statement or remove it.",
                "- Preserve exact identifiers that ARE explicitly present in the supplied source material.",
                "- Ensure headings, scenario labels, and thesis claims accurately describe the content.",
                "  Relabel a misnamed scenario rather than leaving a mismatch.",
                "- Do not attach a citation to a conceptual claim merely because the source is topically related.",
                "  If compression disconnects a claim from reliable attribution, rewrite more generally",
                "  or remove the unsupported attribution.",
                "- When all required criteria are demonstrated and the artifact is at or near target length,",
                "  stop adding examples, defensive subsections, or implementation specifics.",
                "- A shorter artifact that fully satisfies the task is superior to a longer artifact that",
                "  displays redundant expertise.",
                "",
                "SOURCE MATERIAL (only use these; do not invent sources):",
                source_block,
                "",
                "DETERMINISTIC PRE-CHECK FINDINGS (review; do not blindly obey):",
                report.render_text(),
                "",
                "ORIGINAL DRAFT:",
                "```markdown",
                document.text,
                "```",
                "",
                "OUTPUT FORMAT:",
                "Return a ```yaml code block containing:",
                "```yaml",
                "body_markdown: |",
                "  <complete revised markdown body>",
                "changes_made:",
                '  - description: "<brief description>"',
                '    reason: "<constraint priority>"',
                "warnings: []",
                "rubric_items_preserved: <integer>",
                "redundancy_removed: <integer>",
                "unsupported_specificity_generalized: <integer>",
                "sequence_repairs: <integer>",
                "rationale: \"<brief explanation>\"",
                "```",
            ]
        )

    @staticmethod
    def _parse_changes(raw: Any) -> list[ChangeRecord]:
        changes: list[ChangeRecord] = []
        if not isinstance(raw, list):
            return changes
        for item in raw:
            if isinstance(item, dict):
                desc = str(item.get("description") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if desc:
                    changes.append(ChangeRecord(description=desc, reason=reason or "CONSTRAINT_ENFORCEMENT"))
            elif isinstance(item, str) and item.strip():
                changes.append(ChangeRecord(description=item.strip(), reason="CONSTRAINT_ENFORCEMENT"))
        return changes
