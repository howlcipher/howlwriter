"""Meaning preservation: comparing ORIGINAL INTENT vs FINAL OUTPUT.

MeaningPreservationReviewer.compare() is a deterministic heuristic diff --
numbers, attribution phrases, and hedge words between before/after --
never a hardcoded PASS. It returns PASS only when nothing of substance
changed, and FLAGGED (with itemized diffs) otherwise.

ModelMeaningReviewer is the real model-backed semantic meaning reviewer
wired through HowlPlane to perform deep adversarial semantic comparison with
independent reviewer guarantee.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Literal, Protocol

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole

Status = Literal["PASS", "FLAGGED"]
SemanticVerdict = Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_ATTRIBUTION_MARKERS = (
    "according to", "study by", "reports that", "found that"
)
_HEDGE_WORDS = (
    "may", "might", "could", "suggests", "appears", "likely",
    "possibly", "perhaps", "reportedly",
)
_CAUSAL_MARKERS = (
    "causes", "caused", "causing", "causation", "leads to",
    "resulted in", "produces", "produced",
)
_CORRELATIONAL_MARKERS = (
    "associated with", "correlated with", "correlation", "linked to",
    "related to", "connected to", "correlates with",
)
_FILLER_TRANSITION_PHRASES = (
    "furthermore", "moreover", "in addition", "however", "therefore",
    "thus", "consequently", "in conclusion", "to conclude", "finally",
    "as a result", "for example", "for instance", "in summary",
)
_CANNED_CONCLUSION_PHRASES = (
    "in conclusion", "to conclude", "in summary", "to summarize",
)
_WORD = re.compile(r"[A-Za-z']+")
_SENTENCE_COUNT_RATIO_THRESHOLD = 0.2
_SENTENCE_COUNT_MIN_DELTA = 2


@dataclass
class MeaningDiff(DataClassSerializationMixin):
    kind: str
    description: str


@dataclass
class MeaningPreservationResult(DataClassSerializationMixin):
    status: Status = "PASS"
    diffs: list[MeaningDiff] = field(default_factory=list)
    style_diffs: list[MeaningDiff] = field(default_factory=list)


def _count_markers(text: str, markers: tuple[str, ...]) -> Counter:
    lowered = text.lower()
    return Counter({
        marker: lowered.count(marker)
        for marker in markers
        if lowered.count(marker)
    })


def _count_words(text: str, words: tuple[str, ...]) -> Counter:
    tokens = [t.lower() for t in _WORD.findall(text)]
    token_counts = Counter(tokens)
    return Counter({
        word: token_counts[word] for word in words if token_counts[word]
    })


class MeaningPreservationReviewer:
    """Deterministic heuristic meaning preservation checker."""

    def compare(
        self, original: Document, revised: Document
    ) -> MeaningPreservationResult:
        substantive: list[MeaningDiff] = []
        substantive.extend(self._number_diffs(original.text, revised.text))
        substantive.extend(self._attribution_diffs(original.text, revised.text))
        substantive.extend(self._hedge_diffs(original.text, revised.text))
        substantive.extend(self._causal_diffs(original.text, revised.text))

        style: list[MeaningDiff] = []
        style.extend(self._filler_and_transition_diffs(original.text, revised.text))
        style.extend(self._sentence_structure_diffs(original, revised))

        status: Status = "FLAGGED" if substantive else "PASS"
        return MeaningPreservationResult(
            status=status, diffs=substantive, style_diffs=style
        )

    @staticmethod
    def _number_diffs(
        original_text: str, revised_text: str
    ) -> list[MeaningDiff]:
        original_counts = Counter(_NUMBER.findall(original_text))
        revised_counts = Counter(_NUMBER.findall(revised_text))
        removed = original_counts - revised_counts
        added = revised_counts - original_counts

        diffs = []
        for number in removed:
            diffs.append(
                MeaningDiff(
                    "number_removed",
                    f'"{number}" appeared {original_counts[number]}x in the '
                    f"original vs {revised_counts[number]}x in the revision.",
                )
            )
        for number in added:
            diffs.append(
                MeaningDiff(
                    "number_added",
                    f'"{number}" appears {revised_counts[number]}x in the '
                    f"revision vs {original_counts[number]}x in the original.",
                )
            )
        return diffs

    @staticmethod
    def _attribution_diffs(
        original_text: str, revised_text: str
    ) -> list[MeaningDiff]:
        original_counts = _count_markers(
            original_text, _ATTRIBUTION_MARKERS
        )
        revised_counts = _count_markers(revised_text, _ATTRIBUTION_MARKERS)
        removed = original_counts - revised_counts
        return [
            MeaningDiff(
                "attribution_removed",
                f'Attribution phrase "{marker}" was dropped.',
            )
            for marker in removed
        ]

    @staticmethod
    def _hedge_diffs(
        original_text: str, revised_text: str
    ) -> list[MeaningDiff]:
        original_counts = _count_words(original_text, _HEDGE_WORDS)
        revised_counts = _count_words(revised_text, _HEDGE_WORDS)
        removed = original_counts - revised_counts
        added = revised_counts - original_counts

        diffs = []
        for word in removed:
            message = (
                f'Hedge word "{word}" was dropped -- claim may be stronger.'
            )
            diffs.append(MeaningDiff("hedge_removed", message))
        for word in added:
            message = (
                f'Hedge word "{word}" was added -- claim may be weaker.'
            )
            diffs.append(MeaningDiff("hedge_added", message))
        return diffs

    @staticmethod
    def _causal_diffs(
        original_text: str, revised_text: str
    ) -> list[MeaningDiff]:
        original_counts = _count_markers(original_text, _CAUSAL_MARKERS)
        revised_counts = _count_markers(revised_text, _CAUSAL_MARKERS)
        added = revised_counts - original_counts
        return [
            MeaningDiff(
                "causal_escalation",
                f'Causal language "{marker}" was added.',
            )
            for marker in added
        ]

    @staticmethod
    def _filler_and_transition_diffs(
        original_text: str, revised_text: str
    ) -> list[MeaningDiff]:
        original_counts = _count_markers(original_text, _FILLER_TRANSITION_PHRASES)
        revised_counts = _count_markers(revised_text, _FILLER_TRANSITION_PHRASES)
        removed = original_counts - revised_counts
        return [
            MeaningDiff(
                "filler_or_transition_removed",
                f'Filler/transition "{marker}" was removed.',
            )
            for marker in removed
        ]

    @staticmethod
    def _sentence_structure_diffs(
        original: Document, revised: Document
    ) -> list[MeaningDiff]:
        original_count = len(original.all_sentences())
        revised_count = len(revised.all_sentences())
        delta = abs(original_count - revised_count)

        original_words = _content_word_set(original.text)
        revised_words = _content_word_set(revised.text)
        same_content = original_words == revised_words

        if original_count == 0 or delta == 0:
            return []
        if not same_content and delta < _SENTENCE_COUNT_MIN_DELTA:
            return []
        if not same_content and delta / original_count < _SENTENCE_COUNT_RATIO_THRESHOLD:
            return []

        if revised_count > original_count:
            kind = "sentence_split"
            desc = f"One or more sentences were split ({original_count} -> {revised_count})."
        elif revised_count < original_count:
            kind = "sentence_combined"
            desc = f"Sentences were combined ({original_count} -> {revised_count})."
        else:
            return []

        return [MeaningDiff(kind, desc)]


def _content_word_set(text: str) -> set[str]:
    """Content words (lowercased, 3+ chars) used to compare propositions."""
    tokens = [t.lower() for t in _WORD.findall(text) if len(t) >= 3]
    # A small stop-word guard so purely stylistic words do not dominate.
    stop = {
        "the", "and", "but", "for", "with", "from", "into", "onto", "than",
        "that", "this", "these", "those", "they", "them", "their", "there",
    }
    return {t for t in tokens if t not in stop}


@dataclass
class SemanticMeaningResult(DataClassSerializationMixin):
    """Result of independent model-backed semantic meaning review."""

    verdict: SemanticVerdict = "PASS"
    differences: list[MeaningDiff] = field(default_factory=list)
    rationale: str = ""
    provider: str = ""
    model: str | None = None
    duration_seconds: float = 0.0
    independence_status: str = "INDEPENDENT"
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelMeaningReviewer(Protocol):
    """Protocol for semantic meaning review."""

    role: WritingRole

    def compare(
        self,
        original: Document,
        revised: Document,
        humanizer_provider: str | None = None,
    ) -> Any: ...


class NotConfiguredMeaningReviewer(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.FINAL_REVIEWER)

    def compare(
        self, original: Document, revised: Document
    ) -> Any:
        return self.run(original, revised)


MAX_SINGLE_PASS_CHARS = 100_000


class RealModelMeaningReviewer:
    """Real model-backed semantic meaning reviewer wired via HowlPlane."""

    role: WritingRole = WritingRole.FINAL_REVIEWER

    def compare(
        self,
        original: Document,
        revised: Document,
        humanizer_provider: str | None = None,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        run_id: str | None = None,
    ) -> SemanticMeaningResult:
        if (
            len(original.text) > MAX_SINGLE_PASS_CHARS
            or len(revised.text) > MAX_SINGLE_PASS_CHARS
        ):
            raise ValueError(
                f"Document size exceeds safe single-pass limit "
                f"({MAX_SINGLE_PASS_CHARS} chars) for semantic meaning review."
            )

        bridge = get_howlplane_bridge()

        prompt = f"""You are an independent Meaning Reviewer executing the FINAL_REVIEWER role.
