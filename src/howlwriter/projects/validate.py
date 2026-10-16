"""Check a draft against the evidence library and the requirements ledger.

Citations in a project draft are evidence markers: ``[ev-1a2b3c4d5e6f]``.
Each one names a specific extracted item, so every check below is
mechanical:

* **fabricated citation** -- a marker that names no evidence in the library;
* **unsupported claim** -- a sentence that states a number, a protocol
  value, or an observed result without any marker;
* **number not in evidence** -- a cited sentence whose numbers appear in
  none of the evidence it cites;
* **instruction cited as observation** -- a sentence that reports something
  happening ("generated", "captured", "fired", "showed") but whose only
  support is assignment instructions or a reference explaining a procedure;
* **tentative stated as fact** -- support that is only a tentative
  inference, with no hedge in the sentence;
* **contradicted** -- support marked contradicted;
* **missing placeholders** -- ``[MISSING: ...]`` markers the writer left
  where required evidence does not exist (counted, never filled in).

Then the requirements coverage check: every requirement's status, with
section, citation, and deliverable requirements checked against the draft.
"""

from __future__ import annotations

import re

from howlwriter.projects import models as m
from howlwriter.projects.requirements import is_observation, refresh_requirements
from howlwriter.projects.retrieval import terms
from howlwriter.projects.workspace import ProjectWorkspace

MARKER = re.compile(r"\[(ev-[0-9a-f]{12})\]")
MISSING = re.compile(r"\[MISSING:\s*([^\]]+)\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(\"'])")
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*%?)(?![\w])")
_OBSERVED = re.compile(
    r"\b(generated|captured|observed|fired|triggered|alerted|showed|shows|detected|recorded|returned|"
    r"produced|logged|measured|negotiated|saw|was seen|were seen|appeared|dropped|blocked)\b",
    re.I,
)
_TECHNICAL = re.compile(r"\b(TLS|SSL|SNI|DNS|HTTP|TCP|UDP|alert|sid|frame|packet|cipher|certificate)\b", re.I)
_HEDGE = re.compile(
    r"\b(may|might|could|likely|possibly|appears to|suggests?|probably|perhaps|tentative)\b", re.I
)


def sentences(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block or block.startswith("#") or block.startswith("|"):
            continue
        out += [s.strip() for s in _SENTENCE.split(block.replace("\n", " ")) if s.strip()]
    return out


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("%").rstrip(".") for n in _NUMBER.findall(text)}


def _evidence_text(item: m.EvidenceItem) -> str:
    return " ".join([item.excerpt, item.location, str(item.observation)[:20000]])


