"""Real model-backed Academic Writer executing WritingRole.WRITER via HowlPlane."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from howlwriter.academic.length import count_body_words, resolve_length_bounds
from howlwriter.academic.prompts import ACADEMIC_PRIORITY_ORDERING_GUIDANCE
from howlwriter.academic.redundancy import RedundancyResult
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.citations.apa7 import APA7Formatter
from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole


def _aim_words(min_words: int, target_words: int) -> int:
    """The word count the WRITER should aim for: near the lower-middle of the
    allowed range, never the maximum -- see Goal H, "stop elaborating"."""
    return min_words + round((target_words - min_words) / 2)


def _format_outline(outline: list[str]) -> str:
    if outline:
        return "\n".join(f"- {topic}" for topic in outline)
    return "- Comprehensive analysis"


def _format_requirements(requirements: list[str]) -> str:
    if requirements:
        return "\n".join(f"- {r}" for r in requirements)
    return "- Follow academic conventions"


@dataclass
class WriterDraftResult(DataClassSerializationMixin):
    document: Document
    raw_output: str = ""
    claims_stated: list[dict[str, Any]] = field(default_factory=list)
    word_count: int = 0
    provider: str = ""
    model: str | None = None
    duration_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelAcademicWriter:
    """Wired executor for WritingRole.WRITER via HowlPlane."""

    role: WritingRole = WritingRole.WRITER

    def draft_paper(
        self,
        spec: AssignmentSpec,
        sources: list[Source],
        config: HowlWriterConfig | None = None,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        run_id: str | None = None,
        realization: Any | None = None,
    ) -> WriterDraftResult:
        """Invokes the WRITER role to draft an academic paper strictly grounded in retrieved sources."""
        bridge = get_howlplane_bridge()
        formatter = APA7Formatter()

        bounds = resolve_length_bounds(spec)
        min_words, max_words = bounds.min_words, bounds.max_words
        aim_words = _aim_words(min_words, bounds.target_words)

        # Build formatted source list with exact APA in-text citation keys
        source_context_lines: list[str] = []
        for s in sources:
            parenthetical = formatter.in_text_parenthetical(s).text
            narrative = formatter.narrative(s).text
            authors_str = ", ".join(s.authors) if s.authors else "No listed author"
            year_str = str(s.publication_date.year) if s.publication_date else "n.d."

            source_context_lines.append(
                f"[{s.id}] Title: {s.title}\n"
                f"  Authors: {authors_str} | Year: {year_str}\n"
                f"  In-Text Citation Format: {parenthetical} OR narrative {narrative}\n"
                f"  Evidence / Summary:\n  {s.retrieved_text or 'No summary text.'}\n"
            )

        sources_block = "\n".join(source_context_lines) if source_context_lines else "No sources available."

        outline_str = _format_outline(spec.outline)
        reqs_str = _format_requirements(spec.requirements)

        realization_block = ""
        if realization is not None:
            from howlwriter.voice.realization import render_structural_realization_prompt

            realization_lines = render_structural_realization_prompt(realization)
            realization_block = (
                "\n"
                + "\n".join(realization_lines)
                + "\n(Note: Academic integrity rules, outline requirements, and retrieved "
                "source evidence strictly outrank voice realization.)\n"
            )

        prompt = f"""You are executing the WRITER role under the HowlWriter academic contract.
Your mission is to draft a rigorous, high-quality academic research paper on the specified topic,
strictly structured according to the required outline and strictly grounded in the retrieved sources.

{ACADEMIC_PRIORITY_ORDERING_GUIDANCE}
{realization_block}
ASSIGNMENT TITLE: {spec.title}
TOPIC: {spec.topic}
TARGET WORD COUNT (BODY): aim for approximately {aim_words} words
  (Allowed range: {min_words} to {max_words} words)
CITATION STYLE: APA 7

REQUIRED OUTLINE:
{outline_str}

EXPLICIT ASSIGNMENT REQUIREMENTS:
{reqs_str}

RETRIEVED SOURCE EVIDENCE (ONLY USE THESE SOURCES):
{sources_block}

