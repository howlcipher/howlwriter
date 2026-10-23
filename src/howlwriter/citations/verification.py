"""Bibliographic verification: does a citation's metadata match authoritative records?

A DOI that resolves does not show that the formatted citation is right. This
module compares a Source's author, year, edition and title against one or more
canonical records and reports an explicit state. It is orthogonal to claim
support: VERIFIED says the bibliographic data matches, never that the source
backs any claim.

Records come from providers. A "publisher" record (the issuing body's own page
or document) outranks a "registry" record (Crossref, DataCite), because
registries are often thin or lag behind the publisher: Crossref can list an
organization where the document names eight people, or date a revision by its
update year. When records disagree with each other on a field the citation
depends on, the answer is NEEDS_REVIEW unless the citation matches the
higher-authority record, in which case the conflict is reported as a note.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Protocol

from howlwriter.citations.apa7 import _ORG_WORDS, _is_organizational
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source
from howlwriter.research.integrity import (
    SourceIntegrityVerifier,
    SSRFSecurityError,
    _compute_string_similarity,
    _normalize_title,
    crossref_works_url,
    normalize_doi,
)


class CitationState(str, enum.Enum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    INCOMPLETE = "INCOMPLETE"
    UNVERIFIABLE = "UNVERIFIABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


AUTHORITY_PUBLISHER = "publisher"
AUTHORITY_REGISTRY = "registry"
_AUTHORITY_RANK = {AUTHORITY_PUBLISHER: 2, AUTHORITY_REGISTRY: 1}

TITLE_MATCH_THRESHOLD = 0.85

# Finding codes.
AUTHOR_MISMATCH = "CITATION_AUTHOR_MISMATCH"
AUTHOR_TYPE_MISMATCH = "CITATION_AUTHOR_TYPE_MISMATCH"
YEAR_MISMATCH = "CITATION_YEAR_MISMATCH"
EDITION_MISMATCH = "CITATION_EDITION_MISMATCH"
TITLE_MISMATCH = "CITATION_TITLE_MISMATCH"
DOI_MISMATCH = "CITATION_DOI_MISMATCH"
RECORDS_CONFLICT = "CITATION_RECORDS_CONFLICT"
METADATA_MISSING = "CITATION_METADATA_MISSING"
PROVIDER_UNAVAILABLE = "CITATION_PROVIDER_UNAVAILABLE"
NO_RECORD = "CITATION_NO_AUTHORITATIVE_RECORD"
RECORD_THIN = "CITATION_RECORD_INCOMPLETE"
IDENTIFIER_MISMATCH = "CITATION_IDENTIFIER_MISMATCH"
YEAR_UNCERTAIN = "CITATION_YEAR_UNCERTAIN"
SOURCE_WITHDRAWN = "CITATION_SOURCE_WITHDRAWN"
SOURCE_SUPERSEDED = "CITATION_SOURCE_SUPERSEDED"
EDITION_NOT_STATED = "CITATION_EDITION_NOT_STATED"


@dataclass
class CanonicalAuthor(DataClassSerializationMixin):
    family: str = ""
    given: str = ""
    organization: str = ""

    @property
    def is_organization(self) -> bool:
        return bool(self.organization) and not self.family


@dataclass
class CanonicalRecord(DataClassSerializationMixin):
    """Bibliographic metadata as an authority states it."""

    provider: str
    authority: str = AUTHORITY_REGISTRY
    title: str = ""
    authors: list[CanonicalAuthor] = field(default_factory=list)
    year: int | None = None
    # Where the year comes from: "cite_as" (the publisher's own how-to-cite statement),
    # "cover" (a date printed on the document), "registry" (a DOI registry deposit).
    # Only a cite_as year can settle a disagreement between records.
    year_source: str = ""
    edition: str = ""
    identifier: str = ""  # the publisher's own identifier, e.g. a report number
    doi: str = ""
    url: str = ""
    # Distinct dated events, never merged into one "date": published, revised,
    # updated, withdrawn (ISO dates or years as the authority states them).
    dates: dict[str, str] = field(default_factory=dict)
    status: str = ""  # current | superseded | withdrawn | ""
    note: str = ""

    @property
    def author_kind(self) -> str:
        if not self.authors:
            return "unknown"
        return "organization" if all(a.is_organization for a in self.authors) else "individual"


@dataclass
class CitationFinding(DataClassSerializationMixin):
    code: str
    field: str
    message: str
    severity: str = "warning"  # "error" | "warning" | "info"
    provider: str = ""


@dataclass
class CitationVerification(DataClassSerializationMixin):
    source_id: str
    title: str
    state: CitationState
    findings: list[CitationFinding] = field(default_factory=list)
    records: list[CanonicalRecord] = field(default_factory=list)
    # field -> {"value": ..., "provider": ..., "authority": ..., "basis": ...}: where each
    # resolved bibliographic value came from, so a reader can see why a year was accepted.
    resolved: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "state": self.state.value,
            "providers": [r.provider for r in self.records],
            "resolved": self.resolved,
            "findings": [
                {"code": f.code, "field": f.field, "severity": f.severity, "message": f.message}
                for f in self.findings
            ],
        }


class ProviderUnavailable(Exception):
    """A provider could not be reached. Never evidence that a citation is wrong."""


class RecordProvider(Protocol):
    name: str

    def fetch(self, source: Source) -> CanonicalRecord | None:
        """Return the record for this source, None if the provider has none.

        Raise ProviderUnavailable if the lookup could not be completed.
        """


# ---------------------------------------------------------------- helpers


def _ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _surname_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", _ascii_fold(name).lower())


def _source_authors(source: Source) -> list[CanonicalAuthor]:
    """Parse Source.authors into individual or organizational authors.

    Organizations are recognised by the same rules the APA formatter uses to leave them
    uninverted. "Family, G." and "Given Family" are people.
    """
    parsed: list[CanonicalAuthor] = []
    for raw in source.authors:
        raw = raw.strip()
        if not raw:
            continue
        if _is_organizational(raw) or any(t.strip('()[]{}:;,"\'').lower() in _ORG_WORDS for t in raw.split()):
            parsed.append(CanonicalAuthor(organization=raw))
        elif "," in raw:
            family, _, given = raw.partition(",")
            parsed.append(CanonicalAuthor(family=family.strip(), given=given.strip()))
        else:
            tokens = raw.split()
            if len(tokens) == 1 or len(tokens) > 4:
                parsed.append(CanonicalAuthor(organization=raw))
            else:
                parsed.append(CanonicalAuthor(family=tokens[-1], given=" ".join(tokens[:-1])))
    return parsed


def _initial(given: str) -> str:
    folded = _ascii_fold(given).lower()
    m = re.search(r"[a-z]", folded)
    return m.group(0) if m else ""


def _org_tokens(name: str) -> frozenset[str]:
    return frozenset(_normalize_title(name).split())


def _same_organization(a: str, b: str) -> bool:
    """Token overlap, not substring: "Institute" is not "National Institute of Standards"."""
    ta, tb = _org_tokens(a), _org_tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.75


_ORDINAL_WORDS = {w: i for i, w in enumerate(
    ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth'), 1)}


def edition_tokens(*texts: str, doi: str = "") -> set[str]:
    """Edition markers in titles and identifiers, e.g. {"rev1", "update1", "1.0"}.

    Dotted versions are read from titles only; a DOI prefix such as 10.6028 is
    not a version, so DOIs contribute revision and update markers alone.
    """
    tokens: set[str] = set()
    for text in texts:
        if not text:
            continue
        for rev in re.finditer(r"\brev(?:ision|\.)?\s*(\d+)", text, re.IGNORECASE):
            tokens.add("rev" + rev.group(1))
        for upd in re.finditer(r"\bupdate\s*(\d+)", text, re.IGNORECASE):
            tokens.add("update" + upd.group(1))
        for ver in re.finditer(r"\b(\d+\.\d+(?:\.\d+)*)\b", text):
            tokens.add(ver.group(1))
        for ordinal in re.finditer(r"\b(\d+)(?:st|nd|rd|th)\s+ed(?:ition|\.)?", text, re.IGNORECASE):
            tokens.add("ed" + ordinal.group(1))
        for word in re.finditer(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+ed(?:ition|\.)?",
                                text, re.IGNORECASE):
            tokens.add("ed" + str(_ORDINAL_WORDS[word.group(1).lower()]))
    if doi:
        for rev in re.finditer(r"(?<=\d)r(\d+)(?![\d.])", doi, re.IGNORECASE):
            tokens.add("rev" + rev.group(1))
        for upd in re.finditer(r"upd(\d+)", doi, re.IGNORECASE):
            tokens.add("update" + upd.group(1))
    return tokens


def _source_year(source: Source) -> int | None:
    return source.publication_date.year if source.publication_date else None


def _source_edition_tokens(source: Source) -> set[str]:
    return edition_tokens(source.title, source.freshness.source_version or "", doi=source.doi or "")


# ------------------------------------------------------------- comparison


def _norm_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _strip_designator(title: str) -> str:
    """Drop a trailing parenthetical such as a report number: "(NIST SP 800-161 Rev. 1)"."""
    stripped = re.sub(r"\s*\([^()]*\)\s*$", "", title).strip()
    return stripped or title


def _title_similarity(cited: str, recorded: str) -> float:
    """Best similarity over the titles with and without a trailing designator.

    APA appends the report number to a title in parentheses; a record usually
    carries the bare title, so a designator must not count as a mismatch.
    """
    return max(
        _compute_string_similarity(_normalize_title(a), _normalize_title(b))
        for a in {cited, _strip_designator(cited)}
        for b in {recorded, _strip_designator(recorded)}
    )


def _compare_to_record(source: Source, record: CanonicalRecord) -> list[CitationFinding]:
    """Field-level disagreements between a source's citation data and one record."""
    findings: list[CitationFinding] = []
    where = record.provider

    # Authors.
    cited = _source_authors(source)
    if cited and record.authors:
        cited_kind = "organization" if all(a.is_organization for a in cited) else "individual"
        if cited_kind != record.author_kind:
            findings.append(CitationFinding(
                AUTHOR_TYPE_MISMATCH, "authors",
                f"Cited as {cited_kind} author but {where} lists {record.author_kind} author(s): "
                + "; ".join(a.organization or f"{a.family}, {a.given}".strip(", ") for a in record.authors),
                "error", where))
        elif cited_kind == "individual":
            cited_keys = [_surname_key(a.family) for a in cited]
            record_keys = [_surname_key(a.family) for a in record.authors]
            if cited_keys == record_keys:
                for c_author, r_author in zip(cited, record.authors):
                    ci, ri = _initial(c_author.given), _initial(r_author.given)
                    if ci and ri and ci != ri:
                        findings.append(CitationFinding(
                            AUTHOR_MISMATCH, "authors",
                            f"Given name or initial differs for {c_author.family}: cited "
                            f"'{c_author.given}' vs {where} '{r_author.given}'.", "error", where))
            if cited_keys != record_keys:
                missing = [k for k in record_keys if k not in cited_keys]
                extra = [k for k in cited_keys if k not in record_keys]
                detail = []
                if missing:
                    detail.append("missing " + ", ".join(missing))
                if extra:
                    detail.append("not in record: " + ", ".join(extra))
                if not detail:
                    detail.append("different order")
                findings.append(CitationFinding(
                    AUTHOR_MISMATCH, "authors",
                    f"Author list differs from {where} ({'; '.join(detail)}).", "error", where))
        else:
            if not any(_same_organization(c.organization, r.organization)
                       for c in cited for r in record.authors):
                findings.append(CitationFinding(
                    AUTHOR_MISMATCH, "authors",
                    f"Organizational author differs from {where}.", "error", where))

    # Year.
    cited_year = _source_year(source)
    if cited_year is not None and record.year is not None and cited_year != record.year:
        findings.append(CitationFinding(
            YEAR_MISMATCH, "publication_date",
            f"Cited year {cited_year} differs from {where} year {record.year}.", "error", where))

    # Edition: only compare when both sides state one.
    record_ed = edition_tokens(record.edition, record.title, doi=record.doi)
    cited_ed = _source_edition_tokens(source)
    if record_ed and cited_ed and record_ed != cited_ed:
        findings.append(CitationFinding(
            EDITION_MISMATCH, "edition",
            f"Edition markers differ: cited {sorted(cited_ed)} vs {where} {sorted(record_ed)}.",
            "error", where))
    elif record_ed and not cited_ed:
        findings.append(CitationFinding(
            EDITION_NOT_STATED, "edition",
            f"The citation states no edition, but {where} identifies this work as {sorted(record_ed)}.",
            "warning", where))

    # Title.
    if source.title and record.title:
        similarity = _title_similarity(source.title, record.title)
        if similarity < TITLE_MATCH_THRESHOLD:
            findings.append(CitationFinding(
                TITLE_MISMATCH, "title",
                f"Cited title does not match {where} title (similarity {similarity:.2f}).",
                "error", where))

    # Publisher identifier (e.g. a report number) against the source's own.
    cited_id = _norm_identifier(source.freshness.document_identifier or "")
    if cited_id and record.identifier and cited_id != _norm_identifier(record.identifier):
        findings.append(CitationFinding(
            IDENTIFIER_MISMATCH, "identifier",
            f"Cited identifier '{source.freshness.document_identifier}' differs from {where} "
            f"identifier '{record.identifier}'.", "error", where))

    # DOI.
    if source.doi and record.doi and normalize_doi(source.doi).lower() != normalize_doi(record.doi).lower():
        findings.append(CitationFinding(
            DOI_MISMATCH, "doi",
            f"Cited DOI differs from the DOI in the {where} record.", "error", where))
    return findings


