"""One source, one set of metadata, across every document in an assignment.

Documents in a bundle cite the same works. If one says (2022) and another (2024)
for the same DOI, one of them is wrong, and fixing a source in one place must
show which other documents are affected. The registry reads the reference list
of each document, groups entries by the work they identify, and reports any work
whose documents disagree. Distinct editions stay distinct: they have different
identifiers (a DOI) or carry edition markers in the title.

It reports; it never edits a document. Citation formatting stays per document.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.citations.revalidation import ReferenceEntry, parse_references
from howlwriter.citations.verification import CitationVerification, edition_tokens
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.research.integrity import _compute_string_similarity, _normalize_title, normalize_doi

CROSS_DOC_YEAR_CONFLICT = "CROSS_DOCUMENT_YEAR_CONFLICT"
CROSS_DOC_DOI_CONFLICT = "CROSS_DOCUMENT_DOI_CONFLICT"
CROSS_DOC_AUTHOR_CONFLICT = "CROSS_DOCUMENT_AUTHOR_CONFLICT"
DISAGREES_WITH_RECORD = "DOCUMENT_DISAGREES_WITH_VERIFIED_RECORD"

_TITLE_SAME = 0.9


@dataclass
class Appearance(DataClassSerializationMixin):
    document: str
    year: str
    lead: str
    doi: str
    title: str
    raw: str


@dataclass
class RegistryFinding(DataClassSerializationMixin):
    code: str
    message: str
    documents: list[str] = field(default_factory=list)
    key: str = ""


@dataclass
class RegistryEntry(DataClassSerializationMixin):
    key: str
    appearances: list[Appearance] = field(default_factory=list)
    resolved: dict[str, dict] = field(default_factory=dict)  # from a verification, when supplied

    @property
    def documents(self) -> list[str]:
        return sorted({a.document for a in self.appearances})


def _identity(entry: ReferenceEntry) -> str:
    if entry.doi:
        return "doi:" + normalize_doi(entry.doi).lower()
    if entry.url:
        return "url:" + entry.url.rstrip("/").lower()
    return ""


class SourceRegistry:
    def __init__(self) -> None:
        self._entries: list[RegistryEntry] = []

    @property
    def entries(self) -> list[RegistryEntry]:
        return self._entries

    def register_document(self, document: str, text: str) -> None:
        """Add every reference entry of one document."""
        for ref in parse_references(text):
            appearance = Appearance(document, ref.year, ref.lead, ref.doi, ref.title, ref.raw)
            target = self._match(ref)
            if target is None:
                self._entries.append(RegistryEntry(_identity(ref) or f"work:{ref.lead}:{_normalize_title(ref.title)[:40]}",
                                                   [appearance]))
            else:
                target.appearances.append(appearance)

    def _match(self, ref: ReferenceEntry) -> RegistryEntry | None:
        ident = _identity(ref)
        for entry in self._entries:
            first = entry.appearances[0]
            if ident and ident == (("doi:" + normalize_doi(first.doi).lower()) if first.doi else ""):
                return entry
            if ident and entry.key == ident:
                return entry
            if not ident and not first.doi and first.lead == ref.lead and ref.title and first.title and (
                    _compute_string_similarity(_normalize_title(first.title), _normalize_title(ref.title)) >= _TITLE_SAME
                    and edition_tokens(first.title) == edition_tokens(ref.title)):
                return entry
        return None

    def conflicts(self) -> list[RegistryFinding]:
        findings: list[RegistryFinding] = []
        for entry in self._entries:
            years = {a.year for a in entry.appearances}
            if len(years) > 1:
                by_year = {y: sorted({a.document for a in entry.appearances if a.year == y}) for y in sorted(years)}
                findings.append(RegistryFinding(
                    CROSS_DOC_YEAR_CONFLICT,
                    "The same work is cited with different years: "
                    + "; ".join(f"{y} in {', '.join(d)}" for y, d in by_year.items())
                    + ". Unless these are different editions with different identifiers, one is wrong.",
                    entry.documents, entry.key))
            leads = {a.lead for a in entry.appearances}
            if len(leads) > 1:
                findings.append(RegistryFinding(
                    CROSS_DOC_AUTHOR_CONFLICT,
                    "The same work is credited to different lead authors: " + ", ".join(sorted(leads)) + ".",
                    entry.documents, entry.key))
        # The same title and lead under different DOIs, same year: likely a mistyped identifier.
        for i, a in enumerate(self._entries):
            for b in self._entries[i + 1:]:
                fa, fb = a.appearances[0], b.appearances[0]
                if (fa.lead == fb.lead and fa.title and fb.title and fa.doi and fb.doi and fa.doi != fb.doi
                        and edition_tokens(fa.title, doi=fa.doi) == edition_tokens(fb.title, doi=fb.doi)
                        and _compute_string_similarity(_normalize_title(fa.title), _normalize_title(fb.title)) >= _TITLE_SAME
                        and fa.year == fb.year):
                    findings.append(RegistryFinding(
                        CROSS_DOC_DOI_CONFLICT,
                        f"Two DOIs are given for what looks like one edition: {fa.doi} and {fb.doi}.",
                        sorted(set(a.documents + b.documents)), a.key))
        return findings

    def apply_verifications(self, verifications: list[CitationVerification]) -> list[RegistryFinding]:
        """Attach verified metadata to entries and flag documents that disagree with it."""
        findings: list[RegistryFinding] = []
        for v in verifications:
            doi = (v.resolved.get("doi") or {}).get("value", "")
            year = (v.resolved.get("year") or {}).get("value")
            for entry in self._entries:
                if not doi or entry.key != "doi:" + normalize_doi(str(doi)).lower():
                    continue
                entry.resolved = v.resolved
                if year is not None:
                    wrong = sorted({a.document for a in entry.appearances if a.year != str(year)})
                    if wrong:
                        findings.append(RegistryFinding(
                            DISAGREES_WITH_RECORD,
                            f"Verified record year is {year} ({v.resolved['year'].get('basis')}, "
                            f"{v.resolved['year'].get('provider')}), but these documents differ.", wrong, entry.key))
        return findings

    def documents_citing(self, key: str) -> list[str]:
        """Every document affected if the metadata for this work changes."""
        for entry in self._entries:
            if entry.key == key:
                return entry.documents
        return []


def _norm_doi_key(doi: str) -> str:
    return "doi:" + normalize_doi(doi).lower() if doi else ""


def build_registry(documents: dict[str, str]) -> SourceRegistry:
    registry = SourceRegistry()
    for name in sorted(documents):
        registry.register_document(name, documents[name])
    return registry