CRITICAL ACADEMIC WRITING RULES:
1. Ground all factual assertions in the retrieved sources above.
2. Insert APA 7 in-text citations using the exact author/year format provided for each source
   (e.g. (Smith, 2024) or Smith (2024)).
3. DO NOT invent external sources, authors, or DOIs not provided in the source evidence list.
4. DO NOT invent or fabricate statistics, dates, or study findings. This also applies to precise
   technical identifiers and figures (e.g. exact CVE/ATT&CK IDs, event IDs, cloud finding names,
   exact percentages, entropy, or timing values): only state one if it appears in the source
   evidence above; otherwise generalize (e.g. "GuardDuty may flag anomalous credential use"
   rather than inventing a specific finding name).
5. When a precise technical identifier or figure described in rule 4 DOES appear verbatim in the
   retrieved source evidence above and is relevant to the point being made, prefer reusing it
   exactly as given rather than generalizing it away -- grounded precision is preferred over
   unnecessary vagueness. Only generalize when no such grounded value exists.
6. If evidence is insufficient for a claim, qualify the statement (e.g. "Research suggests...") or omit it.
7. Address every section in the required outline. Use clear markdown headings for major outline sections.
8. Aim for approximately {aim_words} words -- near the lower-middle of the allowed range, not the
   maximum. Stop once the outline and explicit requirements are fully addressed with sufficient
   (not exhaustive) support; do not pad, restate, or add tangential elaboration to approach the
   maximum. A shorter paper that fully satisfies the outline and requirements is strongly
   preferred over a longer one that restates points already made.
9. Only attach a citation to a claim when that specific source actually establishes or supports
   that specific claim. Never attach a citation merely because the source is topically adjacent
   to the paragraph's subject.
10. For any staged, sequential, or procedural content (e.g. attack chains, workflows, timelines),
    ensure each stage only uses capabilities or access the actor has already acquired by that
    point -- do not have a later stage retroactively justify an earlier one.
11. DO NOT include a "# References" section at the end (the HowlWriter engine generates and attaches it).

OUTPUT FORMAT:
Return a ```yaml code block containing:
```yaml
body_markdown: |
  # {spec.title}

  <complete academic paper markdown body with headings and APA in-text citations>
claims_made:
  - claim: "<factual statement made>"
    source_id: "<e.g. S001>"
    evidence_snippet: "<relevant excerpt from source>"
