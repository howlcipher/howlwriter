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
from howlwriter.domain.voice import VoiceProfile
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

    `--voice <name>` also arrives here: the CLI resolves a named personal
    voice to its profile.json path before setting this field, so both flags
    converge on one loader rather than growing a second consumer.
    """
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = VoiceProfile.from_dict(data)
    except Exception:
        return None

    # Overrides are stored beside the profile so a rebuild cannot overwrite
    # them, which means they have to be re-attached when loading from a voice
    # directory. A standalone profile file simply has none.
    overrides_path = path.parent / "overrides.yaml"
    if profile.is_corpus_built and overrides_path.is_file():
        try:
            from howlwriter.voice.corpus.store import VoiceStore

            profile.overrides = VoiceStore(
                path.parent.name, root=path.parent.parent
            ).load_overrides()
        except Exception:
            pass
    return profile


def _mode_specific_instructions(mode: Any) -> str:
    """Return mode-specific guardrails for the Humanizer prompt."""
    from howlwriter.domain.modes import WritingMode

    m = mode if isinstance(mode, WritingMode) else WritingMode.CUSTOM
    if m == WritingMode.LINKEDIN:
        return "\n".join([
            "LINKEDIN / SHORT-FORM MODE:",
            "- Prefer a direct opening. Cut throat-clearing setup.",
            "- Deliver a direct, conversational argument with natural flow and human cadence.",
            "- Preserve conversational pronouns ('I', 'you', 'your business', 'we') when natural. "
            "NEVER sanitize them into formal third-person ('enterprises', 'organizations', 'one').",
            "- Avoid corporate whitepaper jargon and thesaurus upgrades "
            "('constructs', 'ceases to function', 'renders vulnerable', 'substitutability', "
            "'commoditization', 'utilize'). "
            "NEVER replace normal conversational words "
            "('developers', 'build', 'use', 'companies', 'cheap', 'replaceable', 'moat') "
            "with abstract synonyms. Use crisp, direct, punchy language.",
            "- Do NOT strip out essential thesis distinctions or qualifying nuance "
            "('The point is not that X... the real issue is Y'). A substantive contrast that "
            "clarifies the boundary of an argument is NOT generic AI filler.",
            "- Keep paragraphs compact (1-3 sentences) with natural human rhythm. "
            "Do NOT force all paragraphs into identical length or artificial bullet stencils.",
            "- Strictly forbid algorithmic engagement bait "
            "('Agree?', 'Thoughts?', 'Drop a comment', 'What do you think?').",
            "- Strictly forbid fake viral rhetorical hooks "
            "('Let that sink in', 'Here's the thing', 'This changes everything').",
            "- A small set of 2-4 natural, relevant hashtags at the very end is acceptable if appropriate "
            "(e.g., #SoftwareEngineering #AI #SaaS), but strictly avoid hashtag spam.",
            "- Strictly avoid emoji bullets or decorative emoji spam.",
            "- End on a thoughtful, concrete observation or dilemma rather than a "
            "forced motivational ending.",
            "- Do not casualize technical terms into vague hand-waving.",
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


def _render_voice_profile(profile: VoiceProfile | None, mode: Any = None) -> str:
    """Render a VoiceProfile for the prompt.

    Delegates to voice/application.py, which handles both schema
    generations: a hand-written profile renders exactly as it always has,
    while a corpus-built one renders contextual tendencies and is framed as a
    distribution rather than a target.
    """
    from howlwriter.voice.application import render_profile

    return render_profile(profile, mode)


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
        voice_text = _render_voice_profile(voice_profile, document.mode)

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
            "INPUT ADAPTATION (SPARSE PROMPT VS COMPLETE DRAFT):",
            "- If the input is a SPARSE ROUGH IDEA, OUTLINE, OR PROMPT "
            "(e.g. short rough notes, or containing instructions like 'Make that into a LinkedIn post'):",
            "  * Expand the core reasoning into a complete, coherent piece appropriate for the writing mode.",
            "  * Fulfill the prompt by developing the causal argument, concrete implications, and supporting "
            "distinctions, while strictly preserving the author's stated stance.",
            "  * Strip meta-instructions (e.g., 'Make that into a LinkedIn post') from the resulting output.",
            "- If the input is an EXISTING DRAFT OR COMPLETE ESSAY:",
            "  * Follow the MINIMUM NECESSARY EDIT rule strictly: if the text is already natural, direct, "
            "and clear, leave it untouched. ZERO CHANGES is an excellent result for clean human drafts.",
            "",
            mode_instructions,
            "",
            "ZERO-CHANGE RULE:",
            "If the input is an existing draft and is already natural, direct, and free of the "
            "patterns above, return the original text EXACTLY (character-for-character) and set "
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
            "- ENGAGEMENT_BAIT_REMOVED",
            "- VIRAL_HOOK_REMOVED",
            "- SOCIAL_SLOP_REMOVED",
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
