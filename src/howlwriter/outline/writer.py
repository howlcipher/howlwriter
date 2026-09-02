"""The generation stage the general pipeline never had.

`run_howl_pipeline` reads a file and transforms it. That is the right shape for
a draft someone already wrote, and the wrong shape for an outline, which is not
a draft and cannot be humanized into one. So outline runs get a writer stage in
front: outline in, draft out, and from there the existing chain -- humanize,
lint, red pen, meaning review -- runs unchanged.

Reusing `WritingRole.WRITER` rather than inventing a role keeps the dispatch
seam single. Everything that follows about provenance depends on there being
exactly one place a prompt leaves this system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode, parse_mode
from howlwriter.domain.outline import Outline
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.outline.freedom import FreedomAssessment, assess_freedom
from howlwriter.outline.prompt import render_outline_prompt

#: Sent as the system instruction. Kept short and absolute: the detail lives in
#: the user prompt, and a system instruction that repeats it at length mostly
#: dilutes both.
OUTLINE_WRITER_SYSTEM_INSTRUCTION = (
    "You expand an author's outline into finished prose under a strict "
    "authority order. The author's own sentences, claims, and structure "
    "outrank your judgement about what would read better. You never invent "
    "facts about the author's life, work, or experience. You report every "
    "factual assertion you add. Producing smooth prose that quietly departs "
    "from the outline is a failure, not a stylistic choice."
)


@dataclass
class OutlineDraftResult:
    """What the writer produced, and everything a provenance record needs."""

    document: Document
    raw_output: str = ""
    added_claims: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    duration_seconds: float | None = None
    independence_status: str | None = None
    assessment: FreedomAssessment | None = None
    effective_system_instruction: str = ""
    effective_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class OutlineWriter:
    """Expands an outline into a draft through the shared model seam."""

    role = WritingRole.WRITER

    def draft(
        self,
        outline: Outline,
        *,
        voice_block: str = "",
        mode_rules: str = "",
        run_id: str | None = None,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        timeout_seconds: int = 600,
    ) -> OutlineDraftResult:
        bridge = get_howlplane_bridge()
        assessment = assess_freedom(outline)
        prompt = render_outline_prompt(
            outline, assessment, voice_block=voice_block, mode_rules=mode_rules
        )
        mode = parse_mode(outline.mode) if outline.mode else WritingMode.CUSTOM

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            system_instruction=OUTLINE_WRITER_SYSTEM_INSTRUCTION,
            context={
                "topic": outline.topic,
                "title": outline.title,
                "mode": mode.value,
                "target_words": outline.target_words,
                "generation_freedom": assessment.freedom.value,
                "run_id": run_id,
            },
            timeout_seconds=timeout_seconds,
            cwd=cwd,
            custom_backend=custom_backend,
        )

        if not result.success:
            error = result.error_message or "writer execution failed"
            raise RuntimeError(f"Writer provider '{result.provider}' failed: {error}")

        structured = result.structured_output or {}
        body = structured.get("body_markdown")
        if not isinstance(body, str) or not body.strip():
            body = (result.raw_output or "").strip()
        if not body.strip():
            raise RuntimeError(
                f"Writer provider '{result.provider}' returned an empty response."
            )

        added = structured.get("added_claims")
        gaps = structured.get("gaps")
        warnings = structured.get("warnings")

        return OutlineDraftResult(
            document=Document.parse(
                body, title=outline.title or outline.topic, mode=mode
            ),
            raw_output=result.raw_output or "",
            added_claims=[c for c in added if isinstance(c, dict)] if isinstance(added, list) else [],
            gaps=[str(g) for g in gaps] if isinstance(gaps, list) else [],
            warnings=[str(w) for w in warnings] if isinstance(warnings, list) else [],
            provider=result.provider,
            model=result.model,
            duration_seconds=result.duration_seconds,
            independence_status=getattr(result, "independence_status", None),
            assessment=assessment,
            # The exact strings handed to the dispatch boundary, kept so
            # provenance never has to reconstruct them and call it exact.
            effective_system_instruction=OUTLINE_WRITER_SYSTEM_INSTRUCTION,
            effective_prompt=prompt,
            metadata=dict(getattr(result, "metadata", {}) or {}),
        )