word_count_estimate: <integer>
warnings: []
```"""

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            system_instruction=ACADEMIC_PRIORITY_ORDERING_GUIDANCE,
            context={
                "topic": spec.topic,
                "title": spec.title,
                "target_words": spec.target_words,
                "mode": WritingMode.ACADEMIC.value,
                "run_id": run_id,
            },
            timeout_seconds=600,
            cwd=cwd,
            custom_backend=custom_backend,
        )

        if not result.success:
            err = result.error_message or "Writer execution failed"
            raise RuntimeError(f"Writer provider '{result.provider}' failed: {err}")

        structured = result.structured_output or {}
        body = structured.get("body_markdown")
        if not body or not isinstance(body, str) or not body.strip():
            body = result.raw_output.strip()

        if not body or not body.strip():
            raise RuntimeError(
                f"Writer provider '{result.provider}' returned empty response."
            )

        claims_made = (
            structured.get("claims_made")
            if isinstance(structured.get("claims_made"), list)
            else (
                structured.get("added_claims")
                if isinstance(structured.get("added_claims"), list)
                else []
            )
        )
        warnings = [
            str(w) for w in structured.get("warnings", []) if isinstance(w, str)
        ]

        doc = Document.parse(body, title=spec.title, mode=WritingMode.ACADEMIC)
        words = count_body_words(body)

        return WriterDraftResult(
            document=doc,
            raw_output=result.raw_output,
            claims_stated=claims_made,
            word_count=words,
            provider=result.provider,
            model=result.model,
            duration_seconds=result.duration_seconds,
            warnings=warnings,
            metadata=result.metadata,
        )

    def correct_length(
        self,
        draft_doc: Document,
        spec: AssignmentSpec,
        sources: list[Source],
        direction: str,  # "EXPAND" | "TIGHTEN"
        current_words: int,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        run_id: str | None = None,
        redundancy_hint: RedundancyResult | None = None,
    ) -> WriterDraftResult:
        """Performs a bounded corrective pass to bring paper body within target word count."""
        bridge = get_howlplane_bridge()
        bounds = resolve_length_bounds(spec)
        min_words, max_words = bounds.min_words, bounds.max_words
        aim_words = _aim_words(min_words, bounds.target_words)
        outline_str = _format_outline(spec.outline)
        reqs_str = _format_requirements(spec.requirements)

        if direction == "EXPAND":
            instruction = (
                f"The draft is currently {current_words} words, which is below the target range "
                f"({min_words}–{max_words} words; target: {bounds.target_words}).\n"
                f"Confirm the outline sections and explicit requirements below are addressed with "
                f"sufficient depth before adding material; prioritize expanding only genuinely "
                f"thin/underdeveloped sections relative to this list using the EXISTING retrieved "
                f"sources and evidence. DO NOT add fluff, restate existing points merely to add "
                f"words, or invent facts."
            )
        else:
            hint_lines: list[str] = []
            if redundancy_hint is not None and redundancy_hint.findings:
                hint_lines.append("Specific redundancy already detected (address these first):")
                for finding in redundancy_hint.findings:
                    hint_lines.append(f"- {finding.description}")
            hint_str = "\n".join(hint_lines)
            hard_max_note = (
                f" This includes a HARD, non-negotiable maximum of {bounds.hard_max_words} "
                f"words that must never be exceeded."
                if bounds.hard_max_words is not None
                else ""
            )
            instruction = (
                f"The draft is currently {current_words} words, which exceeds the target range "
                f"({min_words}–{max_words} words; target: {bounds.target_words}).{hard_max_note}\n"
                f"Please tighten the prose, eliminate redundancy, and condense phrasing while "
                f"strictly preserving all outline sections, factual points, and citations.\n"
                f"{hint_str}"
            ).strip()

        prompt = f"""You are executing a LENGTH CORRECTION pass for the academic paper: "{spec.title}".

{ACADEMIC_PRIORITY_ORDERING_GUIDANCE}

INSTRUCTION:
{instruction}

TARGET BODY WORDS: aim for approximately {aim_words} words (Allowed range: {min_words} to {max_words} words)

REQUIRED OUTLINE:
{outline_str}

EXPLICIT ASSIGNMENT REQUIREMENTS:
{reqs_str}

CURRENT DRAFT:
```markdown
{draft_doc.text}
```

OUTPUT FORMAT:
Return a ```yaml code block containing:
```yaml
body_markdown: |
  <revised complete markdown body>
word_count_estimate: <integer>
warnings: []
```"""

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            system_instruction=ACADEMIC_PRIORITY_ORDERING_GUIDANCE,
            context={
                "topic": spec.topic,
                "title": spec.title,
                "target_words": spec.target_words,
                "correction": direction,
                "run_id": run_id,
            },
            timeout_seconds=600,
            cwd=cwd,
            custom_backend=custom_backend,
        )

        if not result.success:
            return WriterDraftResult(
                document=draft_doc,
                word_count=current_words,
                provider=result.provider,
                warnings=[f"Length correction failed: {result.error_message}"],
            )

        structured = result.structured_output or {}
        body = structured.get("body_markdown")
        if not body or not isinstance(body, str) or not body.strip():
            body = result.raw_output.strip()

        doc = Document.parse(body, title=spec.title, mode=WritingMode.ACADEMIC)
        words = count_body_words(body)

        return WriterDraftResult(
            document=doc,
            raw_output=result.raw_output,
            word_count=words,
            provider=result.provider,
            model=result.model,
            duration_seconds=result.duration_seconds,
            warnings=structured.get("warnings", []),
            metadata=result.metadata,
        )
