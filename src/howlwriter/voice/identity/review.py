"""The authorship review workflow.

Three ways in, one record out. A person can attest documents interactively
(`howlwriter voice review --interactive`), by editing the generated
`review_queue.yaml` worksheet and applying it, or from the web UI. Each path
calls `attest()`, which stamps the decision with the document's current
content fingerprint -- that stamp is what lets a later scan tell "lightly
edited since you confirmed it" from "a different document now".

Previews re-read the source file on demand and are returned to the caller
for display only. They are never cached, logged, or written to the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from howlwriter.voice.corpus.cleanup import clean_document
from howlwriter.voice.corpus.extract import extract
from howlwriter.voice.identity import classify
from howlwriter.voice.identity.analysis import paragraphs_of
from howlwriter.voice.identity.scanner import effective_authorship, needs_review, write_review_queue
from howlwriter.voice.identity.store import (
    Decision,
    IdentityStore,
    parse_paragraph_ranges,
    source_path_of,
)

#: Short aliases accepted interactively and in the worksheet.
ALIASES = {
    "h": classify.CONFIRMED_HUMAN_AUTHORED,
    "human": classify.CONFIRMED_HUMAN_AUTHORED,
    "l": classify.HUMAN_AUTHORED_LIGHT_AI_EDITING,
    "light": classify.HUMAN_AUTHORED_LIGHT_AI_EDITING,
    "m": classify.MIXED_AUTHORSHIP,
    "mixed": classify.MIXED_AUTHORSHIP,
    "a": classify.SUBSTANTIALLY_AI_GENERATED,
    "ai": classify.SUBSTANTIALLY_AI_GENERATED,
    "t": classify.THIRD_PARTY,
    "third": classify.THIRD_PARTY,
    "u": classify.UNKNOWN_AUTHORSHIP,
    "unknown": classify.UNKNOWN_AUTHORSHIP,
}


def normalize_authorship(value: str) -> str:
    raw = (value or "").strip()
    if raw.upper() in classify.AUTHORSHIP_STATES:
        return raw.upper()
    alias = ALIASES.get(raw.lower())
    if alias is None:
        raise ValueError(
            f"unknown authorship {value!r}; use one of {', '.join(classify.AUTHORSHIP_STATES)}"
        )
    return alias


def _entry(store: IdentityStore, doc_id: str) -> dict:
    inventory = store.load_inventory()
    entry = inventory.get("entries", {}).get(doc_id)
    if entry is None:
        raise ValueError(f"no document with id {doc_id!r} in identity '{store.identity}'")
    return entry


def attest(
    store: IdentityStore,
    doc_id: str,
    authorship: str,
    *,
    category: str = "",
    context: str = "",
    include_paragraphs: str = "",
    note: str = "",
    extraction: str = "",
    use_proposed_extraction: bool = False,
    source: str = "user_attestation",
) -> Decision:
    """Record a person's authorship decision for one document.

    `use_proposed_extraction` accepts the scanner's proposed extraction (the
    answer lines of a publisher worksheet) for a MIXED_AUTHORSHIP decision.
    """
    entry = _entry(store, doc_id)
    value = normalize_authorship(authorship)
    if category and category not in classify.CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    if context and context not in ("academic", "professional", "general", "social"):
        raise ValueError(f"unknown context {context!r}")
    if value == classify.MIXED_AUTHORSHIP and include_paragraphs:
        chosen = parse_paragraph_ranges(include_paragraphs)
        count = int(entry.get("paragraph_count") or 0)
        if count and max(chosen) >= count:
            raise ValueError(
                f"paragraph {max(chosen) + 1} does not exist; the document has {count} paragraphs"
            )
    elif include_paragraphs and value != classify.MIXED_AUTHORSHIP:
        raise ValueError("include_paragraphs applies only to MIXED_AUTHORSHIP")
    if use_proposed_extraction and not extraction:
        extraction = (entry.get("proposal") or {}).get("proposed_extraction", "")
        if not extraction and value == classify.MIXED_AUTHORSHIP:
            raise ValueError("this document has no proposed extraction; list paragraphs instead")
    if extraction and value != classify.MIXED_AUTHORSHIP:
        raise ValueError("an extraction applies only to MIXED_AUTHORSHIP")
    if extraction and include_paragraphs:
        raise ValueError("use either include_paragraphs or an extraction, not both")
    if not category and not context:
        # Pin the category the person saw when deciding: a later classifier
        # change must not move an attested document into another profile.
        category = (entry.get("classification") or {}).get("category", "")
        if category not in classify.CATEGORIES:
            category = ""
    fingerprint = entry.get("fingerprint") or {}
    return store.record_decision(
        Decision(
            doc_id=doc_id,
            authorship=value,
            path=entry.get("relative_path", ""),
            category=category,
            context=context,
            include_paragraphs=include_paragraphs,
            extraction=extraction,
            note=note[:500],
            content_hash=entry.get("raw_sha256", ""),
            simhash=str(fingerprint.get("simhash", "")),
            words=int(entry.get("words") or 0),
            source=source,
        )
    )


def apply_worksheet(store: IdentityStore, path: Path, *, source: str = "user_attestation") -> dict[str, int]:
    """Apply every non-pending decision in an edited review_queue.yaml."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    applied = skipped = errors = 0
    problems: list[str] = []
    for item in data.get("pending", []) or []:
        decision = str(item.get("decision", "pending") or "pending").strip()
        if decision.lower() in ("pending", ""):
            skipped += 1
            continue
        try:
            attest(
                store,
                str(item["doc_id"]),
                decision,
                category=str(item.get("category_override", "") or ""),
                context=str(item.get("context_override", "") or ""),
                include_paragraphs=str(item.get("include_paragraphs", "") or ""),
                note=str(item.get("note", "") or ""),
                source=source,
            )
            applied += 1
        except (ValueError, KeyError) as error:
            errors += 1
            problems.append(f"{item.get('doc_id')}: {error}")
    refresh_queue(store)
    return {"applied": applied, "skipped": skipped, "errors": errors, "problems": problems}


