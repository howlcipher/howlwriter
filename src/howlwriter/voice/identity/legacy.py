"""Recovering the evidence behind legacy voice profiles.

The `william` and `william_v2` profiles were built by `voice build` from a
drive scan before authorship review existed. They stay frozen: this module
opens their metadata read-only and never writes into a voice directory. What
it recovers is the *source list* -- which documents were used, in which
split, with what weight and classification -- so that the clean profiles can
reuse the genuine writing among them instead of rediscovering it, and so the
contamination they carried is identified rather than silently inherited.

For each historical source it records, in a private ledger
(`legacy_reconciliation.json` in the identity directory):

* historical membership: which legacy profiles used it, split, inclusion,
  weight, classification, context, duplicate role;
* where it is now: matched by path, then by raw-text hash (the same hash the
  legacy build stored), so moved or renamed files are found;
* whether its content changed since the legacy build;
* the current category, authorship proposal and any attestation;
* a recommendation (`candidate`, `candidate_answers_only`, `exclude`,
  `pending_review`, `missing`) with the reason.

Legacy feature measurements are never reused: they were computed on whole
documents, including the publisher and institutional text this pass exists to
remove. Only identities and historical decisions are carried over.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from howlwriter.voice.corpus.store import VoiceStore, voices_root
from howlwriter.voice.identity import classify, privacy
from howlwriter.voice.identity.scanner import effective_authorship
from howlwriter.voice.identity.store import IdentityStore, utc_now

LEDGER_FILE = "legacy_reconciliation.json"

#: Categories that are never the person's prose, whoever's name is on them.
NON_AUTHORED_CATEGORIES = {
    classify.ADMINISTRATIVE: "institutional or administrative record",
    classify.ASSIGNMENT_INSTRUCTIONS: "instructor-authored instructions",
    classify.TEMPLATE: "template",
    classify.COPIED_REFERENCE: "copied reference or licence text",
    classify.RESUME: "résumé or profile export (formatted, not prose)",
    classify.CONFIDENTIAL: "credential-shaped content",
    classify.NON_PROSE: "not prose",
}

#: Filename shapes that identify exports and letters the content classifier
#: may not catch. Used only to add an exclusion reason, never to include.
_EXPORT_NAMES = (
    ("profile.pdf", "LinkedIn profile export (formatted, not prose)"),
    ("resume", "résumé (formatted, not prose)"),
    ("admissions letter", "admissions correspondence written by the institution"),
)


@dataclass
class LegacySource:
    legacy_key: str
    profiles: list[str] = field(default_factory=list)
    split: str = ""
    inclusion: str = ""
    weight: float = 0.0
    classification: str = ""
    context: str = ""
    duplicate_role: str = ""
    group_id: str = ""
    words: int = 0
    legacy_text_hash: str = ""
    doc_id: str | None = None
    current_path: str | None = None
    match: str = "missing"  # path | content | missing
    content_changed: bool | None = None
    current_status: str = ""
    current_category: str = ""
    eligible_words: int = 0
    authorship: str = ""
    authorship_basis: str = ""
    confirmed: bool = False
    recommendation: str = ""
    reason: str = ""
    review_priority: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _legacy_records(names: list[str], root: Path) -> dict[str, LegacySource]:
    merged: dict[str, LegacySource] = {}
    for name in names:
        store = VoiceStore(name, root=root)
        if not store.exists():
            continue
        for key, record in store.load_sources().items():
            source = merged.get(key)
            if source is None:
                source = LegacySource(
                    legacy_key=key,
                    split=record.split,
                    inclusion=record.inclusion,
                    weight=record.weight,
                    classification=record.classification,
                    context=record.context,
                    duplicate_role=record.duplicate_role,
                    group_id=record.group_id,
                    words=record.words,
                    legacy_text_hash=record.content_hash,
                )
                merged[key] = source
            source.profiles.append(name)
    return merged


def _relative(config, absolute: str) -> str | None:
    for index, source in enumerate(config.sources):
        root = str(Path(source).expanduser())
        if absolute.startswith(root.rstrip("/") + "/"):
            relative = absolute[len(root.rstrip("/")) + 1:]
            return f"{index}:{relative}" if len(config.sources) > 1 else relative
    return None


def reconcile(
    identity: str,
    *,
    legacy_profiles: list[str] | None = None,
    store_root: Path | None = None,
    voices: Path | None = None,
) -> dict[str, Any]:
    """Build (or refresh) the private legacy reconciliation ledger."""
    store = IdentityStore(identity, root=store_root)
    if not store.exists():
        raise ValueError(f"identity '{store.identity}' has not been scanned yet")
    config = store.load_config()
    names = legacy_profiles or [store.identity, f"{store.identity}_v2"]
    root = voices if voices is not None else voices_root()
    sources = _legacy_records(names, root)
    entries = store.load_inventory().get("entries", {})
    decisions = store.load_decisions()

    by_path = {e["relative_path"]: (k, e) for k, e in entries.items() if e.get("present", True)}
    by_hash: dict[str, list[tuple[str, dict]]] = {}
    for k, e in entries.items():
        if e.get("present", True) and e.get("text_hash"):
            by_hash.setdefault(e["text_hash"], []).append((k, e))

    for source in sources.values():
        relative = _relative(config, source.legacy_key)
        hit = by_path.get(relative) if relative else None
        if hit is not None:
            source.match = "path"
        elif source.legacy_text_hash and len(by_hash.get(source.legacy_text_hash, [])) == 1:
            hit = by_hash[source.legacy_text_hash][0]
            source.match = "content"
        if hit is None:
            source.recommendation = "missing"
            source.reason = "not found in the current inventory by path or content"
            continue
        doc_id, entry = hit
        source.doc_id = doc_id
        source.current_path = entry["relative_path"]
        source.current_status = entry.get("status", "")
        source.current_category = (entry.get("classification") or {}).get("category", "")
        source.eligible_words = int(entry.get("eligible_words") or entry.get("prose_words") or 0)
        if entry.get("text_hash") and source.legacy_text_hash:
            source.content_changed = entry["text_hash"] != source.legacy_text_hash
        authorship, basis = effective_authorship(entry, decisions)
        source.authorship, source.authorship_basis = authorship, basis
        source.confirmed = basis == "attested"
        source.review_priority = int((entry.get("proposal") or {}).get("review_priority", 0))
        _recommend(source, entry, decisions.get(doc_id))

    summary = summarize(list(sources.values()))
    payload = {
        "identity": store.identity,
        "generated_at": utc_now(),
        "legacy_profiles": [n for n in names if VoiceStore(n, root=root).exists()],
        "note": (
            "Legacy profiles were read, never modified. Their feature measurements are not "
            "reused; only source identities and historical decisions are."
        ),
        "summary": summary,
        "sources": {k: s.to_dict() for k, s in sorted(sources.items())},
    }
    privacy.write_private_json(store.directory / LEDGER_FILE, payload)
    return payload


def _recommend(source: LegacySource, entry: dict, decision) -> None:
    category = source.current_category
    lowered = (source.current_path or "").lower()
    if source.current_status != "extracted":
        source.recommendation = "exclude"
        source.reason = f"currently {source.current_status or 'unreadable'}"
        return
    if decision is not None and decision.effective:
        if decision.authorship in classify.PROFILE_WEIGHTS:
            source.recommendation = "candidate"
            source.reason = f"attested {decision.authorship}"
        else:
            source.recommendation = "exclude"
            source.reason = f"attested {decision.authorship}"
        return
    for marker, reason in _EXPORT_NAMES:
        if marker in lowered:
            source.recommendation = "exclude"
            source.reason = reason
            return
    if category in NON_AUTHORED_CATEGORIES:
        source.recommendation = "exclude"
        source.reason = NON_AUTHORED_CATEGORIES[category]
        return
    if entry.get("duplicate_role") == "duplicate":
        source.recommendation = "exclude"
        source.reason = "duplicate of another document in the inventory"
        return
    sheet = entry.get("worksheet")
    if sheet:
        worth = (entry.get("proposal") or {}).get("needs_review")
        source.recommendation = "candidate_answers_only" if worth else "exclude"
        source.reason = (
            f"publisher worksheet: about {sheet.get('answer_words')} of {sheet.get('total_words')} "
            "words are answer lines" + ("" if worth else "; too little to contribute")
        )
        return
    if category not in classify.CATEGORY_CONTEXT:
        source.recommendation = "exclude"
        source.reason = f"category '{category}' does not feed a profile"
        return
    source.recommendation = "pending_review"
    source.reason = "plausibly the author's writing; authorship has not been confirmed"


def summarize(sources: list[LegacySource]) -> dict[str, Any]:
    used = [s for s in sources if s.inclusion in ("include", "include_low_weight")]
    trained = [s for s in used if s.split == "train" and s.duplicate_role != "duplicate"]

    def count(predicate, items=None) -> int:
        return sum(1 for s in (items if items is not None else sources) if predicate(s))

    recs: dict[str, int] = {}
    for s in sources:
        recs[s.recommendation or "none"] = recs.get(s.recommendation or "none", 0) + 1
    excluded_trained = [s for s in trained if s.recommendation == "exclude"]
    trained_words = sum(s.words for s in trained) or 1
    return {
        "historical_sources": len(sources),
        "historically_used": len(used),
        "historically_trained": len(trained),
        "matched_by_path": count(lambda s: s.match == "path"),
        "matched_by_content": count(lambda s: s.match == "content"),
        "missing": count(lambda s: s.match == "missing"),
        "content_changed_since_legacy_build": count(lambda s: s.content_changed is True),
        "historical_duplicates": count(lambda s: s.duplicate_role == "duplicate"),
        "recommendations": dict(sorted(recs.items())),
        "trained_sources_now_excluded": len(excluded_trained),
        "trained_words_now_excluded": sum(s.words for s in excluded_trained),
        "trained_word_share_now_excluded": round(
            sum(s.words for s in excluded_trained) / trained_words, 3
        ),
        "confirmed": count(lambda s: s.confirmed),
        "pending_review": count(
            lambda s: s.recommendation in ("pending_review", "candidate_answers_only")
            and not s.confirmed
        ),
        "eligible_words_pending_or_confirmed": sum(
            s.eligible_words
            for s in sources
            if s.recommendation in ("candidate", "candidate_answers_only", "pending_review")
        ),
    }


def load(identity: str, *, store_root: Path | None = None) -> dict | None:
    path = IdentityStore(identity, root=store_root).directory / LEDGER_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def legacy_membership(identity: str, *, store_root: Path | None = None) -> dict[str, list[str]]:
    """doc_id -> legacy profiles that trained on it (for review display)."""
    ledger = load(identity, store_root=store_root) or {}
    out: dict[str, list[str]] = {}
    for source in (ledger.get("sources") or {}).values():
        if source.get("doc_id") and source.get("inclusion") in ("include", "include_low_weight"):
            out[source["doc_id"]] = list(source.get("profiles", []))
    return out
