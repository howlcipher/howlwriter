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
from howlwriter.domain.generation_provenance import ReviewerFallbackRecord
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
    # Negated and adjacent hedges. "unlikely" is a distinct token from
    # "likely", so without listing it a rewrite from a categorical claim to
    # "unlikely to" changed the claim invisibly.
    "unlikely", "unclear", "uncertain", "potentially", "presumably",
    "apparently", "seems", "arguably", "generally", "typically",
    "approximately", "roughly", "somewhat", "occasionally",
)
# Negation carries the polarity of a claim. Dropping or adding one inverts what
# the sentence asserts, which is the most damaging meaning change a rewrite can
# make and the one a word-frequency check would otherwise miss entirely.
_NEGATION_MARKERS = frozenset({
    "not", "no", "never", "cannot", "cant", "dont", "doesnt", "didnt",
    "isnt", "arent", "wasnt", "werent", "wont", "nor", "neither",
    "none", "without", "unable", "lacks", "lacking",
})
# Curly apostrophes are folded onto the ASCII one so "doesn't" and "doesn’t"
# are the same word; without this a typographic substitution alone read as a
# dropped negation.
_APOSTROPHES = ("\u2019", "\u2018", "\u02bc")
# How many content words after a negation are taken as what it negates.
_POLARITY_SCOPE_WORDS = 3
# Shared negated words above which a removal and an addition are read as
# one negation reworded rather than two polarity changes.
_POLARITY_REPHRASE_OVERLAP = 2
_SCOPE_STOPWORDS = frozenset({
    "a", "an", "the", "to", "of", "in", "it", "its", "is", "are", "was",
    "were", "be", "been", "being", "that", "this", "these", "those", "and",
    "or", "for", "as", "at", "by", "on", "with", "from", "does", "do", "did",
    "has", "have", "had", "any", "all", "will", "would", "can", "could",
})
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


def _shared_scope_words(left: str, right: str) -> int:
    """How many negated content words two scopes have in common."""
    return len(set(left.split()) & set(right.split()))


def _negation_scopes(text: str) -> Counter:
    """What each negation in the passage negates.

    Comparing scopes rather than counts is deliberate. A total count cancels
    out -- moving a negation from one sentence to another leaves the count
    unchanged while inverting both sentences -- and comparing negation words
    individually reports a difference every time a rewrite swaps synonyms.
    The words a negation governs are what actually carries the claim, so
    "lacks textual support" and "without textual support" agree, while
    "does not block SSH" and "does not block HTTP" do not.
    """
    lowered = text.lower()
    for apostrophe in _APOSTROPHES:
        lowered = lowered.replace(apostrophe, "'")
    tokens = [t.replace("'", "") for t in _WORD.findall(lowered)]

    scopes: Counter = Counter()
    for index, token in enumerate(tokens):
        if token not in _NEGATION_MARKERS:
            continue
        scope: list[str] = []
        for following in tokens[index + 1:]:
            if following in _SCOPE_STOPWORDS or following in _NEGATION_MARKERS:
                continue
            scope.append(following)
            if len(scope) == _POLARITY_SCOPE_WORDS:
                break
        scopes[" ".join(scope)] += 1
    return scopes


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
        substantive.extend(self._polarity_diffs(original.text, revised.text))

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
    def _polarity_diffs(
        original_text: str, revised_text: str
    ) -> list[MeaningDiff]:
        """Flag negations that appeared or disappeared during a rewrite.

        A dropped negation turns "does not permit arbitrary code execution"
        into "permits arbitrary code execution". Counting negation markers on
        both sides catches that inversion without needing to parse the
        sentence.
        """
        original_scopes = _negation_scopes(original_text)
        revised_scopes = _negation_scopes(revised_text)
        removed = list((original_scopes - revised_scopes).elements())
        added = list((revised_scopes - original_scopes).elements())

        # A removal and an addition that still share most of the negated words
        # are one negation reworded, not a polarity change: "not considered a
        # valid source" and "not treated as a valid source" negate the same
        # proposition. Pair those off so only genuinely different negations are
        # reported. Requiring a majority of the words to survive keeps real
        # inversions ("not block SSH" vs "not block HTTP", which share only
        # one) out of the pairing.
        rephrased: list[tuple[str, str]] = []
        for old_scope in list(removed):
            match = next(
                (
                    new_scope
                    for new_scope in added
                    if _shared_scope_words(old_scope, new_scope)
                    >= _POLARITY_REPHRASE_OVERLAP
                ),
                None,
            )
            if match is not None:
                removed.remove(old_scope)
                added.remove(match)
                rephrased.append((old_scope, match))

        diffs = []
        for scope in removed:
            diffs.append(
                MeaningDiff(
                    "negation_removed",
                    f'The negation of "{scope}" was dropped -- the revision '
                    "may assert the opposite of the original.",
                )
            )
        for scope in added:
            diffs.append(
                MeaningDiff(
                    "negation_added",
                    f'A negation of "{scope}" was added -- the revision may '
                    "deny something the original asserted.",
                )
            )
        for old_scope, new_scope in rephrased:
            diffs.append(
                MeaningDiff(
                    "negation_rephrased",
                    f'A negation was reworded from "{old_scope}" to '
                    f'"{new_scope}" -- confirm the claim still holds.',
                )
            )
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
    fallback_record: ReviewerFallbackRecord | None = None


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
        fallback_backend: Any | None = None,
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
- Did the rewrite introduce any factual claim not present in the original?
- Did it drop an important qualifier, constraint, or condition?
- Did it alter numbers, metrics, or technical specifics?
- Did it change who or what is attributed as the source of a claim?
- Did it invert or weaken a causal relationship (e.g. "X causes Y" -> "X is correlated with Y")?