def refresh_queue(store: IdentityStore) -> Path:
    inventory = store.load_inventory()
    return write_review_queue(store, inventory.get("entries", {}), store.load_decisions())


#: Expected corpus value by category, used to order the queue. Independent
#: discussion and lab analysis are the most direct evidence of unaided
#: writing; long papers are valuable but most exposed to AI drafting;
#: worksheets contribute only their answer lines. Professional writing is
#: scarce on this corpus, so it ranks high.
_CATEGORY_VALUE = {
    classify.ACADEMIC_DISCUSSION: 6,
    classify.ACADEMIC_LAB: 5,
    classify.PROFESSIONAL_ARTICLE: 6,
    classify.PROFESSIONAL_ENGINEERING: 6,
    classify.TECHNICAL_DOCUMENTATION: 6,
    classify.PUBLIC_COMMENTARY: 5,
    classify.RESEARCH_ANALYSIS: 4,
    classify.ACADEMIC_PAPER: 4,
}

AUTHORSHIP_DESCRIPTIONS = {
    classify.CONFIRMED_HUMAN_AUTHORED: "You wrote it yourself, without AI drafting or rewriting the prose.",
    classify.HUMAN_AUTHORED_LIGHT_AI_EDITING: (
        "Your prose; AI only suggested small wording or grammar fixes. Counts at half weight."
    ),
    classify.MIXED_AUTHORSHIP: (
        "Part yours, part not (AI-drafted sections, quoted or publisher text). Only the parts "
        "you identify are used."
    ),
    classify.SUBSTANTIALLY_AI_GENERATED: (
        "AI drafted most of the prose, even if the ideas were yours. Never used as your voice."
    ),
    classify.THIRD_PARTY: "Someone else wrote it. Never used.",
    classify.UNKNOWN_AUTHORSHIP: "You are not sure. Kept out of the profiles.",
}


@dataclass
class QueueItem:
    doc_id: str
    path: str
    category: str
    context: str
    words: int
    eligible_words: int
    paragraphs: int
    proposed: str
    recommendation: str
    reasons: list[str]
    style_signals: list[str]
    priority: int
    value: float
    reopened: bool
    predates_llm_era: bool | None
    mixed: bool
    proposed_extraction: str
    revision_history: str
    legacy_profiles: list[str]
    family: str
    course: str
    month: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _revision_history(entry: dict) -> str:
    provenance = entry.get("provenance") or {}
    if provenance.get("revision_count") is not None:
        span = provenance.get("revision_span_days")
        return f"{provenance['revision_count']} Drive revisions" + (
            f" over {span} days" if span is not None else ""
        )
    if provenance.get("revision") is not None:
        return f"saved {provenance['revision']} times (Word revision counter)"
    return "no revision history available"


