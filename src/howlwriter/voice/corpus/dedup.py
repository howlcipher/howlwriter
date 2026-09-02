"""Stage 7: make sure one piece of writing counts once.

A drive accumulates the same document many times over. `A5.docx` sits beside
`A5 (1).docx`; a paper is saved as .docx and exported to .pdf; an assignment
goes through four revisions that differ by a paragraph. Left alone, every one
of those inflates the corpus and, worse, overweights whichever piece of
writing the author happened to save the most times. Ten near-copies of one
essay would drag the whole profile toward that essay's cadence.

Four passes, cheapest first:

  exact        identical normalized text
  cross-format the same document saved in two formats
  revision     a small edit of a document already seen
  representative  pick the richest copy of each group

Everything is deterministic and local. Documents are compared by hash,
shingle overlap, and SimHash distance -- never by asking a model, which would
be slow, expensive, and non-reproducible for a job that is fundamentally
string comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re

_WORD = re.compile(r"[a-z0-9']+")

#: Shingle width. Three words is long enough that shared stock phrases do not
#: create false overlap, short enough that a reworded sentence still shares
#: most of its shingles with the original.
_SHINGLE = 3

#: Jaccard overlap above which two documents are the same writing.
REVISION_JACCARD = 0.72

#: Hamming distance on the 64-bit SimHash below which two documents are
#: candidates. Used as a cheap pre-filter before the exact Jaccard test.
SIMHASH_DISTANCE = 12

#: Cross-format pairs are compared on a stricter overlap, because a PDF
#: export of a DOCX should be nearly identical, not merely similar.
CROSS_FORMAT_JACCARD = 0.60

#: How rich a format's extraction is. When the same document exists twice,
#: the copy that preserves the most structure wins: a DOCX keeps headings and
#: list markers that a PDF export has already flattened into text.
_FORMAT_RANK = {
    ".docx": 5, ".odt": 5, ".md": 4, ".markdown": 4, ".rtf": 3,
    ".html": 3, ".htm": 3, ".txt": 2, ".text": 2, ".pdf": 1, ".doc": 0,
}

#: Filename decorations that mark a copy or a revision rather than a new
#: document: "A5 (1).docx", "paper v2.docx", "report - Copy.docx".
_REVISION_SUFFIX = re.compile(
    r"(?:\s*\((?:\d+|copy)\)|\s*-\s*copy|\s*copy\s*\d*|[\s_-]*v(?:er(?:sion)?)?\.?\s*\d+|"
    r"[\s_-]*(?:final|draft|rev(?:ised|ision)?|updated?|new|old)\d*)+$",
    re.IGNORECASE,
)


@dataclass
class DedupMember:
    """One document's place in the deduplication result."""

    key: str
    group_id: str = ""
    role: str = "representative"   # "representative" | "duplicate"
    relation: str = ""             # "exact" | "cross_format" | "revision"
    reason: str = ""


@dataclass
class DedupGroup:
    group_id: str
    representative: str = ""
    members: list[str] = field(default_factory=list)
    relation: str = ""


@dataclass
class DedupResult:
    members: dict[str, DedupMember] = field(default_factory=dict)
    groups: list[DedupGroup] = field(default_factory=list)
    exact_duplicates: int = 0
    cross_format_duplicates: int = 0
    revision_duplicates: int = 0

    @property
    def revision_groups(self) -> int:
        """Groups holding more than one document -- the count worth reporting."""
        return sum(1 for g in self.groups if len(g.members) > 1)

    def representatives(self) -> list[str]:
        return [k for k, m in self.members.items() if m.role == "representative"]


@dataclass
class DedupCandidate:
    """The minimum a document must expose to be deduplicated."""

    key: str
    path: Path
    text: str
    words: int
    mtime: float = 0.0


def normalize(text: str) -> str:
    """Collapse a document to comparable form: lowercase words only.

    Punctuation, casing, and whitespace differ between a DOCX and its PDF
    export even when the words are identical, so none of them can take part
    in the comparison.
    """
    return " ".join(_WORD.findall(text.lower()))


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def shingles(text: str) -> set[str]:
    words = _WORD.findall(text.lower())
    if len(words) < _SHINGLE:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)}


