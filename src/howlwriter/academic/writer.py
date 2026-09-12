"""Real model-backed Academic Writer executing WritingRole.WRITER via HowlPlane."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from howlwriter.academic.length import calculate_word_tolerance, count_body_words
from howlwriter.academic.spec import AssignmentSpec, extract_constraints
from howlwriter.citations.apa7 import APA7Formatter
from howlwriter.config.schema import HowlWriterConfig
from howlwriter.constraints.specs import ConstraintSet
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole


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

    @staticmethod
    def _constraint_block(spec: AssignmentSpec) -> str:
        constraints = extract_constraints(spec)
        target = constraints.effective_target_words()
        hard = constraints.effective_max_words()
        lines: list[str] = ["CONSTRAINTS (highest priority after factual integrity):"]
        if target is not None:
            lines.append(f"- Target body words: ~{target}")
        if hard is not None:
            lines.append(f"- Hard maximum body words: {hard}")
            lines.append("- Do not casually consume the full maximum; aim below it unless told otherwise.")
        if constraints.max_pages is not None:
            lines.append(f"- Hard maximum pages: {constraints.max_pages}")
        if constraints.required_sections:
            lines.append(f"- Required outline sections: {', '.join(constraints.required_sections)}")
        if constraints.required_items:
            lines.append("- Required rubric items (preserve one clear instance of each):")
            for item in constraints.required_items:
                lines.append(f"    * {item}")
        if constraints.prohibited_content:
            lines.append("- Prohibited / unsupported content:")
            for p in constraints.prohibited_content:
                lines.append(f"    * {p}")
        if constraints.compression_notes:
            lines.append(f"- Compression guidance: {constraints.compression_notes}")
        lines.append("- Stop elaborating once all required criteria are demonstrated and length is met.")
        lines.append("- Prefer concise grounded statements over impressive-looking specificity.")
        return "\n".join(lines)

    def draft_paper(
        self,
        spec: AssignmentSpec,
        sources: list[Source],
        config: HowlWriterConfig | None = None,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        run_id: str | None = None,
    ) -> WriterDraftResult:
        """Invokes the WRITER role to draft an academic paper strictly grounded in retrieved sources."""
        bridge = get_howlplane_bridge()
        formatter = APA7Formatter()

        min_words, max_words = calculate_word_tolerance(
            spec.target_words, spec.word_tolerance_percent
        )

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

        if spec.outline:
            outline_str = "\n".join(f"- {topic}" for topic in spec.outline)
        else:
            outline_str = "- Comprehensive analysis"

        if spec.requirements:
            reqs_str = "\n".join(f"- {r}" for r in spec.requirements)
        else:
            reqs_str = "- Follow academic conventions"

        prompt = f"""You are executing the WRITER role under the HowlWriter academic contract.
Your mission is to draft a rigorous, high-quality academic research paper on the specified topic,
strictly structured according to the required outline and strictly grounded in the retrieved sources.

ASSIGNMENT TITLE: {spec.title}
TOPIC: {spec.topic}
TARGET WORD COUNT (BODY): {spec.target_words} words (Allowed range: {min_words} to {max_words} words)
CITATION STYLE: APA 7

REQUIRED OUTLINE:
{outline_str}

EXPLICIT ASSIGNMENT REQUIREMENTS:
{reqs_str}

RETRIEVED SOURCE EVIDENCE (ONLY USE THESE SOURCES):
{sources_block}

{self._constraint_block(spec)}

CRITICAL ACADEMIC WRITING RULES:
1. Ground all factual assertions in the retrieved sources above.
2. Insert APA 7 in-text citations using the exact author/year format provided for each source
   (e.g. (Smith, 2024) or Smith (2024)).
3. DO NOT invent external sources, authors, or DOIs not provided in the source evidence list.
4. DO NOT invent or fabricate statistics, dates, study findings, or exact technical identifiers.
5. If evidence is insufficient for a claim, qualify the statement (e.g. "Research suggests...") or omit it.
6. Address every section in the required outline. Use clear markdown headings for major outline sections.
7. Write substantive, rigorous academic prose aiming for the body target of {spec.target_words} words.
8. DO NOT include a "# References" section at the end (the HowlWriter engine generates and attaches it).

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
            else []
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
    ) -> WriterDraftResult:
        """Performs a bounded corrective pass to bring paper body within target word count."""
        bridge = get_howlplane_bridge()
        min_words, max_words = calculate_word_tolerance(
            spec.target_words, spec.word_tolerance_percent
        )

        if direction == "EXPAND":
            instruction = (
                f"The draft is currently {current_words} words, which is below the target range "
                f"({min_words}–{max_words} words; target: {spec.target_words}).\n"
                f"Please expand thin sections with deeper academic analysis and discussion "
                f"using the EXISTING retrieved sources and evidence. DO NOT add fluff or invent facts."
            )
        else:
            instruction = (
                f"The draft is currently {current_words} words, which exceeds the target range "
                f"({min_words}–{max_words} words; target: {spec.target_words}).\n"
                f"Please tighten the prose, eliminate redundancy, and condense phrasing while "
                f"strictly preserving all outline sections, factual points, and citations."
            )

        constraints = extract_constraints(spec)
        target = constraints.effective_target_words()
        hard = constraints.effective_max_words()
        length_guidance = f"Target body words: ~{target or spec.target_words}"
        if hard is not None:
            length_guidance += f"; hard maximum: {hard}"
            if max_words > hard:
                max_words = hard

        prompt = f"""You are executing a LENGTH CORRECTION pass for the academic paper: "{spec.title}".

INSTRUCTION:
{instruction}

{length_guidance}

Allowed range: {min_words} to {max_words} words.

{self._constraint_block(spec)}

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
