"""Account for every change between a document and its revision.

For each change: what changed, the checkable reason, whether meaning held,
whether a citation moved. A revision that changed nothing says so. The report
states only what can be established from the two texts. Where a reason or a voice
effect cannot be determined, it says "not determinable" instead of guessing, and
it attaches no scores that would imply more precision than exists.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
import re
from typing import Any

from howlwriter.academic.length import count_body_words
from howlwriter.citations.extract import extract_in_text_citations
from howlwriter.citations.revalidation import CitationChange, citation_delta, split_body_and_references
from howlwriter.domain.document import Document
from howlwriter.domain.sentences import split_sentences
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.review.leakage import detect_leakage
from howlwriter.review.meaning import MeaningPreservationReviewer

_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")
NOT_DETERMINABLE = "wording change; the reason cannot be determined from the text alone"


@dataclass
class Change(DataClassSerializationMixin):
    kind: str  # reworded | removed | added
    before: str
    after: str
    reasons: list[str] = field(default_factory=list)
    citation_effect: str = "none"  # none | citation changed | citation removed | citation added
    meaning: str = "PASS"  # PASS | FLAGGED
    meaning_notes: list[str] = field(default_factory=list)


@dataclass
class ChangeReport(DataClassSerializationMixin):
    changed: bool
    changes: list[Change] = field(default_factory=list)
    meaning_status: str = "PASS"
    citation_changes: list[CitationChange] = field(default_factory=list)
    word_count_before: int = 0
    word_count_after: int = 0
    requirements: list[str] = field(default_factory=list)  # human-readable pass/fail statements
    voice: dict[str, Any] = field(default_factory=lambda: {"status": "NOT_REQUESTED"})
    summary: str = ""


def _sentences(text: str) -> list[str]:
    body, _ = split_body_and_references(text)
    return split_sentences(body)


def _cite_keys(sentence: str) -> set[str]:
    return {f"{c.names} {c.year}" for c in extract_in_text_citations(sentence) if c.source_id is None}


def _reasons(before: str, after: str) -> list[str]:
    reasons: list[str] = []
    if before and after and _cite_keys(before) != _cite_keys(after):
        reasons.append("the citation changed")
    if _NUMBER.findall(before) != _NUMBER.findall(after) and before and after:
        reasons.append("a number changed")
    if before and detect_leakage(before) and not detect_leakage(after):
        reasons.append("workflow commentary was removed")
    if before and after and len(after.split()) < len(before.split()) * 0.8:
        reasons.append("the sentence was shortened")
    return reasons


def _citation_effect(before: str, after: str) -> str:
    b, a = _cite_keys(before), _cite_keys(after)
    if b == a:
        return "none"
    if b and not a:
        return "citation removed"
    if a and not b:
        return "citation added"
    return "citation changed"


def build_change_report(
    original_text: str,
    revised_text: str,
    *,
    min_words: int | None = None,
    max_words: int | None = None,
    identity: str | None = None,
    mode: str | None = None,
    identities_root: Any = None,
) -> ChangeReport:
    before, after = _sentences(original_text), _sentences(revised_text)
    wb, wa = count_body_words(original_text), count_body_words(revised_text)
    reviewer = MeaningPreservationReviewer()
    changes: list[Change] = []

    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old, new = " ".join(before[i1:i2]), " ".join(after[j1:j2])
        kind = "removed" if not new else "added" if not old else "reworded"
        pair = reviewer.compare(Document.parse(old or "x", title="a"), Document.parse(new or "x", title="b")) \
            if kind == "reworded" else None
        reasons = _reasons(old, new)
        if kind == "removed":
            reasons.append("the sentence was removed")
        elif kind == "added":
            reasons.append("a sentence was added")
        changes.append(Change(
            kind=kind, before=old, after=new, reasons=reasons or [NOT_DETERMINABLE],
            citation_effect=_citation_effect(old, new),
            meaning=pair.status if pair else ("FLAGGED" if kind != "reworded" else "PASS"),
            meaning_notes=[d.description for d in pair.diffs] if pair else
            (["content was removed"] if kind == "removed" else ["content was added"])))

    overall = reviewer.compare(Document.parse(original_text, title="original"),
                               Document.parse(revised_text, title="revised"))
    cdelta = citation_delta(original_text, revised_text)

    requirements = []
    if min_words is not None or max_words is not None:
        ok_b = (min_words is None or wb >= min_words) and (max_words is None or wb <= max_words)
        ok_a = (min_words is None or wa >= min_words) and (max_words is None or wa <= max_words)
        requirements.append(f"word count {wb} -> {wa}; within {min_words or 0}-{max_words or 'any'}: "
                            f"{'yes' if ok_b else 'no'} before, {'yes' if ok_a else 'no'} after")

    voice: dict[str, Any] = {"status": "NOT_REQUESTED"}
    if identity:
        voice = _voice_effect(original_text, revised_text, identity, mode, identities_root)

    changed = bool(changes) or original_text.strip() != revised_text.strip()
    summary = ("No changes." if not changed else
               f"{len(changes)} change(s); meaning {overall.status}; "
               f"{len([c for c in cdelta.changes if c.severity != 'info'])} citation change(s).")
    return ChangeReport(changed, changes, overall.status, cdelta.changes, wb, wa, requirements, voice, summary)


def _voice_effect(original: str, revised: str, identity: str, mode: str | None,
                  identities_root: Any = None) -> dict[str, Any]:
    """Whether the revision moved toward or away from the voice profile. Statuses only; scores
    appear only when both versions were scored."""
    try:
        from howlwriter.evaluation.personal import evaluate_text

        a = evaluate_text(split_body_and_references(original)[0], mode=mode or "academic", identity=identity,
                          identities_root=identities_root)
        b = evaluate_text(split_body_and_references(revised)[0], mode=mode or "academic", identity=identity,
                          identities_root=identities_root)
    except Exception as exc:
        return {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
    sa, sb = a["voice_match"].get("score"), b["voice_match"].get("score")
    if sa is None or sb is None:
        reason = b["voice_match"].get("reason") or a["voice_match"].get("reason") or "not scored"
        return {"status": "UNAVAILABLE", "reason": reason}
    delta = sb - sa
    # Small differences are measurement noise, not a finding.
    effect = "unchanged" if abs(delta) < 3 else "closer to the profile" if delta > 0 else "further from the profile"
    return {"status": "SCORED", "effect": effect, "before": sa, "after": sb}
