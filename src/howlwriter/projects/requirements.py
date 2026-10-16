"""The requirements ledger: what the task asks for, and whether it is met.

Requirements come only from material classified as assignment instructions
or a rubric (or added by the user), each with the exact location it was read
from. They are never evidence: an instruction that says "capture traffic
with TLS 1.3" proves nothing was captured.

Status rules:

* Experiments, screenshots, evidence and comparisons are satisfied only by
  *observation* evidence -- the user's own packet captures, screenshots,
  data and logs, or an observation recorded in a lab browser session --
  that matches the requirement. A reference document or a video describing
  the procedure never satisfies them.
* Sections, citations, formatting and deliverables are checked against a
  draft (see `validate.check_draft`); before a draft exists they are pending.
* A user's own status (for instance not_applicable, or satisfied after they
  inspected the evidence) is kept across rescans and wins.

Matching is lexical and deliberately conservative; every automatic link
names the shared terms that produced it, so the user can judge it.
"""

from __future__ import annotations

import hashlib
import re

from howlwriter.materials.convert import extract_requirement_lines
from howlwriter.projects import models as m
from howlwriter.projects.retrieval import terms
from howlwriter.projects.workspace import ProjectWorkspace

_KINDS = (
    ("screenshot", re.compile(r"screen ?shot|screen ?capture|snip|image of", re.I)),
    (
        "comparison",
        re.compile(r"\bcompar|\bversus\b|\bvs\.?\b|\bdifference|\bcontrast|before and after", re.I),
    ),
    (
        "experiment",
        re.compile(
            r"\b(run|perform|execute|configure|capture|replay|generate|test|launch|start|enable|"
            r"create a rule|"
            r"write a rule|install|deploy|observe)\b",
            re.I,
        ),
    ),
    (
        "citation",
        re.compile(r"\bcit(e|ation)|\breferences?\b|\bAPA\b|\bMLA\b|\bsources?\b|bibliograph", re.I),
    ),
    (
        "formatting",
        re.compile(r"\bfont\b|double[- ]spaced|\bmargins?\b|\bword count\b|\bpages? long\b|\bformat", re.I),
    ),
    ("deliverable", re.compile(r"\bsubmit|\bupload|\bturn in\b|\.docx|\.pdf|\bdeliverable", re.I)),
    (
        "section",
        re.compile(r"\bsection\b|\bintroduction\b|\bconclusion\b|\bsummary\b|\breflection\b|\bdiscuss", re.I),
    ),
    (
        "evidence",
        re.compile(
            r"\bshow\b|\bprovide\b|\binclude\b|\bevidence\b|\boutput\b|\bresults?\b|\balerts?\b", re.I
        ),
    ),
)
OBSERVATION_KINDS = ("experiment", "screenshot", "comparison", "evidence")
DRAFT_KINDS = ("section", "citation", "formatting", "deliverable", "question")
MIN_SHARED_TERMS = 2
MIN_SHARE = 0.3
#: Imperative openers that state a task even without "must" or a bullet.
_IMPERATIVE = re.compile(
    r"^(?:\d{1,2}[.)]\s*)?(include|cite|submit|capture|take|compare|describe|explain|discuss|provide|"
    r"write|run|create|configure|answer|document|record|list|identify|analy[sz]e|upload|use|ensure|show|"
    r"report|summari[sz]e|evaluate|demonstrate|attach|reflect|perform|generate|replay|observe|test|install|"
    r"enable|disable|deploy)\b",
    re.I,
)
#: Which observation evidence can prove which kind of requirement.
PROOF_CATEGORIES = {
    "screenshot": (m.SCREENSHOT,),
    "experiment": m.OBSERVATION_CATEGORIES,
    "evidence": m.OBSERVATION_CATEGORIES,
    "comparison": m.OBSERVATION_CATEGORIES,
}


def requirement_lines(text: str) -> list[str]:
    """Obligation lines (bullets, modal verbs) plus imperative sentences, in order."""
    found = extract_requirement_lines(text)
    seen = {line.lower() for line in found}
    for raw in text.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", raw.strip()):
            sentence = " ".join(sentence.split())
            if (
                12 <= len(sentence) <= 400
                and len(sentence.split()) >= 4
                and _IMPERATIVE.match(sentence)
                and sentence.lower() not in seen
            ):
                seen.add(sentence.lower())
                found.append(re.sub(r"^\d{1,2}[.)]\s*", "", sentence))
    return found


def requirement_kind(text: str) -> str:
    if text.rstrip().endswith("?"):
        return "question"
    for kind, pattern in _KINDS:
        if pattern.search(text):
            return kind
    return "other"


def _rid(source_id: str, text: str) -> str:
    return "req-" + hashlib.sha256(f"{source_id}|{text.lower()}".encode("utf-8")).hexdigest()[:10]


def is_observation(item: m.EvidenceItem) -> bool:
    """Evidence that records what happened, as opposed to what should happen."""
    if item.source_type == "browser":
        return item.observation.get("mode") in ("observe", "interactive")
    return item.category in m.OBSERVATION_CATEGORIES


def can_prove(kind: str, item: m.EvidenceItem) -> bool:
    if not is_observation(item):
        return False
    if kind == "screenshot":
        return item.category == m.SCREENSHOT or item.kind == "screenshot"
    return True