Your mission is to compare the ORIGINAL text against the REVISED text and evaluate
whether factual meaning, intent, technical precision, or claims were altered.

EVALUATION CRITERIA (substantive changes only):
1. Changed meaning, thesis, or polarity (e.g. negative turned into positive)
2. Stronger or bolder claims than the original justified
3. Weaker claims or dropped core assertions
4. Removed qualifiers, hedges, or conditions (e.g. "may", "approximately", "likely")
5. Changed opinions or altered author stance
6. New factual assertions fabricated by the rewrite
7. Removed or altered technical details, software versions, IP addresses, or units
8. Altered numbers, statistics, percentages, currency, ranges, or dates
9. Removed or altered source attribution, quotes, or citations
10. Changed uncertainty levels or causation (e.g. correlation changed to causation)

BENIGN STYLE EDITS (do NOT return FAIL for these):
- Removing filler words such as "Furthermore", "Moreover", "In conclusion"
- Changing transition words ("However" -> "Yet")
- Adapting to conversational/social medium cadence (e.g. natural first/second
  person, compact paragraphs, standard hashtags) while preserving causal logic
- Splitting or combining sentences while the propositions remain the same
- Simplifying phrasing, removing redundancy, or varying rhythm
- Removing canned conclusions, viral hooks, or engagement bait