def _value(entry: dict, category: str) -> float:
    import math

    words = int(entry.get("eligible_words") or entry.get("prose_words") or 0)
    value = _CATEGORY_VALUE.get(category, 2) + min(3.0, max(0.0, math.log2(max(words, 1) / 150)))
    provenance = entry.get("provenance") or {}
    if provenance.get("byline_identity"):
        value += 1.0
    if "draft" in entry.get("relative_path", "").lower():
        value += 1.0
    if entry.get("worksheet"):
        value -= 2.0
    return round(value, 2)


def queue(store: IdentityStore) -> list[QueueItem]:
    """Documents awaiting a decision, most valuable independent evidence first."""
    from howlwriter.voice.identity.families import assign_families, course_key, month_of
    from howlwriter.voice.identity.legacy import legacy_membership

    inventory = store.load_inventory()
    entries = inventory.get("entries", {})
    decisions = store.load_decisions()
    families = assign_families(entries)
    legacy = legacy_membership(store.identity, store_root=store.root)
    items: list[QueueItem] = []
    for entry in entries.values():
        if not needs_review(entry, decisions):
            continue
        proposal = entry.get("proposal") or {}
        classification = entry.get("classification") or {}
        decision = decisions.get(entry["doc_id"])
        category = classification.get("category", "unknown")
        reasons = list(proposal.get("reasons", []))
        items.append(
            QueueItem(
                doc_id=entry["doc_id"],
                path=entry["relative_path"],
                category=category,
                context=classification.get("context", "unknown"),
                words=int(entry.get("words") or 0),
                eligible_words=int(entry.get("eligible_words") or entry.get("prose_words") or 0),
                paragraphs=int(entry.get("paragraph_count") or 0),
                proposed=proposal.get("authorship", classify.UNKNOWN_AUTHORSHIP),
                recommendation=reasons[0] if reasons else "",
                reasons=reasons,
                style_signals=list(proposal.get("style_signals", [])),
                priority=int(proposal.get("review_priority", 0)),
                value=_value(entry, category),
                reopened=bool(decision and decision.status == "reopened"),
                predates_llm_era=(entry.get("provenance") or {}).get("predates_llm_era"),
                mixed=proposal.get("authorship") == classify.MIXED_AUTHORSHIP,
                proposed_extraction=proposal.get("proposed_extraction", ""),
                revision_history=_revision_history(entry),
                legacy_profiles=legacy.get(entry["doc_id"], []),
                family=families.get(entry["doc_id"], ""),
                course=course_key(entry["relative_path"]) or "",
                month=month_of(entry),
            )
        )
    # Prefer independent documents: the second and later members of a family
    # add less new evidence than the first, so they sink.
    items.sort(key=lambda i: (-i.value, i.path))
    seen: set[str] = set()
    for item in items:
        if item.family in seen:
            item.value = round(item.value - 2.0, 2)
        seen.add(item.family)
    items.sort(key=lambda i: (not i.reopened, -i.value, i.path))
    return items


@dataclass
class ReviewGroup:
    group_id: str
    kind: str
    label: str
    doc_ids: list[str]
    titles: list[str]
    eligible_words: int
    categories: dict[str, int]
    proposed: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def groups(store: IdentityStore, items: list[QueueItem] | None = None) -> list[ReviewGroup]:
    """Pending documents grouped by family, course, worksheet series and month.

    Groups are for reviewing related documents together. They never decide
    anything: a bulk decision is applied only to the members the person saw.
    """
    import hashlib
    from pathlib import PurePosixPath

    from howlwriter.voice.identity.families import series_key

    items = items if items is not None else queue(store)
    buckets: dict[tuple[str, str], list[QueueItem]] = {}
    for item in items:
        keys = [("family", item.family)]
        if item.course:
            keys.append(("course", item.course))
        if item.mixed and item.proposed_extraction:
            keys.append(("worksheet_series", series_key(item.path) or "worksheets"))
        keys.append(("month", item.month))
        keys.append(("context", item.context))
        for key in keys:
            buckets.setdefault(key, []).append(item)
    result: list[ReviewGroup] = []
    for (kind, key), members in buckets.items():
        if len(members) < 2:
            continue
        ids = sorted(m.doc_id for m in members)
        group_id = hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()[:10]
        label = {
            "family": f"related documents ({members[0].category.replace('_', ' ')})",
            "course": f"course {key}",
            "worksheet_series": f"publisher worksheets {key}",
            "month": f"modified {key}",
            "context": f"{key} context",
        }[kind]
        categories: dict[str, int] = {}
        proposed: dict[str, int] = {}
        for m in members:
            categories[m.category] = categories.get(m.category, 0) + 1
            proposed[m.proposed] = proposed.get(m.proposed, 0) + 1
        result.append(
            ReviewGroup(
                group_id=f"{kind[:3]}-{group_id}",
                kind=kind,
                label=label,
                doc_ids=ids,
                titles=[
                    PurePosixPath(source_path_of(m.path)).name
                    for m in sorted(members, key=lambda m: m.doc_id)
                ],
                eligible_words=sum(m.eligible_words for m in members),
                categories=categories,
                proposed=proposed,
            )
        )
    order = {"family": 0, "worksheet_series": 1, "course": 2, "context": 3, "month": 4}
    result.sort(key=lambda g: (order[g.kind], -g.eligible_words))
    return result


