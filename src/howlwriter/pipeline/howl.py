"""The one genuinely-working end-to-end path: INPUT -> EDIT -> HUMANIZE ->
LINT -> RED PEN -> FINAL REVIEW -> OUTPUT.

Every stage here is real and deterministic. No research, no citation
generation, no LLM rewriting happens in this pipeline -- those are
separate, independently-callable commands (/research, /cite, /fact-check
with --verify) operating on data the caller supplies, not part of `howl`'s
MVP scope. See docs/architecture.md for the full stage-by-stage contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from howlwriter.config.schema import HowlWriterConfig
from howlwriter.domain.document import Document
from howlwriter.domain.report import WritingReport
from howlwriter.editing.editor import PassthroughEditor
from howlwriter.facts.extraction import HeuristicClaimExtractor
from howlwriter.humanize.rewriter import SafeRewriter
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD, RuleMatch
from howlwriter.redpen.critic import RedPenEngine, RedPenFinding
from howlwriter.review.meaning import MeaningPreservationReviewer, MeaningPreservationResult


@dataclass
class PipelineResult:
    original_document: Document
    final_document: Document
    lint_matches: list[RuleMatch]
    red_pen_findings: list[RedPenFinding]
    meaning_result: MeaningPreservationResult
    report: WritingReport


def run_howl_pipeline(path: str | Path, config: HowlWriterConfig) -> PipelineResult:
    text = Path(path).read_text(encoding="utf-8")
    original_document = Document.parse(text, title=Path(path).stem)

    # EDIT: deterministic whitespace/heading normalization only. No prose
    # rewriting -- that would be the model-backed Editor, not invoked here.
    edited_document = PassthroughEditor().edit(original_document)

    # HUMANIZE: the only rewrite `howl` performs on its own is a
    # banned-word substitution, and only when the caller both configured a
    # replacement and opted in via config.apply_safe_rewrites. Otherwise
    # this stage contributes findings only, folded into the LINT stage
    # below since it runs the same rule engine over the same document.
    safe_rewrite = SafeRewriter().rewrite(edited_document, config)
    final_document = safe_rewrite.document

    # LINT: the full configured rule set over the (possibly rewritten)
    # document -- this is what actually surfaces the humanization findings.
    lint_matches = LintEngine().run(final_document, config)

    # RED PEN: deterministic critique, cross-referencing extracted claims.
    # Every extracted claim is UNVERIFIABLE by construction -- no sources
    # exist in this path; fact-checking is a separate command.
    claims = HeuristicClaimExtractor().extract(final_document)
    red_pen_findings = RedPenEngine().critique(final_document, claims=claims)

    # FINAL REVIEW: a real diff against the original, not a rubber stamp.
    # PASS here means the safe rewrite (if any) changed nothing of
    # substance -- not that no rewriting happened.
    meaning_result = MeaningPreservationReviewer().compare(original_document, final_document)

    banned_word_count = sum(1 for m in lint_matches if m.rule_code == AI_STYLE_BANNED_WORD)
    ai_style_count = len(lint_matches) - banned_word_count
    status = "READY" if meaning_result.status == "PASS" else "NEEDS_REVIEW"

    report = WritingReport(
        status=status,
        banned_words=banned_word_count,
        ai_style_warnings=ai_style_count,
        meaning_preservation=meaning_result.status,
        changes=list(safe_rewrite.changes),
    )

    return PipelineResult(
        original_document=original_document,
        final_document=final_document,
        lint_matches=lint_matches,
        red_pen_findings=red_pen_findings,
        meaning_result=meaning_result,
        report=report,
    )