If a rewrite is only a benign style edit, return PASS (or PASS_WITH_WARNINGS
if you are uncertain but the risk looks remote). Use FAIL only when a
reasonably identifiable factual, semantic, or evidentiary discrepancy exists.
Use differences with severity "info" for benign style notes, "warning" for
uncertain or minor semantic risk, and "blocker" for definite substantive drift.

When describing a substantive difference, prefer these kinds:
MEANING_DRIFT, FACT_CHANGE, QUALIFIER_CHANGE, ATTRIBUTION_CHANGE,
BENIGN_STYLE_CHANGE, UNCERTAIN.

ORIGINAL TEXT:
```markdown
{original.text}
```

REVISED TEXT:
```markdown
{revised.text}
```

OUTPUT FORMAT:
Return a ```yaml code block containing:
```yaml
verdict: "PASS" # One of: "PASS", "PASS_WITH_WARNINGS", "FAIL"
differences:
  - kind: "<kind of difference, e.g. stronger_claim, altered_fact, dropped_qualifier, new_assertion>"
    description: "<detailed explanation of semantic shift>"
    severity: "blocker" # blocker | warning | info
rationale: "<summary explanation of verdict>"
```"""

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            context={
                "original_title": original.title,
                "revised_title": revised.title,
                "humanizer_provider": humanizer_provider,
                "run_id": run_id,
            },
            avoid_provider=humanizer_provider,
            timeout_seconds=300,
            cwd=cwd,
            custom_backend=custom_backend,
        )

        if not result.success:
            err = result.error_message or "Reviewer execution failed"
            return SemanticMeaningResult(
                verdict="FAIL",
                differences=[
                    MeaningDiff(
                        kind="reviewer_failure",
                        description=f"Meaning reviewer failed: {err}",
                    )
                ],
                rationale=f"Reviewer execution failed: {err}",
                provider=result.provider,
                model=result.model,
                duration_seconds=result.duration_seconds,
                independence_status=result.independence_status,
                metadata=result.metadata,
            )

        structured = result.structured_output or {}
        raw_verdict = str(structured.get("verdict") or "").upper().strip()
        if raw_verdict not in ("PASS", "PASS_WITH_WARNINGS", "FAIL"):
            if raw_verdict in ("FLAGGED", "WARNING"):
                verdict: SemanticVerdict = "PASS_WITH_WARNINGS"
            else:
                verdict = (
                    "PASS"
                    if not structured.get("differences")
                    else "PASS_WITH_WARNINGS"
                )
        else:
            verdict = raw_verdict  # type: ignore

        differences: list[MeaningDiff] = []
        raw_diffs = structured.get("differences", [])
        if isinstance(raw_diffs, list):
            for item in raw_diffs:
                if isinstance(item, dict):
                    kind = str(item.get("kind") or "semantic_shift")
                    desc = str(item.get("description") or item.get("claim") or "")
                    differences.append(MeaningDiff(kind=kind, description=desc))
                elif isinstance(item, str):
                    differences.append(MeaningDiff(kind="semantic_shift", description=item))

        rationale = str(structured.get("rationale") or "")

        return SemanticMeaningResult(
            verdict=verdict,
            differences=differences,
            rationale=rationale,
            provider=result.provider,
            model=result.model,
            duration_seconds=result.duration_seconds,
            independence_status=result.independence_status,
            metadata=result.metadata,
        )