def _thin_record_notes(record: CanonicalRecord) -> list[CitationFinding]:
    """Flag records too sparse to confirm what they were asked to confirm."""
    missing = []
    if not record.authors:
        missing.append("authors")
    if record.year is None:
        missing.append("year")
    if not record.title:
        missing.append("title")
    if not missing:
        return []
    return [CitationFinding(RECORD_THIN, "record",
                            f"{record.provider} record lacks {', '.join(missing)}.", "info", record.provider)]


def _missing_fields(source: Source) -> list[str]:
    missing = []
    if not source.title:
        missing.append("title")
    if not source.authors:
        missing.append("authors")
    if source.publication_date is None:
        missing.append("publication_date")
    if not (source.doi or source.url):
        missing.append("doi_or_url")
    return missing


_REVIEW_ONLY_CODES = {EDITION_NOT_STATED}
_DEPENDENT_CODES = {IDENTIFIER_MISMATCH, AUTHOR_MISMATCH, AUTHOR_TYPE_MISMATCH, YEAR_MISMATCH, EDITION_MISMATCH,
                    TITLE_MISMATCH, DOI_MISMATCH}


def verify_citation(
    source: Source,
    records: list[CanonicalRecord],
    unavailable: list[str] | None = None,
) -> CitationVerification:
    """Decide the state of one citation from the records gathered for it."""
    result = _decide(source, records, unavailable)
    if not result.resolved and records:
        result.resolved = _resolved_fields(source, records)
    return result