def check_draft(workspace: ProjectWorkspace, text: str) -> dict:
    evidence = workspace.load_evidence()
    issues: list[dict] = []
    cited: set[str] = set()
    claim_sentences = 0
    for sentence in sentences(text):
        markers = MARKER.findall(sentence)
        bare = MARKER.sub("", MISSING.sub("", sentence))
        cited |= set(markers)
        unknown = [mk for mk in markers if mk not in evidence]
        for mk in unknown:
            issues.append({"type": "fabricated_citation", "sentence": sentence[:300], "marker": mk})
        known = [evidence[mk] for mk in markers if mk in evidence]
        numbers = _numbers(bare)
        factual = bool(numbers) or bool(_OBSERVED.search(bare)) or bool(_TECHNICAL.search(bare))
        if factual:
            claim_sentences += 1
        if not markers:
            if factual and not MISSING.search(sentence) and not _HEDGE.search(bare):
                issues.append({"type": "unsupported_claim", "sentence": sentence[:300]})
            continue
        if not known:
            continue
        if numbers:
            have: set[str] = set()
            for item in known:
                have |= _numbers(_evidence_text(item))
            absent = sorted(n for n in numbers if n not in have)
            if absent:
                issues.append(
                    {
                        "type": "number_not_in_evidence",
                        "sentence": sentence[:300],
                        "numbers": absent,
                        "cited": [i.evidence_id for i in known],
                    }
                )
        if _OBSERVED.search(bare) and not any(is_observation(i) or i.category == m.MULTIMEDIA for i in known):
            if all(i.category in m.REQUIREMENT_CATEGORIES or i.category == m.REFERENCE for i in known):
                issues.append(
                    {
                        "type": "instruction_cited_as_observation",
                        "sentence": sentence[:300],
                        "cited": [i.citation for i in known],
                    }
                )
        if all(i.status == m.INFERENCE for i in known) and not _HEDGE.search(bare):
            issues.append({"type": "tentative_stated_as_fact", "sentence": sentence[:300]})
        if any(i.status == m.CONTRADICTED for i in known):
            issues.append({"type": "contradicted_support", "sentence": sentence[:300]})
    missing = [x.strip() for x in MISSING.findall(text)]
    coverage = coverage_check(workspace, text)
    blocking = [
        i
        for i in issues
        if i["type"]
        in (
            "fabricated_citation",
            "number_not_in_evidence",
            "instruction_cited_as_observation",
            "contradicted_support",
        )
    ]
    result = {
        "sentences_with_claims": claim_sentences,
        "citations": len(cited),
        "issues": issues,
        "issue_counts": _count(issues),
        "missing_placeholders": missing,
        "requirements": coverage,
        "verdict": (
            "BLOCKED"
            if blocking
            else (
                "INCOMPLETE"
                if missing or coverage["unmet"]
                else "REVIEW" if issues else "READY_FOR_HUMAN_REVIEW"
            )
        ),
    }
    workspace.save_validation(result)
    return result


def _count(issues: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for issue in issues:
        out[issue["type"]] = out.get(issue["type"], 0) + 1
    return out


def coverage_check(workspace: ProjectWorkspace, text: str | None = None) -> dict:
    """Every requirement's status; with a draft, section/citation/deliverable checks too."""
    requirements = refresh_requirements(workspace)
    headings = [h.lower() for h in re.findall(r"^#{1,6}\s+(.+)$", text or "", re.M)]
    draft_terms = set(terms(text or ""))
    rows = []
    for requirement in requirements.values():
        status, reason = requirement.status, requirement.status_reason
        if (
            text is not None
            and not requirement.user_status
            and requirement.kind in ("section", "citation", "formatting", "deliverable", "other")
        ):
            wanted = set(terms(requirement.text))
            if requirement.kind == "citation":
                ok = bool(MARKER.search(text)) or bool(re.search(r"^#+\s*references", text, re.I | re.M))
                status = m.SATISFIED if ok else m.PENDING
                reason = "draft cites evidence" if ok else "draft has no citations"
            elif requirement.kind == "section":
                in_heading = any(len(wanted & set(terms(h))) >= max(1, min(2, len(wanted))) for h in headings)
                shared = wanted & draft_terms
                status = (
                    m.SATISFIED
                    if in_heading
                    else m.PARTIAL if len(shared) >= max(2, len(wanted) // 2) else m.PENDING
                )
                reason = (
                    "a heading covers it"
                    if in_heading
                    else (
                        f"terms present but no heading ({', '.join(sorted(shared)[:5])})"
                        if status == m.PARTIAL
                        else "not addressed in the draft"
                    )
                )
            else:
                status = m.PENDING
                reason = "needs human check (formatting and submission are not verified automatically)"
        rows.append(
            {
                "requirement_id": requirement.requirement_id,
                "kind": requirement.kind,
                "text": requirement.text,
                "location": requirement.location,
                "status": status,
                "reason": reason,
                "evidence_ids": requirement.evidence_ids,
            }
        )
    unmet = [r for r in rows if r["status"] in (m.PENDING, m.BLOCKED, m.PARTIAL)]
    return {
        "total": len(rows),
        "unmet": len(unmet),
        "rows": rows,
        "by_status": {
            s: sum(1 for r in rows if r["status"] == s) for s in sorted({r["status"] for r in rows})
        },
    }