def extract(workspace: ProjectWorkspace, *, sources=None, evidence=None) -> dict[str, m.Requirement]:
    sources = sources if sources is not None else workspace.load_sources()
    evidence = evidence if evidence is not None else workspace.load_evidence()
    found: dict[str, m.Requirement] = {}
    for item in sorted(evidence.values(), key=lambda e: (e.source_path, str(e.locator))):
        record = sources.get(item.source_id)
        if record is None or not record.present or record.category not in m.REQUIREMENT_CATEGORIES:
            continue
        text = (
            item.observation.get("text")
            or "\n".join(
                line.get("text", "")
                for line in item.observation.get("lines", [])
                if not line.get("uncertain")
            )
            or item.excerpt
        )
        for line in requirement_lines(text):
            rid = _rid(item.source_id, line)
            if rid not in found:
                found[rid] = m.Requirement(
                    requirement_id=rid,
                    text=line,
                    kind=requirement_kind(line),
                    source_id=item.source_id,
                    location=item.citation,
                )
    return found


def assess(requirement: m.Requirement, evidence: dict[str, m.EvidenceItem]) -> None:
    if requirement.user_status:
        requirement.status = requirement.user_status
        requirement.status_reason = (
            f"set by the user{': ' + requirement.user_note if requirement.user_note else ''}"
        )
        return
    if requirement.kind == "question":
        _support(requirement, evidence)
        return
    if requirement.kind in DRAFT_KINDS or requirement.kind == "other":
        requirement.status = m.PENDING
        requirement.status_reason = "checked against a draft by `project validate`"
        requirement.evidence_ids = []
        return
    wanted = set(terms(requirement.text))
    if not wanted:
        requirement.status, requirement.status_reason = m.PENDING, "no checkable terms"
        return
    matches = []
    for item in evidence.values():
        if not can_prove(requirement.kind, item):
            continue
        have = set(
            terms(" ".join([item.excerpt, item.location, item.source_path, _flatten(item.observation)]))
        )
        shared = wanted & have
        if len(shared) >= MIN_SHARED_TERMS:
            matches.append((len(shared) / len(wanted), sorted(shared), item.evidence_id))
    matches.sort(reverse=True)
    strong = [x for x in matches if x[0] >= MIN_SHARE]
    if requirement.kind == "comparison" and len({evidence[x[2]].source_id for x in strong}) < 2:
        # A comparison needs observations from at least two sources.
        matches, strong = (strong or matches), []
    if strong:
        requirement.status = m.SATISFIED
        requirement.evidence_ids = [x[2] for x in strong[:8]]
        requirement.status_reason = (
            f"automatic match to {len(strong)} observation(s) on: {', '.join(strong[0][1][:8])}; "
            "review the linked evidence"
        )
    elif matches:
        requirement.status = m.PARTIAL
        requirement.evidence_ids = [x[2] for x in matches[:5]]
        requirement.status_reason = f"weak match on: {', '.join(matches[0][1][:6])}"
    else:
        requirement.status = m.PENDING
        requirement.evidence_ids = []
        requirement.status_reason = (
            "no observation evidence (capture, screenshot, data, or lab observation) found"
        )


def _support(requirement: m.Requirement, evidence: dict[str, m.EvidenceItem]) -> None:
    """A question is answered in the draft; observations that bear on it are linked as support."""
    wanted = set(terms(requirement.text))
    scored = []
    for item in evidence.values():
        if not is_observation(item):
            continue
        have = set(terms(" ".join([item.excerpt, item.source_path, _flatten(item.observation)])))
        shared = wanted & have
        if len(shared) >= MIN_SHARED_TERMS:
            scored.append((len(shared) / max(1, len(wanted)), item.evidence_id))
    scored.sort(reverse=True)
    requirement.evidence_ids = [eid for _, eid in scored[:5]]
    requirement.status = m.PENDING
    requirement.status_reason = (
        f"answer it in the draft; {len(scored)} observation(s) may support the answer"
        if scored
        else "answer it in the draft; no observation found that bears on it"
    )


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(
            f"{k} {_flatten(v)}" for k, v in value.items() if k not in ("lines", "segments", "box")
        )
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value[:50])
    return str(value)


def refresh_requirements(
    workspace: ProjectWorkspace, *, sources=None, evidence=None
) -> dict[str, m.Requirement]:
    """Re-extract, keep user additions and user statuses, and re-assess."""
    evidence = evidence if evidence is not None else workspace.load_evidence()
    previous = workspace.load_requirements()
    current = extract(workspace, sources=sources, evidence=evidence)
    for rid, old in previous.items():
        if old.source_id == "user":
            current[rid] = old
        elif rid in current:
            current[rid].user_status, current[rid].user_note = old.user_status, old.user_note
    for requirement in current.values():
        assess(requirement, evidence)
    workspace.save_requirements(current)
    return current


def add_requirement(workspace: ProjectWorkspace, text: str, kind: str | None = None) -> m.Requirement:
    requirements = workspace.load_requirements()
    requirement = m.Requirement(
        requirement_id=_rid("user", text),
        text=text.strip(),
        kind=kind or requirement_kind(text),
        source_id="user",
        location="added by the user",
    )
    requirements[requirement.requirement_id] = requirement
    workspace.save_requirements(requirements)
    return refresh_requirements(workspace)[requirement.requirement_id]


def set_status(
    workspace: ProjectWorkspace, requirement_id: str, status: str, note: str = ""
) -> m.Requirement:
    allowed = (m.SATISFIED, m.PARTIAL, m.PENDING, m.BLOCKED, m.NOT_APPLICABLE, "")
    if status not in allowed:
        raise ValueError(f"status must be one of {', '.join(s for s in allowed if s)} (or empty to clear)")
    requirements = workspace.load_requirements()
    if requirement_id not in requirements:
        raise ValueError(f"no requirement {requirement_id!r}")
    requirements[requirement_id].user_status = status
    requirements[requirement_id].user_note = note
    workspace.save_requirements(requirements)
    return refresh_requirements(workspace)[requirement_id]
