"""Readiness of a whole submission package, not of single files.

Each file can pass its own length and citation checks while the assignment is
unfinished: a deliverable missing, a reply nobody can check against the post it
answers, a citation whose metadata could not be verified. This module evaluates
the deliverables together against one specification and reports one truthful
state.

States, most serious first:

  BLOCKED                   something must not be submitted as it stands: a
                            citation that contradicts authoritative metadata,
                            an in-text citation with no source, a reply that
                            misstates the post it answers.
  INCOMPLETE                a required deliverable, or the evidence needed to
                            check one (the post a reply answers), is missing.
  NEEDS_REVISION            a check found something to fix: length, topic
                            coverage, genre conventions, leaked workflow
                            commentary, partial grounding, a reference list that
                            disagrees with the citations.
  VERIFICATION_UNAVAILABLE  a required check could not complete (a metadata
                            provider was unreachable, a required voice score
                            cannot be computed). Absence of evidence, not a
                            pass.
  READY_FOR_HUMAN_REVIEW    every required check ran and passed. It is never
                            "submitted" or "approved": a person still reads it.

A rendered or exported document is not evidence of any of this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
from pathlib import Path
import re
from typing import Any

import yaml

from howlwriter.academic.citations import AcademicCitationManager
from howlwriter.academic.length import count_body_words
from howlwriter.citations.apa7 import APA7Formatter
from howlwriter.citations.registry import build_registry
from howlwriter.citations.verification import (
    CitationState,
    CitationVerification,
    RecordProvider,
    verify_sources,
)
from howlwriter.domain.document import Document
from howlwriter.domain.genres import AcademicGenre, check_genre_conformance, parse_genre
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source, source_from_dict
from howlwriter.replies.grounding import GroundingState, SourcePost, check_reply
from howlwriter.review.leakage import detect_leakage
from howlwriter.review.evidence import (
    DETERMINISTIC,
    EXTERNAL_RECORD,
    FAIL,
    NEEDS_REVIEW,
    PASS,
    UNAVAILABLE,
    VerificationRecord,
    semantic_review_record,
)
from howlwriter.review.meaning import MeaningPreservationReviewer


class PackageState(str, enum.Enum):
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"


# Severity of the finding, which decides the state.
LEVEL_BLOCKED = "blocked"
LEVEL_INCOMPLETE = "incomplete"
LEVEL_REVISE = "revise"
LEVEL_UNAVAILABLE = "unavailable"
LEVEL_INFO = "info"

_PRECEDENCE = [
    (LEVEL_BLOCKED, PackageState.BLOCKED),
    (LEVEL_INCOMPLETE, PackageState.INCOMPLETE),
    (LEVEL_REVISE, PackageState.NEEDS_REVISION),
    (LEVEL_UNAVAILABLE, PackageState.VERIFICATION_UNAVAILABLE),
]

_ROLE_GENRE = {
    "discussion": AcademicGenre.DISCUSSION,
    "peer_reply": AcademicGenre.PEER_REPLY,
    "paper": AcademicGenre.RESEARCH_PAPER,
}


@dataclass
class PackageFinding(DataClassSerializationMixin):
    level: str
    code: str
    message: str
    deliverable: str = ""


@dataclass
class DeliverableReport(DataClassSerializationMixin):
    id: str
    role: str
    path: str
    state: PackageState
    word_count: int | None = None
    findings: list[PackageFinding] = field(default_factory=list)
    scores: dict[str, Any] = field(default_factory=dict)


@dataclass
class PackageReport(DataClassSerializationMixin):
    title: str
    state: PackageState
    deliverables: list[DeliverableReport] = field(default_factory=list)
    package_findings: list[PackageFinding] = field(default_factory=list)
    unavailable_checks: list[str] = field(default_factory=list)
    human_decisions: list[str] = field(default_factory=list)
    citation_verification: list[dict[str, Any]] = field(default_factory=list)
    # What was actually checked, by which component, on what evidence (see review/evidence.py).
    verification_records: list[VerificationRecord] = field(default_factory=list)


def _state_for(findings: list[PackageFinding]) -> PackageState:
    levels = {f.level for f in findings}
    for level, state in _PRECEDENCE:
        if level in levels:
            return state
    return PackageState.READY_FOR_HUMAN_REVIEW


def load_package_spec(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("deliverables"), list) or not raw["deliverables"]:
        raise ValueError("package spec needs a non-empty 'deliverables' list")
    raw["_base"] = str(spec_path.resolve().parent)
    return raw


def _resolve(base: str, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else Path(base) / p


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _reference_lines(text: str) -> list[str]:
    m = re.search(r"(?:^|\n)(?:#{1,3}\s*|\*\*\s*)(?:References|Bibliography)(?:\s*\*\*)?\s*\n", text, re.I)
    if not m:
        return []
    return [ln.strip() for ln in text[m.end():].split("\n") if ln.strip()]


def _check_references(text: str, sources: list[Source], deliverable: str) -> list[PackageFinding]:
    """In-text citations resolve, and the reference list matches what is cited."""
    findings: list[PackageFinding] = []
    analysis = AcademicCitationManager().analyze_and_build_references(Document.parse(text, title=deliverable), sources)
    for raw in analysis.unmatched_in_text_citations:
        findings.append(PackageFinding(
            LEVEL_BLOCKED, "CITATION_UNRESOLVED",
            f"In-text citation “{raw}” matches no supplied source.", deliverable))
    lines = [_norm(ln) for ln in _reference_lines(text)]
    formatter = APA7Formatter()
    cited_keys: list[str] = []
    for source in analysis.used_sources:
        entry = _norm(formatter.reference_entry(source).text)
        key = " ".join(entry.split()[:8])  # authors and year lead the entry
        cited_keys.append(key)
        if lines and not any(ln.startswith(key) or key in ln for ln in lines):
            findings.append(PackageFinding(
                LEVEL_REVISE, "REFERENCE_MISSING_OR_DIFFERENT",
                f"The reference list has no entry matching '{source.title[:50]}' as the source metadata "
                "formats it.", deliverable))
        if not lines:
            findings.append(PackageFinding(LEVEL_REVISE, "REFERENCE_LIST_MISSING",
                                           "The text cites sources but has no reference list.", deliverable))
            break
    for ln in lines:
        if cited_keys and not any(ln.startswith(k) or k in ln for k in cited_keys):
            findings.append(PackageFinding(
                LEVEL_REVISE, "REFERENCE_NOT_CITED",
                f"Reference entry '{ln[:60]}' matches no cited source.", deliverable))
    return findings


def _topic_findings(body: str, topics: list[Any], deliverable: str) -> list[PackageFinding]:
    findings: list[PackageFinding] = []
    haystack = _norm(body)
    for topic in topics or []:
        name = topic.get("name", "") if isinstance(topic, dict) else str(topic)
        phrases = topic.get("any_of", [name]) if isinstance(topic, dict) else [str(topic)]
        if not any(_norm(p) in haystack for p in phrases if p):
            findings.append(PackageFinding(
                LEVEL_REVISE, "TOPIC_NOT_COVERED",
                f"Required topic not found: {name} (looked for: {', '.join(map(str, phrases))}).", deliverable))
    return findings


def _evaluate_voice(body: str, role_genre: AcademicGenre | None, identity: str | None) -> dict[str, Any]:
    if not identity:
        return {"status": "NOT_REQUESTED"}
    try:
        from howlwriter.evaluation.personal import evaluate_text

        result = evaluate_text(body, mode=(role_genre.value if role_genre else "academic"), identity=identity)
    except Exception as exc:  # no identity store, unreadable profile: unavailable, never a pass
        return {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "naturalness_status": result["naturalness"].get("status"),
        "naturalness_score": result["naturalness"].get("score"),
        "naturalness_reason": result["naturalness"].get("reason", ""),
        "voice_match_status": result["voice_match"].get("status"),
        "voice_match_score": result["voice_match"].get("score"),
        "voice_match_reason": result["voice_match"].get("reason", ""),
        "profile": result["profile_selection"].get("voice"),
    }


def _record(records: list[VerificationRecord], scope: str, check: str, component: str, findings: list[PackageFinding],
            codes: tuple[str, ...], evidence: str, limitations: list[str] | None = None, method: str = DETERMINISTIC) -> None:
    hit = [f for f in findings if f.code.startswith(codes)]
    records.append(VerificationRecord(
        check, component, method, FAIL if hit else PASS, scope=scope,
        evidence=("; ".join(f.message[:90] for f in hit[:2]) if hit else evidence), limitations=limitations or []))


def check_package(
    spec: dict[str, Any],
    *,
    providers: list[RecordProvider] | None = None,
) -> PackageReport:
    """Evaluate a package spec (see load_package_spec) and return one truthful report."""
    base = spec.get("_base", ".")
    title = spec.get("title", "assignment")
    package_findings: list[PackageFinding] = []
    human: list[str] = []
    unavailable: list[str] = []
    records: list[VerificationRecord] = []

    sources: list[Source] = []
    if spec.get("sources"):
        import json

        raw = json.loads(_resolve(base, spec["sources"]).read_text(encoding="utf-8"))
        sources = [source_from_dict(e) for e in (raw["sources"] if isinstance(raw, dict) else raw)]
    require_citations = bool(spec.get("require_citation_verification", bool(sources)))

    entries = spec["deliverables"]
    reports: list[DeliverableReport] = []
    texts: dict[str, str] = {}
    cited_sources: dict[str, Source] = {}

    for index, entry in enumerate(entries, 1):
        did = entry.get("id") or f"deliverable-{index}"
        role = entry.get("role", "discussion")
        genre = _ROLE_GENRE.get(role) or parse_genre(role)
        path = _resolve(base, entry["path"]) if entry.get("path") else None
        findings: list[PackageFinding] = []
        report = DeliverableReport(did, role, str(path or ""), PackageState.INCOMPLETE)
        reports.append(report)

        if path is None or not path.is_file():
            findings.append(PackageFinding(LEVEL_INCOMPLETE, "DELIVERABLE_MISSING",
                                           f"Required deliverable '{did}' does not exist.", did))
            report.findings, report.state = findings, _state_for(findings)
            continue
        text = path.read_text(encoding="utf-8")
        texts[did] = text
        words = count_body_words(text)
        report.word_count = words

        lo, hi = entry.get("min_words"), entry.get("max_words")
        if (lo is not None and words < lo) or (hi is not None and words > hi):
            findings.append(PackageFinding(
                LEVEL_REVISE, "WORD_COUNT",
                f"{words} words; required {lo if lo is not None else 0}-{hi if hi is not None else 'any'}.", did))

        findings.extend(_topic_findings(text, entry.get("required_topics", []), did))

        for f in detect_leakage(text, genre=(genre.value if genre else "")):
            findings.append(PackageFinding(LEVEL_REVISE, f.code, f"{f.message} “{f.matched_text}”", did))
        for f in check_genre_conformance(text, genre):
            findings.append(PackageFinding(LEVEL_REVISE, f.code, f.message, did))

        if sources:
            findings.extend(_check_references(text, sources, did))
            analysis = AcademicCitationManager().analyze_and_build_references(Document.parse(text, title=did), sources)
            for s in analysis.used_sources:
                cited_sources[s.id] = s
        elif entry.get("require_citations"):
            findings.append(PackageFinding(LEVEL_INCOMPLETE, "NO_SOURCES",
                                           "Citations are required but no sources file was supplied.", did))

        if role == "peer_reply":
            post_spec = entry.get("source_post") or {}
            post_text = ""
            if post_spec.get("path"):
                pp = _resolve(base, post_spec["path"])
                post_text = pp.read_text(encoding="utf-8") if pp.is_file() else ""
            post_text = post_text or post_spec.get("text", "")
            if not post_text.strip():
                findings.append(PackageFinding(
                    LEVEL_INCOMPLETE, "PEER_POST_MISSING",
                    "The post this reply answers was not supplied, so the reply cannot be reported as "
                    "source-grounded.", did))
            else:
                g = check_reply(text, [SourcePost(text=post_text, author=post_spec.get("author", ""))],
                                min_words=lo, max_words=hi,
                                extra_quotable_text=" ".join(s.retrieved_text or "" for s in sources))
                report.scores["reply_grounding"] = g.state.value
                for f in g.findings:
                    if f.code.startswith("REPLY_WORD_COUNT") or f.code.startswith("GENRE_"):
                        continue  # already reported above
                    level = LEVEL_BLOCKED if f.severity == "error" else LEVEL_REVISE
                    findings.append(PackageFinding(level, f.code, f.message, did))
                if g.state is GroundingState.UNSUPPORTED:
                    human.append(f"{did}: read the reply against the original post; it misstates or invents something.")

        if entry.get("original"):
            op = _resolve(base, entry["original"])
            if op.is_file():
                result = MeaningPreservationReviewer().compare(
                    Document.parse(op.read_text(encoding="utf-8"), title="original"),
                    Document.parse(text, title=did))
                report.scores["meaning_preservation"] = result.status
                if result.status != "PASS":
                    findings.append(PackageFinding(
                        LEVEL_REVISE, "MEANING_FLAGGED",
                        "Meaning differs from the original: " + "; ".join(d.description for d in result.diffs[:3]),
                        did))
                    human.append(f"{did}: confirm each flagged change from the original is intended.")
            else:
                findings.append(PackageFinding(LEVEL_UNAVAILABLE, "ORIGINAL_MISSING",
                                               "The original to compare against was not found.", did))
                unavailable.append(f"{did}: meaning preservation (original not found)")

        voice = _evaluate_voice(re.split(r"\n(?:#{1,3}\s*|\*\*\s*)References", text, flags=re.I)[0],
                                genre, spec.get("identity"))
        report.scores.update({f"voice.{k}": v for k, v in voice.items()})
        if voice.get("status") == "UNAVAILABLE":
            unavailable.append(f"{did}: voice evaluation ({voice.get('reason', '')})")
        else:
            for kind, label in (("voice_match", "Personal Voice Match"), ("naturalness", "Human Naturalness")):
                status = voice.get(f"{kind}_status")
                if status and status != "SCORED":
                    unavailable.append(f"{did}: {label} ({voice.get(f'{kind}_reason', status)})")
                    if spec.get(f"require_{kind}"):
                        findings.append(PackageFinding(
                            LEVEL_UNAVAILABLE, f"{kind.upper()}_UNAVAILABLE",
                            f"{label} is required but cannot be computed.", did))

        _record(records, did, "word count", "howlwriter.academic.length.count_body_words", findings,
                ("WORD_COUNT",), f"{words} words, required {lo if lo is not None else 0}-{hi if hi is not None else 'any'}")
        _record(records, did, "required topics", "howlwriter.assignment.package", findings, ("TOPIC_NOT_COVERED",),
                "every required topic phrase found in the body",
                ["Phrase presence only; it does not judge how well a topic is argued."])
        _record(records, did, "workflow-commentary leakage", "howlwriter.review.leakage", findings, ("LEAK_",),
                "no leaked process commentary found", ["Pattern based; novel phrasings can pass."])
        _record(records, did, "genre conventions", "howlwriter.domain.genres", findings, ("GENRE_",),
                f"conforms to {genre.value if genre else 'no genre'}")
        if sources:
            _record(records, did, "in-text citations and reference list", "howlwriter.assignment.package", findings,
                    ("CITATION_UNRESOLVED", "REFERENCE_"),
                    "every in-text citation resolves and the reference list matches the cited sources")
        if role == "peer_reply" and "reply_grounding" in report.scores:
            _record(records, did, "reply grounding", "howlwriter.replies.grounding", findings, ("REPLY_",),
                    f"grounding state {report.scores['reply_grounding']}",
                    ["Lexical comparison with the post; it cannot prove a paraphrase faithful."])
        if "meaning_preservation" in report.scores:
            _record(records, did, "meaning preservation vs original", "howlwriter.review.meaning", findings,
                    ("MEANING_",), "no substantive meaning difference found",
                    ["Heuristic: numbers, scope, attribution, hedges, causation, polarity."])
        records.append(semantic_review_record(did, writer_provider=entry.get("writer_provider"),
                                              reviewer_provider=entry.get("reviewer_provider")))
        report.findings = findings
        report.state = _state_for(findings)

    # Package-level deliverable count.
    expected = spec.get("expected_deliverables")
    if expected is not None and len(entries) != expected:
        package_findings.append(PackageFinding(
            LEVEL_INCOMPLETE, "DELIVERABLE_COUNT", f"{len(entries)} deliverable(s) listed; {expected} required."))

    # One work, one set of metadata: the documents must agree with each other.
    registry = build_registry(texts)
    for conflict in registry.conflicts():
        package_findings.append(PackageFinding(
            LEVEL_REVISE, conflict.code, conflict.message + f" (documents: {', '.join(conflict.documents)})"))

    # Citation metadata verification, once, for every source actually cited.
    verification: list[CitationVerification] = []
    if cited_sources and require_citations:
        if providers:
            verification = verify_sources(list(cited_sources.values()), providers)
        else:
            package_findings.append(PackageFinding(
                LEVEL_UNAVAILABLE, "CITATION_VERIFICATION_NOT_RUN",
                "Citation metadata was not checked against any authoritative record."))
            records.append(VerificationRecord(
                "citation metadata", "howlwriter.citations.verification", EXTERNAL_RECORD, UNAVAILABLE,
                scope="package", evidence="no record provider was configured",
                limitations=["A resolving DOI or URL does not establish that author, year and edition are right."]))
            unavailable.append("citation metadata verification (no provider configured)")
        for v in verification:
            records.append(VerificationRecord(
                f"citation metadata: {v.title[:50]}", "howlwriter.citations.verification", EXTERNAL_RECORD,
                {CitationState.VERIFIED: PASS, CitationState.MISMATCH: FAIL,
                 CitationState.NEEDS_REVIEW: NEEDS_REVIEW, CitationState.INCOMPLETE: NEEDS_REVIEW,
                 CitationState.UNVERIFIABLE: UNAVAILABLE}[v.state],
                scope="package",
                evidence=f"{v.state.value} against " + (", ".join(r.provider for r in v.records) or "no record"),
                limitations=([f"{p} was unreachable" for p in
                              [f.provider for f in v.findings if f.code == "CITATION_PROVIDER_UNAVAILABLE"]]
                             + ["Bibliographic metadata only; this does not show the source supports any claim."])))
            if v.state is CitationState.VERIFIED:
                continue
            level = {CitationState.MISMATCH: LEVEL_BLOCKED, CitationState.NEEDS_REVIEW: LEVEL_REVISE,
                     CitationState.INCOMPLETE: LEVEL_REVISE, CitationState.UNVERIFIABLE: LEVEL_UNAVAILABLE}[v.state]
            detail = "; ".join(f.message for f in v.findings if f.severity != "info") or v.state.value
            package_findings.append(PackageFinding(level, f"CITATION_{v.state.value}",
                                                   f"{v.title[:60]}: {detail}"))
            if v.state in (CitationState.NEEDS_REVIEW, CitationState.MISMATCH):
                human.append(f"Citation '{v.title[:50]}': decide which record is authoritative.")
            if v.state is CitationState.UNVERIFIABLE:
                unavailable.append(f"citation metadata for '{v.title[:50]}'")
    elif cited_sources and not require_citations:
        unavailable.append("citation metadata verification (not required by this package)")

    for finding in registry.apply_verifications(verification):
        package_findings.append(PackageFinding(
            LEVEL_REVISE, finding.code, finding.message + f" (documents: {', '.join(finding.documents)})"))
    all_findings = package_findings + [f for r in reports for f in r.findings]
    state = _state_for(all_findings)
    if state is PackageState.READY_FOR_HUMAN_REVIEW:
        human.append("Read each deliverable in full and approve it before it is submitted anywhere.")
    records.append(VerificationRecord(
        "cross-document citation consistency", "howlwriter.citations.registry", DETERMINISTIC,
        FAIL if any(f.code.startswith("CROSS_DOCUMENT") for f in package_findings) else PASS, scope="package",
        evidence=f"{len(registry.entries)} distinct work(s) across {len(texts)} document(s)"))
    return PackageReport(
        title=title, state=state, deliverables=reports, package_findings=package_findings,
        verification_records=records,
        unavailable_checks=unavailable, human_decisions=human,
        citation_verification=[v.to_summary() for v in verification])
