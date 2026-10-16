"""Document families: which documents must stay together.

Two uses, one definition.

**Holdout integrity.** A held-out document only tests a profile if nothing
closely related to it was trained on. A draft and its final version, a
proposal and the paper it became, two copies of one assignment in different
folders, and worksheets printed from the same publisher template all share
text. If one lands in training and the other in holdout, validation measures
memory. Families are assigned to one side of the split as a unit.

**Grouped review.** The same families, plus course codes and month of last
modification, are the groups a person can review together.

Families are a union of conservative links -- over-grouping only makes the
split coarser, while under-grouping leaks -- so any of these joins two
documents:

* the scanner already grouped them as duplicates;
* their SimHash fingerprints are within `FAMILY_SIMHASH_BITS`;
* their file names share a base name once draft/final/version/copy markers
  are removed;
* their file names name the same numbered deliverable -- a paper, project or
  deliverable (``Paper2_Project Proposal`` and ``Paper 2 _ Project
  Submission``). Generic numbering (``A3``, ``Assignment 3``, ``Lab 3``) does
  not link on its own: on a real corpus it joined unrelated documents from
  different courses that happened to share a number, and genuine revisions
  are already joined by content (duplicate grouping, SimHash) or base name;
* they are worksheets from the same publisher series (same parenthesised
  edition and suffix, e.g. ``(4e) - Name``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
import re

from howlwriter.voice.corpus.dedup import hamming
from howlwriter.voice.identity.store import source_path_of

#: Looser than the duplicate threshold on purpose: revisions that dedup keeps
#: separately still share enough text to leak across a split.
FAMILY_SIMHASH_BITS = 16

_VERSION_MARKERS = re.compile(
    r"(?:[\s_-]*(?:draft|final|v\d+|version\s*\d+|copy|revised|rev\d*|edit(?:ed)?|\(\d+\)|formatted))+$",
    re.IGNORECASE,
)
_ASSIGNMENT = re.compile(
    r"\b(?:(paper|deliverable|project)\s*[_ :-]*\s*(\d{1,2}))(?!\d)", re.IGNORECASE
)
_SERIES = re.compile(r"(\(\s*\d+\s*[a-z]{1,3}\s*\)\s*-\s*[\w .'-]+)$", re.IGNORECASE)
_COURSE = re.compile(r"\b([A-Z]{3,5})\s?[-_]?\s?(\d{3})\b")


def _stem(relative_path: str) -> str:
    return PurePosixPath(source_path_of(relative_path)).stem


def base_name(relative_path: str) -> str:
    stem = _VERSION_MARKERS.sub("", _stem(relative_path)).strip(" _-")
    return re.sub(r"[\s_-]+", " ", stem).lower()


def assignment_key(relative_path: str) -> str | None:
    match = _ASSIGNMENT.search(_stem(relative_path))
    if not match:
        return None
    return f"{match.group(1).lower()}:{int(match.group(2))}"


def series_key(relative_path: str) -> str | None:
    match = _SERIES.search(_stem(relative_path))
    return re.sub(r"\s+", " ", match.group(1).lower()) if match else None


def course_key(relative_path: str) -> str | None:
    match = _COURSE.search(source_path_of(relative_path))
    return f"{match.group(1)} {match.group(2)}" if match else None


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def assign_families(entries: dict[str, dict]) -> dict[str, str]:
    """Map every extracted, present document id to a family id."""
    docs = {
        doc_id: e
        for doc_id, e in entries.items()
        if e.get("present", True) and e.get("status") == "extracted"
    }
    uf = _UnionFind()
    links: dict[str, str] = {}

    def link(doc_id: str, key: str) -> None:
        if key in links:
            uf.union(doc_id, links[key])
        else:
            links[key] = doc_id
        uf.find(doc_id)

    simhashes: list[tuple[str, int]] = []
    for doc_id, entry in docs.items():
        uf.find(doc_id)
        if entry.get("duplicate_of"):
            uf.union(doc_id, entry["duplicate_of"])
        path = entry["relative_path"]
        link(doc_id, "base:" + base_name(path))
        assignment = assignment_key(path)
        if assignment:
            link(doc_id, "assignment:" + assignment)
        if entry.get("worksheet"):
            link(doc_id, "series:" + (series_key(path) or "worksheet"))
        fp = entry.get("fingerprint") or {}
        if fp.get("simhash"):
            simhashes.append((doc_id, int(str(fp["simhash"]), 16)))
    for i, (left, left_hash) in enumerate(simhashes):
        for right, right_hash in simhashes[i + 1:]:
            if hamming(left_hash, right_hash) <= FAMILY_SIMHASH_BITS:
                uf.union(left, right)
    return {doc_id: "family:" + uf.find(doc_id) for doc_id in docs}


def month_of(entry: dict) -> str:
    try:
        return datetime.fromtimestamp(float(entry.get("mtime") or 0), tz=timezone.utc).strftime(
            "%Y-%m"
        )
    except (OverflowError, OSError, ValueError):
        return "unknown"