def _decide(
    source: Source,
    records: list[CanonicalRecord],
    unavailable: list[str] | None = None,
) -> CitationVerification:
    unavailable = unavailable or []
    findings: list[CitationFinding] = []

    missing = _missing_fields(source)
    if missing:
        findings.append(CitationFinding(
            METADATA_MISSING, "source", "Source lacks " + ", ".join(missing) + ".", "error"))
        return CitationVerification(source.id, source.title, CitationState.INCOMPLETE, findings, records)

    for name in unavailable:
        findings.append(CitationFinding(
            PROVIDER_UNAVAILABLE, "provider",
            f"{name} could not be reached; this is not evidence the citation is wrong.", "info", name))

    if not records:
        findings.append(CitationFinding(NO_RECORD, "source", "No authoritative record was retrieved.", "info"))
        return CitationVerification(source.id, source.title, CitationState.UNVERIFIABLE, findings, records)

    per_record = {id(r): _compare_to_record(source, r) for r in records}
    for r in records:
        findings.extend(_thin_record_notes(r))

    def rank(r: CanonicalRecord) -> int:
        return _AUTHORITY_RANK.get(r.authority, 0)

    # The most authoritative record *for each field* decides that field. A publisher record that
    # states no year cannot vouch for a year; the best record that does state it decides.
    field_rank = {fld: max((rank(r) for r in records if _has_field(r, fld)), default=0) for fld in _FIELDS}
    review_findings = [f for r in records for f in per_record[id(r)] if f.code in _REVIEW_ONLY_CODES]
    decisive = [(r, f) for r in records for f in per_record[id(r)]
                if f.code not in _REVIEW_ONLY_CODES and rank(r) == field_rank.get(f.field, 0)]
    top_findings = [f for _, f in decisive]
    top_names = sorted({r.provider for r, _ in decisive})
    disputed_fields = {f.field for f in top_findings}

    # Do the records disagree among themselves on a field the citation depends on?
    conflicts: list[CitationFinding] = []
    for r in records:
        for f in per_record[id(r)]:
            if (f.code in _DEPENDENT_CODES and f.code not in _REVIEW_ONLY_CODES
                    and rank(r) < field_rank.get(f.field, 0) and f.code not in {x.code for x in top_findings}):
                conflicts.append(CitationFinding(
                    RECORDS_CONFLICT, f.field,
                    f"{r.provider} disagrees with the citation on {f.field}, but a higher-authority record "
                    f"agrees with it: {f.message}", "info", r.provider))

    if top_findings:
        # If a lower-authority record agrees with the citation on a disputed field, the
        # authorities conflict, so human judgment is required.
        agreeing = [r for r in records
                    if any(_has_field(r, fld) and rank(r) < field_rank[fld] for fld in disputed_fields)
                    and not any(f.field in disputed_fields for f in per_record[id(r)])]
        findings.extend(top_findings)
        if agreeing:
            findings.append(CitationFinding(
                RECORDS_CONFLICT, "records",
                "Records disagree: " + ", ".join(r.provider for r in agreeing)
                + " support the citation but " + ", ".join(top_names) + " do not.", "warning"))
            state = CitationState.NEEDS_REVIEW
        else:
            state = CitationState.MISMATCH
        return CitationVerification(source.id, source.title, state, findings, records)

    findings.extend(conflicts)

    # A year the records disagree about is never settled silently. It is accepted only when
    # the citation matches a year the publisher itself states as the way to cite the work.
    years = {r.provider: r.year for r in records if r.year is not None}
    if len(set(years.values())) > 1:
        citing = [r for r in records if r.year == _source_year(source)]
        authoritative = [r for r in citing if r.year_source == "cite_as"]
        if not authoritative:
            findings.append(CitationFinding(
                YEAR_UNCERTAIN, "publication_date",
                "Records give different years (" + ", ".join(f"{k}: {v}" for k, v in sorted(years.items()))
                + ") and no publisher cite-as statement settles it; choose the year deliberately.",
                "warning"))
            return CitationVerification(source.id, source.title, CitationState.NEEDS_REVIEW, findings,
                                        records, _resolved_fields(source, records))

    # Withdrawn or superseded works are cited knowingly or not at all.
    for r in records:
        if r.status == "withdrawn":
            findings.append(CitationFinding(
                SOURCE_WITHDRAWN, "status", f"{r.provider} reports this work is withdrawn.", "warning", r.provider))
        elif r.status == "superseded":
            findings.append(CitationFinding(
                SOURCE_SUPERSEDED, "status", f"{r.provider} reports a newer edition supersedes this work.",
                "info", r.provider))
    if any(f.code == SOURCE_WITHDRAWN for f in findings):
        return CitationVerification(source.id, source.title, CitationState.NEEDS_REVIEW, findings, records,
                                    _resolved_fields(source, records))

    # No hard disagreement with the best record. A record that cannot test authors or year
    # leaves the citation unconfirmed on those fields.
    confirmed_authors = any(r.authors for r in records)
    confirmed_year = any(r.year is not None for r in records)
    if not (confirmed_authors and confirmed_year):
        findings.append(CitationFinding(
            RECORD_THIN, "record",
            "Records could not confirm "
            + " or ".join(n for n, ok in (("authors", confirmed_authors), ("year", confirmed_year)) if not ok)
            + ".", "warning"))
        return CitationVerification(source.id, source.title, CitationState.NEEDS_REVIEW, findings, records,
                                    _resolved_fields(source, records))
    if review_findings:
        findings.extend(review_findings)
        return CitationVerification(source.id, source.title, CitationState.NEEDS_REVIEW, findings, records,
                                    _resolved_fields(source, records))
    return CitationVerification(source.id, source.title, CitationState.VERIFIED, findings, records,
                                _resolved_fields(source, records))