def simhash(items: set[str], bits: int = 64) -> int:
    """64-bit SimHash over a shingle set.

    A cheap similarity pre-filter: documents whose hashes are far apart cannot
    be near-duplicates, which avoids an O(n^2) Jaccard over the whole corpus.
    """
    if not items:
        return 0
    vector = [0] * bits
    for item in items:
        digest = int.from_bytes(hashlib.blake2b(item.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(bits):
            vector[bit] += 1 if (digest >> bit) & 1 else -1
    value = 0
    for bit in range(bits):
        if vector[bit] > 0:
            value |= 1 << bit
    return value


def hamming(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left) + len(right) - intersection
    return intersection / union if union else 0.0


def base_name(path: Path) -> str:
    """The document's name with copy/revision decorations stripped.

    "Assignment 7 Analysisv2" and "Assignment 7 Analysis" reduce to the same
    base, which is what lets a revision pair be recognised even when the text
    has drifted further than the similarity threshold.
    """
    stem = path.stem.strip()
    previous = None
    while previous != stem:
        previous = stem
        stem = _REVISION_SUFFIX.sub("", stem).strip(" _-")
    return re.sub(r"\s+", " ", stem).lower()


def _richness(candidate: DedupCandidate) -> tuple[int, int, float, str]:
    """Sort key choosing the best copy: format, then length, then recency."""
    return (
        _FORMAT_RANK.get(candidate.path.suffix.lower(), 0),
        candidate.words,
        candidate.mtime,
        str(candidate.path),
    )


def deduplicate(candidates: list[DedupCandidate]) -> DedupResult:
    """Group documents that are the same piece of writing.

    Candidates are processed in a stable order so that the same corpus always
    produces the same groups and the same representatives -- a rebuild must
    not shuffle which copy of a paper is the one that counts.
    """
    result = DedupResult()
    ordered = sorted(candidates, key=lambda c: str(c.path))
    if not ordered:
        return result

    prepared = [
        (
            candidate,
            content_hash(candidate.text),
            shingles(candidate.text),
            base_name(candidate.path),
        )
        for candidate in ordered
    ]
    hashes = {
        candidate.key: simhash(shingle_set)
        for candidate, _, shingle_set, _ in prepared
    }

    groups: list[dict] = []

    for candidate, digest, shingle_set, base in prepared:
        matched: dict | None = None
        relation = ""
        reason = ""

        for group in groups:
            # 1. Exact content match.
            if digest == group["hash"]:
                matched, relation = group, "exact"
                reason = "normalized text is byte-identical to another document"
                break

            similarity = jaccard(shingle_set, group["shingles"])
            same_base = base == group["base"]
            other_suffix = group["representative"].path.suffix.lower()
            cross_format = other_suffix != candidate.path.suffix.lower()

            # 2. The same document saved in two formats.
            if cross_format and (same_base or similarity >= CROSS_FORMAT_JACCARD):
                if similarity >= CROSS_FORMAT_JACCARD:
                    matched, relation = group, "cross_format"
                    reason = (
                        f"same content as a {other_suffix} copy "
                        f"({similarity:.0%} shingle overlap)"
                    )
                    break

            # 3. A revision of something already seen. The SimHash pre-filter
            #    keeps this from becoming an all-pairs comparison.
            if hamming(hashes[candidate.key], group["simhash"]) <= SIMHASH_DISTANCE:
                if similarity >= REVISION_JACCARD:
                    matched, relation = group, "revision"
                    reason = f"near-duplicate revision ({similarity:.0%} shingle overlap)"
                    break
            if same_base and similarity >= 0.35:
                matched, relation = group, "revision"
                reason = (
                    f"filename resolves to the same document ('{base}') with "
                    f"{similarity:.0%} overlap"
                )
                break

        if matched is None:
            groups.append({
                "id": f"g{len(groups) + 1:04d}",
                "hash": digest,
                "shingles": shingle_set,
                "simhash": hashes[candidate.key],
                "base": base,
                "representative": candidate,
                "members": [candidate],
                "relation": "",
                "reasons": {},
            })
            continue

        matched["members"].append(candidate)
        matched["reasons"][candidate.key] = (relation, reason)
        if not matched["relation"]:
            matched["relation"] = relation
        # Keep the richest copy as the representative, and re-key the group's
        # comparison state to it so later candidates compare against the copy
        # that actually survives.
        if _richness(candidate) > _richness(matched["representative"]):
            displaced = matched["representative"]
            # The displaced copy becomes a duplicate, so it needs its own
            # relation and reason. Without this it would fall through to the
            # default and report as a "revision" even when it was an exact
            # match, which is a misleading thing to tell a user.
            matched["reasons"][displaced.key] = (
                relation,
                f"{reason.split('(')[0].strip() or 'duplicate'}; "
                f"{candidate.path.name} was kept as the richer copy",
            )
            matched["representative"] = candidate
            matched["hash"] = digest
            matched["shingles"] = shingle_set
            matched["simhash"] = hashes[candidate.key]

    for group in groups:
        representative = group["representative"]
        member_keys = [m.key for m in group["members"]]
        result.groups.append(DedupGroup(
            group_id=group["id"],
            representative=representative.key,
            members=member_keys,
            relation=group["relation"],
        ))
        for member in group["members"]:
            if member.key == representative.key:
                result.members[member.key] = DedupMember(
                    key=member.key, group_id=group["id"], role="representative",
                    reason=(
                        f"richest of {len(member_keys)} copies"
                        if len(member_keys) > 1 else ""
                    ),
                )
                continue
            relation, reason = group["reasons"].get(member.key, ("revision", ""))
            result.members[member.key] = DedupMember(
                key=member.key, group_id=group["id"], role="duplicate",
                relation=relation,
                reason=reason or f"duplicate of {representative.path.name}",
            )
            if relation == "exact":
                result.exact_duplicates += 1
            elif relation == "cross_format":
                result.cross_format_duplicates += 1
            else:
                result.revision_duplicates += 1

    return result