def attest_group(
    store: IdentityStore,
    group_id: str,
    authorship: str,
    *,
    confirmed_doc_ids: list[str],
    use_proposed_extraction: bool = False,
    note: str = "",
    source: str = "user_attestation",
) -> list[Decision]:
    """Apply one decision to every pending member of a group.

    `confirmed_doc_ids` must be exactly the members the person was shown. If
    the group changed in between (a scan added or resolved a document), the
    bulk decision is refused rather than applied to documents nobody looked
    at.
    """
    current = next((g for g in groups(store) if g.group_id == group_id), None)
    if current is None:
        raise ValueError(f"no pending review group {group_id!r}")
    if sorted(confirmed_doc_ids) != current.doc_ids:
        raise ValueError(
            "the group's members changed since they were shown; review the current list and confirm again"
        )
    value = normalize_authorship(authorship)
    decisions = []
    for doc_id in current.doc_ids:
        decisions.append(
            attest(
                store,
                doc_id,
                value,
                note=note,
                use_proposed_extraction=use_proposed_extraction
                and value == classify.MIXED_AUTHORSHIP,
                source=source,
            )
        )
    refresh_queue(store)
    return decisions


def preview(
    store: IdentityStore, doc_id: str, *, max_paragraphs: int = 40, max_chars: int = 400
) -> list[str]:
    """Numbered paragraphs of the cleaned text, re-read from the source.

    For display to the document's owner only. Nothing is cached.
    """
    entry = _entry(store, doc_id)
    config = store.load_config()
    relative = entry["relative_path"]
    index = 0
    if ":" in relative and relative.split(":", 1)[0].isdigit() and len(config.sources) > 1:
        index_text, relative = relative.split(":", 1)
        index = int(index_text)
    root = Path(config.sources[index]).expanduser()
    path = (root / relative).resolve()
    if Path(root).resolve() not in path.parents:
        raise ValueError("refusing to preview a path outside the identity's source root")
    if config.exclusions.path_is_excluded(relative.split("/")):
        raise ValueError("refusing to preview a file under an excluded directory")
    result = extract(path)
    if not result.ok:
        return [f"(preview unavailable: {result.reason})"]
    paragraphs = paragraphs_of(clean_document(result.text).text)
    shown = []
    for number, paragraph in enumerate(paragraphs[:max_paragraphs], start=1):
        text = " ".join(paragraph.split())
        shown.append(
            f"[{number}] " + (text if len(text) <= max_chars else text[: max_chars - 1] + "…")
        )
    if len(paragraphs) > max_paragraphs:
        shown.append(f"... {len(paragraphs) - max_paragraphs} more paragraphs")
    return shown


def summary(store: IdentityStore) -> dict[str, Any]:
    inventory = store.load_inventory()
    decisions = store.load_decisions()
    counts: dict[str, int] = {}
    for entry in inventory.get("entries", {}).values():
        if not entry.get("present", True) or entry.get("status") != "extracted":
            continue
        value, basis = effective_authorship(entry, decisions)
        counts[f"{value}:{basis}"] = counts.get(f"{value}:{basis}", 0) + 1
    return {
        "pending": len(queue(store)),
        "decisions": len(decisions),
        "reopened": sum(1 for d in decisions.values() if d.status == "reopened"),
        "by_authorship": dict(sorted(counts.items())),
    }
