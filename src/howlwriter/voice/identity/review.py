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
from howlwriter.voice.identity.store import Decision, IdentityStore, parse_paragraph_ranges

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
) -> Decision:
    """Record a person's authorship decision for one document."""
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
    fingerprint = entry.get("fingerprint") or {}
    return store.record_decision(
        Decision(
            doc_id=doc_id,
            authorship=value,
            path=entry.get("relative_path", ""),
            category=category,
            context=context,
            include_paragraphs=include_paragraphs,
            note=note[:500],
            content_hash=entry.get("raw_sha256", ""),
            simhash=str(fingerprint.get("simhash", "")),
            words=int(entry.get("words") or 0),
        )
    )


def apply_worksheet(store: IdentityStore, path: Path) -> dict[str, int]:
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


@dataclass
class QueueItem:
    doc_id: str
    path: str
    category: str
    context: str
    words: int
    paragraphs: int
    proposed: str
    reasons: list[str]
    style_signals: list[str]
    priority: int
    reopened: bool
    predates_llm_era: bool | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def queue(store: IdentityStore) -> list[QueueItem]:
    inventory = store.load_inventory()
    decisions = store.load_decisions()
    items: list[QueueItem] = []
    for entry in inventory.get("entries", {}).values():
        if not needs_review(entry, decisions):
            continue
        proposal = entry.get("proposal") or {}
        classification = entry.get("classification") or {}
        decision = decisions.get(entry["doc_id"])
        items.append(
            QueueItem(
                doc_id=entry["doc_id"],
                path=entry["relative_path"],
                category=classification.get("category", "unknown"),
                context=classification.get("context", "unknown"),
                words=int(entry.get("words") or 0),
                paragraphs=int(entry.get("paragraph_count") or 0),
                proposed=proposal.get("authorship", classify.UNKNOWN_AUTHORSHIP),
                reasons=list(proposal.get("reasons", [])),
                style_signals=list(proposal.get("style_signals", [])),
                priority=int(proposal.get("review_priority", 0)),
                reopened=bool(decision and decision.status == "reopened"),
                predates_llm_era=(entry.get("provenance") or {}).get("predates_llm_era"),
            )
        )
    items.sort(key=lambda i: (-i.priority, i.path))
    return items


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