_FIELDS = ("authors", "publication_date", "title", "edition", "identifier", "doi")


def _has_field(record: CanonicalRecord, fld: str) -> bool:
    if fld == "authors":
        return bool(record.authors)
    if fld == "publication_date":
        return record.year is not None
    if fld == "title":
        return bool(record.title)
    if fld == "edition":
        return bool(edition_tokens(record.edition, record.title, doi=record.doi))
    if fld == "identifier":
        return bool(record.identifier)
    if fld == "doi":
        return bool(record.doi)
    return False


def _resolved_fields(source: Source, records: list[CanonicalRecord]) -> dict[str, dict[str, Any]]:
    """For each field, the value the citation was checked against and who stated it."""
    ranked = sorted(records, key=lambda r: -_AUTHORITY_RANK.get(r.authority, 0))
    resolved: dict[str, dict[str, Any]] = {}
    for r in ranked:
        if r.year is not None and "year" not in resolved:
            resolved["year"] = {"value": r.year, "provider": r.provider, "authority": r.authority,
                                "basis": r.year_source or "unspecified"}
        if r.authors and "authors" not in resolved:
            resolved["authors"] = {"value": [a.organization or f"{a.family}, {a.given}".strip(", ")
                                             for a in r.authors],
                                   "provider": r.provider, "authority": r.authority, "basis": "record"}
        if r.title and "title" not in resolved:
            resolved["title"] = {"value": r.title, "provider": r.provider, "authority": r.authority,
                                 "basis": "record"}
        if r.doi and "doi" not in resolved:
            resolved["doi"] = {"value": normalize_doi(r.doi), "provider": r.provider, "authority": r.authority,
                               "basis": "record"}
        if r.identifier and "identifier" not in resolved:
            resolved["identifier"] = {"value": r.identifier, "provider": r.provider, "authority": r.authority,
                                      "basis": "record"}
        if r.dates and "dates" not in resolved:
            resolved["dates"] = {"value": dict(r.dates), "provider": r.provider, "authority": r.authority,
                                 "basis": "record"}
    return resolved


