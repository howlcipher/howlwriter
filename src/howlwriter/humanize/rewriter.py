"""HumanizerRewriter: model-backed prose rewriting ("make this sound less AI").

SafeRewriter is the deterministic safe rewrite: literal substitution of a
banned word for its configured replacement, only when opted in via
config.apply_safe_rewrites.

ModelHumanizerRewriter executes the real WritingRole.HUMANIZER through HowlPlane
with a deliberate role contract and structured output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Protocol

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.report import ChangeRecord
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.humanize.detector import detect
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole
from howlwriter.linting.engine import LintEngine


class HumanizerRewriter(Protocol):
    role: WritingRole

    def rewrite(
        self, document: Document, config: HowlWriterConfig
    ) -> Any: ...


class NotConfiguredHumanizer(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.HUMANIZER)

    def rewrite(
        self, document: Document, config: HowlWriterConfig
    ) -> Any:
        return self.run(document, config)


@dataclass
class SafeRewriteResult(DataClassSerializationMixin):
    document: Document
    changes: list[ChangeRecord] = field(default_factory=list)


class SafeRewriter:
    def rewrite(
        self, document: Document, config: HowlWriterConfig
    ) -> SafeRewriteResult:
        replacements = {
            bw.word.lower(): bw.replacement
            for bw in config.banned_words
            if bw.replacement
        }
        if not config.apply_safe_rewrites or not replacements:
            return SafeRewriteResult(document=document, changes=[])

        pattern = re.compile(
            r"\b(" + "|".join(re.escape(w) for w in replacements) + r")\b",
            re.IGNORECASE,
        )
        changes: list[ChangeRecord] = []

        def _substitute(match: re.Match) -> str:
            original = match.group(0)
            replacement = replacements[original.lower()]
            changes.append(
                ChangeRecord(
                    description=f'replaced "{original}" with "{replacement}"'
                )
            )
            return replacement

        new_text = pattern.sub(_substitute, document.text)
        new_document = Document.parse(
            new_text, title=document.title, mode=document.mode
        )
        return SafeRewriteResult(document=new_document, changes=changes)


@dataclass
class ModelHumanizeResult(DataClassSerializationMixin):
    document: Document
    changes: list[ChangeRecord] = field(default_factory=list)
    rationale: str = ""
    warnings: list[str] = field(default_factory=list)
    provider: str = ""
    model: str | None = None
    duration_seconds: float = 0.0
    independence_status: str = "INDEPENDENT"
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelHumanizerRewriter:
    """Real model-backed Humanizer executor wired through HowlPlane."""

    role: WritingRole = WritingRole.HUMANIZER

    def rewrite(
        self,
        document: Document,
        config: HowlWriterConfig,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
    ) -> ModelHumanizeResult:
        bridge = get_howlplane_bridge()

        # Run deterministic analysis to supply context to the model
        lint_findings = LintEngine().run(document, config)
        humanize_findings = detect(document, config)

        issues_summary: list[str] = []
        for finding in humanize_findings[:10]:
            issues_summary.append(f"- {finding.rule_code}: {finding.message}")
        for match in lint_findings[:10]:
            issues_summary.append(f"- {match.rule_code}: {match.message}")
        issues_text = "\n".join(issues_summary) if issues_summary else "None"

        banned_words_list = [bw.word for bw in config.banned_words]
        banned_patterns_list = list(config.banned_patterns)
        banned_words_str = ", ".join(banned_words_list) or "None"
        banned_patterns_str = ", ".join(banned_patterns_list) or "None"
        banned_summary = (
            f"Banned Words: {banned_words_str}; "
            f"Banned Patterns: {banned_patterns_str}"
        )

        prompt = f"""You are executing the HUMANIZER writing role under the HowlWriter contract.
Your objective is to rewrite the input text to eliminate mechanical AI-generated prose rhythms,
clichés, and artificial polish, while strictly preserving all factual meaning, numbers, claims, and intent.

HUMANIZER PRIORITIES:
1. Preserve factual meaning - do not change any facts, numbers, dates, or claims.
2. Preserve author intent - keep the core message and thesis intact.
3. Preserve useful personal quirks and natural voice.
4. Remove generic LLM phrasing and clichés (e.g. "delve", "tapestry", "in conclusion", "furthermore").
5. Vary overly mechanical sentence length and repetitive syntax.
6. Remove unnecessary polish and corporate stiffness.
7. Remove filler words and rhetorical padding.
8. Make minimal edits - if a sentence is already clean and natural, leave it untouched.
9. If the input is already clean human writing with no clichés, return it untouched with changes_made: [].
10. Do not fabricate facts, statistics, or sources.

CONTEXT:
- Writing Mode: {document.mode or 'standard'}
- Transformation Strength: {config.humanization_strength}
- Voice Profile: {config.voice_profile or 'None'}
- {banned_summary}
- Detected Style Issues:
{issues_text}

ORIGINAL TEXT:
```markdown
{document.text}
```

OUTPUT FORMAT:
Return a ```yaml code block containing:
```yaml
resulting_text: |
  <exact rewritten markdown text>
changes_made:
  - "<brief description of change 1>"
  - "<brief description of change 2>"
rationale: "<brief rationale of why changes were made>"
warnings: []
```"""

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            context={
                "title": document.title,
                "mode": document.mode,
                "strength": config.humanization_strength,
            },
            timeout_seconds=300,
            cwd=cwd,
            custom_backend=custom_backend,
        )

        if not result.success:
            err = result.error_message or "Execution failed"
            raise RuntimeError(
                f"Humanizer provider '{result.provider}' failed: {err}"
            )

        structured = result.structured_output or {}
        new_text = structured.get("resulting_text")
        if not new_text or not isinstance(new_text, str) or not new_text.strip():
            # Fallback to raw output if structured parse didn't find resulting_text
            new_text = result.raw_output.strip()

        if not new_text or not new_text.strip():
            raise RuntimeError(
                f"Humanizer provider '{result.provider}' returned an empty or unparseable response."
            )

        changes: list[ChangeRecord] = []
        if "changes_made" in structured and isinstance(structured["changes_made"], list):
            for item in structured["changes_made"]:
                if isinstance(item, str) and item.strip():
                    changes.append(ChangeRecord(description=item.strip()))
        elif new_text.strip() != document.text.strip():
            changes.append(
                ChangeRecord(description="Model-backed humanization rewrite")
            )

        rationale = str(structured.get("rationale") or "")
        warnings = [
            str(w) for w in structured.get("warnings", []) if isinstance(w, str)
        ]

        new_doc = Document.parse(
            new_text, title=document.title, mode=document.mode
        )
        return ModelHumanizeResult(
            document=new_doc,
            changes=changes,
            rationale=rationale,
            warnings=warnings,
            provider=result.provider,
            model=result.model,
            duration_seconds=result.duration_seconds,
            independence_status=result.independence_status,
            metadata=result.metadata,
        )
