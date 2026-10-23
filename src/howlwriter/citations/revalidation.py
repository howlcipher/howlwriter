"""Re-check citations after a document has been edited.

A citation verified during research can drift as the text is revised: a humanizer
drops a parenthetical, an editor changes a year, a reference is left behind when
its only citation is cut. This compares the text before and after a
transformation and reports every citation-level change, so a correction cannot
silently disappear and an editor cannot silently break one.

It reports; it never edits. A changed citation may be a correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.citations.extract import extract_in_text_citations
from howlwriter.domain.sentences import split_sentences
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.research.integrity import _compute_string_similarity, _normalize_title

CITATION_REMOVED = "CITATION_REMOVED"
CITATION_ADDED = "CITATION_ADDED"
CITATION_YEAR_CHANGED = "CITATION_YEAR_CHANGED"
CITATION_STRIPPED_FROM_CLAIM = "CITATION_STRIPPED_FROM_CLAIM"
CLAIM_REMOVED = "CITED_CLAIM_REMOVED"
REFERENCE_ORPHANED = "REFERENCE_ORPHANED"
REFERENCE_MISSING = "REFERENCE_MISSING"
REFERENCE_CHANGED = "REFERENCE_CHANGED"
REFERENCE_INCONSISTENT_WITH_CITATION = "REFERENCE_INCONSISTENT_WITH_CITATION"
REFERENCE_SECTION_REMOVED = "REFERENCE_SECTION_REMOVED"
CITATION_NAMES_CHANGED = "CITATION_NAMES_CHANGED"

_WORD = re.compile(r"[a-z0-9]+")
_DOI = re.compile(r"10\.\d{4,9}/[^\s)]+", re.I)


@dataclass
class ReferenceEntry(DataClassSerializationMixin):
    raw: str
    lead: str  # first author or organization, lower-cased
    year: str
    doi: str = ""
    url: str = ""
    title: str = ""
    authors: str = ""  # the text before the year, normalized


@dataclass
class CitationChange(DataClassSerializationMixin):
    code: str
    message: str
    severity: str = "warning"  # "error" | "warning" | "info"
    before: str = ""
    after: str = ""


@dataclass
class CitationDelta(DataClassSerializationMixin):
    changes: list[CitationChange] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.changes

    @property
    def blocking(self) -> bool:
        return any(c.severity == "error" for c in self.changes)


def split_body_and_references(text: str) -> tuple[str, str]:
    m = re.search(r"(?:^|\n)(?:#{1,3}[ \t]*|\*\*[ \t]*)(?:References|Bibliography)(?:[ \t]*\*\*)?[ \t]*(?:\n|$)", text, re.I)
    return (text[: m.start()], text[m.end():]) if m else (text, "")


def _names_signature(names: str) -> str:
    """The author names a citation gives, without joiners: "Boyens & Paulsen" != "Boyens"."""
    return " ".join(t for t in _WORD.findall(names.lower()) if t not in {"and", "al", "et"})


def citation_key(names: str, year: str | None) -> tuple[str, str]:
    """(lead name, year): "Autio et al." and "Autio, Schwartz & Hall" are the same work."""
    tokens = _WORD.findall(names.lower())
    return (tokens[0] if tokens else "", year or "")


def parse_references(text: str) -> list[ReferenceEntry]:
    _, refs = split_body_and_references(text)
    entries: list[ReferenceEntry] = []
    for line in (ln.strip() for ln in refs.split("\n")):
        if not line:
            continue
        year = re.search(r"\((\d{4}[a-z]?|n\.d\.)\)", line)
        if not year:
            continue
        lead_tokens = _WORD.findall(line[: year.start()].lower())
        doi = _DOI.search(line)
        url = re.search(r"https?://\S+", line)
        after_year = line[year.end():].lstrip(". ").strip()
        title = re.sub(r"[*_]", "", re.split(r"(?<=[a-z0-9\)])\.\s", after_year, maxsplit=1)[0]).strip()
        entries.append(ReferenceEntry(
            raw=line, lead=lead_tokens[0] if lead_tokens else "", year=year.group(1), title=title,
            authors=" ".join(lead_tokens),
            doi=doi.group(0).rstrip(".,").lower() if doi else "",
            url=url.group(0).rstrip(".,") if url else ""))
    return entries


def _cited_sentences(body: str) -> dict[str, set[tuple[str, str]]]:
    out: dict[str, set[tuple[str, str]]] = {}
    for sentence in split_sentences(body):
        keys = {citation_key(c.names, c.year) for c in extract_in_text_citations(sentence) if c.source_id is None}
        out[sentence] = keys
    return out


def _stem_words(sentence: str) -> frozenset[str]:
    # Remove citations first so a change to the citation alone does not look like new wording.
    stripped = re.sub(r"\([^()]*\d{4}[^()]*\)", " ", sentence)
    return frozenset(w for w in _WORD.findall(stripped.lower()) if len(w) > 3)


def citation_delta(before: str, after: str) -> CitationDelta:
    """Citation-level differences between two versions of the same document."""
    b_body, _ = split_body_and_references(before)
    a_body, _ = split_body_and_references(after)
    changes: list[CitationChange] = []

    b_found = [c for c in extract_in_text_citations(b_body) if c.source_id is None]
    a_found = [c for c in extract_in_text_citations(a_body) if c.source_id is None]
    b_cites = {citation_key(c.names, c.year): c.raw for c in b_found}
    a_cites = {citation_key(c.names, c.year): c.raw for c in a_found}
    b_names = {citation_key(c.names, c.year): _names_signature(c.names) for c in b_found}
    a_names = {citation_key(c.names, c.year): _names_signature(c.names) for c in a_found}
    a_by_lead = {lead: (key, raw) for key, raw in a_cites.items() for lead in [key[0]]}
    b_by_lead = {key[0]: (key, raw) for key, raw in b_cites.items()}

    for key, raw in b_cites.items():
        if key in a_cites:
            continue
        counterpart = a_by_lead.get(key[0])
        if counterpart and counterpart[0][1] != key[1]:
            changes.append(CitationChange(
                CITATION_YEAR_CHANGED,
                f"Citation year changed for {key[0]}: {key[1]} -> {counterpart[0][1]}. If this is a correction, "
                "confirm it against the source record.", "warning", raw, counterpart[1]))
        else:
            changes.append(CitationChange(
                CITATION_REMOVED, f"Citation {raw} no longer appears in the text.", "error", raw, ""))
    for key, raw in a_cites.items():
        if key not in b_cites and key[0] not in b_by_lead:
            changes.append(CitationChange(CITATION_ADDED, f"Citation {raw} was added.", "warning", "", raw))
        elif key in b_cites and b_names.get(key) != a_names.get(key):
            changes.append(CitationChange(
                CITATION_NAMES_CHANGED,
                f"The authors named in the citation changed ({b_cites[key]} -> {raw}).", "warning", b_cites[key], raw))

    # A retained claim that lost its citation, or a cited claim that disappeared.
    b_sent = _cited_sentences(b_body)
    a_sent = _cited_sentences(a_body)
    a_words = {s: _stem_words(s) for s in a_sent}
    for sentence, keys in b_sent.items():
        if not keys:
            continue
        words = _stem_words(sentence)
        if len(words) < 4:
            continue
        best = max(a_sent, key=lambda s: len(words & a_words[s]) / max(len(words | a_words[s]), 1), default=None)
        overlap = len(words & a_words[best]) / max(len(words | a_words[best]), 1) if best else 0.0
        if best is not None and overlap >= 0.6:
            lost = keys - a_sent[best]
            if lost and not (a_sent[best] and {k[0] for k in a_sent[best]} >= {k[0] for k in lost}):
                changes.append(CitationChange(
                    CITATION_STRIPPED_FROM_CLAIM,
                    "A claim was kept but its citation was dropped.", "error", sentence[:140], best[:140]))
        else:
            changes.append(CitationChange(
                CLAIM_REMOVED, "A cited claim no longer appears; check nothing it supported depends on it.",
                "info", sentence[:140], ""))

    # References against what is cited now.
    refs_after = parse_references(after)
    cited_leads = {k[0] for k in a_cites}
    # Text that cites by source id (S001) names no author, so reference leads cannot be matched to it.
    cites_by_id = any(c.source_id for c in extract_in_text_citations(a_body))
    for entry in refs_after:
        if entry.lead and entry.lead not in cited_leads and not cites_by_id:
            changes.append(CitationChange(
                REFERENCE_ORPHANED, "A reference is listed that nothing in the text cites.", "warning", "", entry.raw[:140]))
    refs_before_all = parse_references(before)
    if refs_before_all and not refs_after and a_cites:
        changes.append(CitationChange(
            REFERENCE_SECTION_REMOVED,
            f"The reference list is gone ({len(refs_before_all)} entries before) while the text still cites "
            f"{len(a_cites)} source(s).", "error", refs_before_all[0].raw[:140], ""))
    ref_by_lead: dict[str, list[ReferenceEntry]] = {}
    for entry in refs_after:
        ref_by_lead.setdefault(entry.lead, []).append(entry)
    for key, raw in a_cites.items():
        entries = ref_by_lead.get(key[0])
        if refs_after and not entries and not cites_by_id:
            changes.append(CitationChange(
                REFERENCE_MISSING, f"Citation {raw} has no reference entry.", "error", raw, ""))
        elif entries and key[1] and all(e.year != key[1] for e in entries):
            changes.append(CitationChange(
                REFERENCE_INCONSISTENT_WITH_CITATION,
                f"Citation {raw} and its reference entry disagree on the year ({entries[0].year}).",
                "error", raw, entries[0].raw[:140]))

    # A reference entry that changed between versions. The prior entry is the one by the same lead
    # with the most similar title, so several works by one author are not confused.
    prior_by_lead: dict[str, list[ReferenceEntry]] = {}
    for e in refs_before_all:
        if e.lead:
            prior_by_lead.setdefault(e.lead, []).append(e)
    for entry in refs_after:
        candidates = prior_by_lead.get(entry.lead)
        if not candidates:
            continue
        prior = max(candidates, key=lambda c: _compute_string_similarity(_normalize_title(c.title), _normalize_title(entry.title)))
        what = []
        if prior.year != entry.year:
            what.append(f"year {prior.year} -> {entry.year}")
        if prior.doi != entry.doi:
            what.append("DOI " + ("removed" if prior.doi and not entry.doi else "added" if entry.doi and not prior.doi
                                  else "changed"))
        if prior.authors and entry.authors and prior.authors != entry.authors:
            what.append("authors")
        if prior.title and entry.title and _compute_string_similarity(
                _normalize_title(prior.title), _normalize_title(entry.title)) < 0.9:
            what.append("title or edition")
        if what:
            changes.append(CitationChange(
                REFERENCE_CHANGED, "A reference entry changed: " + ", ".join(what) + ".", "warning",
                prior.raw[:140], entry.raw[:140]))
    return CitationDelta(changes)