# --------------------------------------------------------------- providers


class RecordFileProvider:
    """Canonical records supplied or recorded in a JSON file.

    Used for publisher records that have no stable API (an issuing body's
    publication page or document cover), and for offline or recorded runs.
    The file is a list of records, each with at least "provider" and one of
    "doi" or "url" to key on.
    """

    def __init__(self, path: str | Path, name: str | None = None) -> None:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        records = raw["records"] if isinstance(raw, dict) else raw
        self._records = [_record_from_dict(r) for r in records]
        self.name = name or "records-file"

    def fetch(self, source: Source) -> CanonicalRecord | None:
        doi = normalize_doi(source.doi).lower() if source.doi else ""
        url = (source.url or "").rstrip("/").lower()
        for record in self._records:
            if doi and record.doi and normalize_doi(record.doi).lower() == doi:
                return record
            if url and record.url and record.url.rstrip("/").lower() == url:
                return record
        return None


def _record_from_dict(entry: dict) -> CanonicalRecord:
    authors = [CanonicalAuthor(**a) for a in entry.get("authors", [])]
    return CanonicalRecord(
        provider=entry.get("provider", "records-file"),
        authority=entry.get("authority", AUTHORITY_REGISTRY),
        title=entry.get("title", ""),
        authors=authors,
        year=entry.get("year"),
        year_source=entry.get("year_source", ""),
        identifier=entry.get("identifier", ""),
        dates=dict(entry.get("dates", {})),
        status=entry.get("status", ""),
        edition=entry.get("edition", ""),
        doi=entry.get("doi", ""),
        url=entry.get("url", ""),
        note=entry.get("note", ""),
    )