BENIGN CADENCE REWRITES (MUST BE TOLERATED):
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

        fallback_rec: ReviewerFallbackRecord | None = None
        if not result.success and fallback_backend:
            primary_err = result.error_message or "Reviewer execution failed"
            primary_backend_name = str(custom_backend or self.role.value)
            fb_res = bridge.execute_writing_role(
                role=self.role,
                prompt=prompt,
                context={
                    "original_title": original.title,
                    "revised_title": revised.title,
                    "humanizer_provider": humanizer_provider,
                    "run_id": run_id,
                },
                avoid_provider=None,
                timeout_seconds=300,
                cwd=cwd,
                custom_backend=fallback_backend,
            )
            if fb_res.success:
                result = fb_res
                indep = (
                    "SAME_PROVIDER"
                    if (humanizer_provider and fb_res.provider == humanizer_provider)
                    else "INDEPENDENT"
                )
                result.independence_status = indep
                fallback_rec = ReviewerFallbackRecord(
                    stage="meaning_review",
                    requested_reviewer=primary_backend_name,
                    failure_reason=primary_err,
                    fallback_reviewer=str(fallback_backend),
                    provider=fb_res.provider,
                    model=fb_res.model,
                    independence_status=indep,
                )
        elif (
            not result.success
            and humanizer_provider
            and (
                "avoiding" in (result.error_message or "")
                or "No executor or provider configured" in (result.error_message or "")
            )
        ):
            # Fallback to executing with the available provider, honestly recording SAME_PROVIDER independence
            fallback_res = bridge.execute_writing_role(
                role=self.role,
                prompt=prompt,
                context={
                    "original_title": original.title,
                    "revised_title": revised.title,
                    "humanizer_provider": humanizer_provider,
                    "run_id": run_id,
                },
                avoid_provider=None,
                timeout_seconds=300,
                cwd=cwd,
                custom_backend=custom_backend,
            )
            if fallback_res.success:
                result = fallback_res
                result.independence_status = "SAME_PROVIDER"
                fallback_rec = ReviewerFallbackRecord(
                    stage="meaning_review",
                    requested_reviewer=str(custom_backend or self.role.value),
                    failure_reason="No independent reviewer available",
                    fallback_reviewer=str(custom_backend or self.role.value),
                    provider=fallback_res.provider,
                    model=fallback_res.model,
                    independence_status="SAME_PROVIDER",
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
                fallback_record=fallback_rec,
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
            fallback_record=fallback_rec,
        )
