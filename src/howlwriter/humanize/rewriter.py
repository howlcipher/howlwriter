"""HumanizerRewriter: model-backed prose rewriting ("make this sound less AI").

SafeRewriter is the deterministic safe rewrite: literal substitution of a
banned word for its configured replacement, only when opted in via
config.apply_safe_rewrites.

ModelHumanizerRewriter executes the real WritingRole.HUMANIZER through HowlPlane
with a deliberate role contract and structured output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Protocol

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.report import ChangeRecord
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.voice import VoiceExample, VoiceProfile
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


MAX_SINGLE_PASS_CHARS = 100_000


def _load_voice_profile(value: str | None) -> VoiceProfile | None:
    """Resolve a config.voice_profile value to a VoiceProfile when it names a file.

    If `value` is a path to an existing JSON file, parse it as a VoiceProfile.
    Otherwise treat it as an author label and return None. This keeps the
    config field a simple string while still allowing callers to point at a
    real profile on disk.
    """
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return VoiceProfile.from_dict(data)
    except Exception:
        return None


def _mode_specific_instructions(mode: Any) -> str:
    """Return mode-specific guardrails for the Humanizer prompt."""
    from howlwriter.domain.modes import WritingMode

    m = mode if isinstance(mode, WritingMode) else WritingMode.CUSTOM
    if m == WritingMode.LINKEDIN:
        return "\n".join([
            "LINKEDIN / SHORT-FORM MODE:",
            "- Prefer a direct opening. Cut throat-clearing setup.",
            "- Preserve first-person voice and conversational tone if the source uses them.",
            "- Keep sentence length varied; keep short punchy sentences.",
            "- Avoid headings, corporate filler, generic motivational endings, "
            "and fake thought-leadership tone.",
            "- Preserve humor, sarcasm, and mild roughness where present.",
            "- Do not add a conclusion that merely restates the post.",
            "- Do not casualize professional substance; keep technical terms intact.",
        ])
    if m == WritingMode.ACADEMIC:
        return "\n".join([
            "ACADEMIC MODE:",
            "- Keep formal clarity, citation structure, technical terminology, "
            "qualifications, and scholarly tone.",
            "- Remove generic LLM filler, canned transitions, repetitive summaries, "
            "inflated importance language, and mechanical paragraph structures.",
            "- Do not inject casual contractions, jokes, fragments, or "
            "LinkedIn-style language into the prose.",
            "- Preserve hedging, uncertainty, and scope exactly as in the source.",
        ])
    if m == WritingMode.TECHNICAL:
        return "\n".join([
            "TECHNICAL MODE:",
            "- Preserve precise technical terminology, numbers, and configuration details.",
            "- Remove generic marketing language, but keep the prose clear and direct.",
            "- Do not simplify correct technical terms into casual approximations.",
        ])
    if m == WritingMode.CASUAL:
        return "\n".join([
            "CASUAL MODE:",
            "- Keep a relaxed, natural voice. Preserve contractions, fragments, "
            "and personal phrasing.",
            "- Avoid over-polishing into corporate prose.",
        ])
    return "\n".join([
        "STANDARD MODE:",
        "- Remove generic AI patterns while preserving the author's natural voice.",
        "- Do not force a particular register; follow the source.",
    ])


def _render_voice_profile(profile: VoiceProfile | None) -> str:
    if profile is None:
        return "None"
    parts: list[str] = []
    if profile.author_name:
        parts.append(f"author_name: {profile.author_name}")
    if profile.formality is not None:
        parts.append(f"formality: {profile.formality}")
    if profile.sentence_length_mean is not None:
        parts.append(f"sentence_length_mean: {profile.sentence_length_mean:.1f}")
    if profile.sentence_length_stdev is not None:
        parts.append(f"sentence_length_stdev: {profile.sentence_length_stdev:.1f}")
    if profile.paragraph_length_mean is not None:
        parts.append(f"paragraph_length_mean: {profile.paragraph_length_mean:.1f}")
    if profile.contraction_rate is not None:
        parts.append(f"contraction_rate: {profile.contraction_rate:.2f}")
    if profile.fragment_rate is not None:
        parts.append(f"fragment_rate: {profile.fragment_rate:.2f}")
    if profile.rhetorical_question_rate is not None:
        parts.append(f"rhetorical_question_rate: {profile.rhetorical_question_rate:.2f}")
    if profile.preferred_phrases:
        parts.append(f"preferred_phrases: {', '.join(profile.preferred_phrases)}")
    if profile.disliked_phrases:
        parts.append(f"disliked_phrases: {', '.join(profile.disliked_phrases)}")
    if profile.structural_notes:
        parts.append(f"structural_notes: {profile.structural_notes}")
    examples = [
        ex.text if isinstance(ex, VoiceExample) else str(ex.get("text", ""))
        for ex in profile.representative_examples[:3]
    ]
    if examples:
        parts.append("representative_examples:")
        for example in examples:
            parts.append(f"  - {example}")
    return "\n".join(parts) if parts else "Empty VoiceProfile"


class ModelHumanizerRewriter:
    """Real model-backed Humanizer executor wired through HowlPlane."""

    role: WritingRole = WritingRole.HUMANIZER

    def rewrite(
        self,
        document: Document,
        config: HowlWriterConfig,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        run_id: str | None = None,
    ) -> ModelHumanizeResult:
        if len(document.text) > MAX_SINGLE_PASS_CHARS:
            raise ValueError(
                f"Document size ({len(document.text)} chars) exceeds safe single-pass limit "
                f"({MAX_SINGLE_PASS_CHARS} chars). Please process document in sections or chapters."
            )

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

        voice_profile = _load_voice_profile(config.voice_profile)
        voice_text = _render_voice_profile(voice_profile)

        mode_label = (
            document.mode.value
            if isinstance(document.mode, WritingMode)
            else (str(document.mode) if document.mode else "standard")
        )
        mode_instructions = _mode_specific_instructions(document.mode)

        prompt = "\n".join([
            "You are executing the HUMANIZER writing role under the HowlWriter contract.",
            "Your objective is to make the input text read like the actual author wrote it, "
            "not like a generic AI draft.",
            "You do NOT optimize for AI-detector scores, detector evasion, "
            'or "human probability" metrics.',
            "You must NOT intentionally misspell words, inject grammar errors, "
            "randomly alter punctuation, invent fake personal anecdotes, or corrupt prose.",
            "The quality target is authentic writing, not classifier manipulation.",
            "",
            "HUMANIZER PRIORITIES (in order):",
            "1. PRESERVE FACTS: never change numbers, dates, percentages, names, "
            "attribution, technical terms, source citations, uncertainty/hedging, "
            "or causal meaning.",
            "2. PRESERVE INTENT: keep the author's argument, question, criticism, "
            "emphasis, and stance unchanged.",
            "3. PRESERVE AUTHOR VOICE: do not normalize the author into generic "
            "polished corporate prose. Keep uneven sentence length, direct wording, "
            "contractions, personal phrasing, concrete details, occasional roughness, "
            "humor, and opinion where present.",
            "4. REMOVE GENERIC LLM HABITS: cut or rework canned openings, canned "
            "conclusions, mechanical transitions, formulaic contrasts, repetitive "
            "three-part lists, generic intensifiers, abstract corporate filler, and "
            "artificially symmetrical structure.",
            "5. MAKE THE MINIMUM NECESSARY EDIT: if a sentence is already natural and "
            "clear, leave it untouched. ZERO CHANGES is an excellent result when the "
            "input is already clean.",
            "6. AVOID OVER-POLISHING: do not upgrade vocabulary, replace simple verbs "
            "with formal ones, remove contractions, add unnecessary transitions, "
            "convert opinions into neutral consultant prose, or smooth away natural quirks.",
            "7. PREFER CONCRETE LANGUAGE: keep specific numbers, examples, and details "
            "that are already present. Never invent personal experience, statistics, "
            "or anecdotes.",
            "",
            mode_instructions,
            "",
            "ZERO-CHANGE RULE:",
            "If the text is already natural, direct, and free of the patterns above, "
            "return the original text EXACTLY (character-for-character) and set "
            "changes_made to an empty list.",
            "",
            "CHANGE REASON TAXONOMY (use these reasons when describing edits):",
            "- GENERIC_LLM_PHRASE",
            "- REDUNDANT_SETUP",
            "- CANNED_TRANSITION",
            "- CANNED_OPENING",
            "- CANNED_CONCLUSION",
            "- UNNECESSARY_SUMMARY",
            "- VOICE_MISMATCH",
            "- OVERPOLISHED",
            "- REPETITIVE_STRUCTURE",
            "- CORPORATE_FILLER",
            "- RHYTHM_NORMALIZATION",
            "- FACT_PRESERVATION_NOTE (use only when you reworded something generic "
            "but kept every fact)",
            "",
            f"CONTEXT:\n- Writing Mode: {mode_label}",
            f"- Transformation Strength: {config.humanization_strength}",
            "- Voice Profile:",
            voice_text,
            f"- {banned_summary}",
            "- Detected Style Issues:",
            issues_text,
            "",
            "ORIGINAL TEXT:",
            "```markdown",
            document.text,
            "```",
            "",
            "OUTPUT FORMAT:",
            "Return a ```yaml code block containing:",
            "```yaml",
            "resulting_text: |",
            "  <exact rewritten markdown text; if no changes are needed, "
            "copy the original exactly>",
            "changes_made:",
            '  - description: "<brief description of the edit>"',
            '    reason: "<one of the change-reason taxonomy values>"',
            '  - description: "<another edit>"',
            '    reason: "<taxonomy value>"',
            'rationale: "<brief rationale of why changes were made, or why no changes were needed>"',
            "warnings: []",
            "```",
        ])

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            context={
                "title": document.title,
                "mode": document.mode,
                "strength": config.humanization_strength,
                "run_id": run_id,
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
                if isinstance(item, dict):
                    desc = str(item.get("description") or "").strip()
                    reason = str(item.get("reason") or "").strip()
                    if desc:
                        changes.append(
                            ChangeRecord(
                                description=desc,
                                reason=reason or "GENERIC_LLM_PHRASE",
                            )
                        )
                elif isinstance(item, str) and item.strip():
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