class CrossrefProvider:
    """Registry record from Crossref, fetched through the SSRF-safe client."""

    name = "crossref"

    def __init__(self, verifier: SourceIntegrityVerifier | None = None) -> None:
        self._verifier = verifier or SourceIntegrityVerifier()

    def fetch(self, source: Source) -> CanonicalRecord | None:
        if not source.doi:
            return None
        url = crossref_works_url(source.doi)
        if url is None:
            return None  # not a DOI; no request is made
        headers = {"User-Agent": "HowlWriter-CitationVerification/1.0"}
        try:
            with self._verifier._build_client() as client:
                response = client.get(url, headers=headers)
        except SSRFSecurityError as exc:
            raise ProviderUnavailable(f"blocked: {exc}") from exc
        except Exception as exc:  # network failure, timeout, TLS: not evidence about the citation
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ProviderUnavailable(f"HTTP {response.status_code}")
        try:
            message = response.json()["message"]
        except Exception as exc:
            raise ProviderUnavailable("unparseable response") from exc
        return crossref_message_to_record(message)


def crossref_message_to_record(message: dict) -> CanonicalRecord:
    authors: list[CanonicalAuthor] = []
    for a in message.get("author", []) or []:
        if a.get("family"):
            authors.append(CanonicalAuthor(family=a["family"], given=a.get("given", "")))
        elif a.get("name"):
            authors.append(CanonicalAuthor(organization=a["name"]))
    parts = ((message.get("issued") or message.get("published") or {}).get("date-parts") or [[None]])[0]
    year = parts[0] if parts and isinstance(parts[0], int) else None
    titles = message.get("title") or []
    return CanonicalRecord(
        provider="crossref", authority=AUTHORITY_REGISTRY,
        title=titles[0] if titles else "", authors=authors, year=year,
        doi=message.get("DOI", ""), url=message.get("URL", ""))


def verify_sources(
    sources: list[Source],
    providers: list[RecordProvider],
) -> list[CitationVerification]:
    """Gather records per source from every provider and decide each citation."""
    results: list[CitationVerification] = []
    for source in sources:
        records: list[CanonicalRecord] = []
        unavailable: list[str] = []
        for provider in providers:
            try:
                record = provider.fetch(source)
            except ProviderUnavailable:
                unavailable.append(provider.name)
                continue
            if record is not None:
                records.append(record)
        results.append(verify_citation(source, records, unavailable))
    return results


def worst_state(results: list[CitationVerification]) -> CitationState:
    """Aggregate: MISMATCH > NEEDS_REVIEW > INCOMPLETE > UNVERIFIABLE > VERIFIED.

    Nothing to aggregate is not "verified": an empty list is UNVERIFIABLE.
    """
    if not results:
        return CitationState.UNVERIFIABLE
    order = [CitationState.MISMATCH, CitationState.NEEDS_REVIEW, CitationState.INCOMPLETE,
             CitationState.UNVERIFIABLE, CitationState.VERIFIED]
    for state in order:
        if any(r.state == state for r in results):
            return state
    return CitationState.VERIFIED
