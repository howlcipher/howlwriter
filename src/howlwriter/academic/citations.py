"""APA 7 in-text citation extraction, reference matching, and bibliography construction."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.citations.apa7 import APA7Formatter, CitationWarning
from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source


_YEAR_TOKEN = re.compile(r"\b(\d{4}[a-z]?|n\.d\.)\b")
_WORD_TOKEN = re.compile(r"[a-z]+")
_PARENTHETICAL_GROUP = re.compile(r"\(([^()\n]{3,300})\)")
# Narrative form: Author (2024), Author et al. (2024a), Author (2024, p. 12).
_NARRATIVE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z'-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z'-]+|\s+et\s+al\.)?)"
    r"\s+\((\d{4}[a-z]?|n\.d\.)(?:,\s*[^()\n]{0,40})?\)"
)
_SOURCE_ID_PATTERN = re.compile(r"\b(S\d{3})\b")
# Parentheticals that carry a year but are not citations.
_NON_CITATION_LEADS = (
    "see", "e.g", "i.e", "cf", "figure", "fig", "table", "section", "chapter",
    "appendix", "eq", "equation", "note", "compare", "as of", "since", "until",
)


def _looks_like_citation(segment: str) -> bool:
    """Does this parenthetical segment read as an APA in-text citation?

    It must carry a year and open with a name or a quoted short title. The
    lead-word exclusions keep asides like "(see Figure 2, 2024)" from being
    reported as unresolvable citations.
    """
    if not _YEAR_TOKEN.search(segment):
        return False
    stripped = segment.lstrip("\u201c\u2018\"'")
    if not stripped[:1].isupper():
        return False
    lead = stripped.split(",")[0].split()[0].rstrip(".").lower() if stripped.split() else ""
    return lead not in _NON_CITATION_LEADS


CITATION_UNRESOLVED = "CITATION_UNRESOLVED"
CITATION_NO_IN_TEXT_CITATIONS = "CITATION_NO_IN_TEXT_CITATIONS"


@dataclass
class _InTextCitation:
    """One in-text citation, kept in the structured form needed to resolve it."""

    raw: str
    names: str
    year: str | None
    source_id: str | None = None


def _split_names_and_year(raw: str) -> tuple[str, str | None]:
    """Split a parenthetical citation body into its name part and its year.

    The year is located by pattern rather than by position so a pinpoint
    locator ("Rose, 2020, p. 15") does not get read as the year, which would
    make a perfectly good citation look unresolvable.
    """
    match = _YEAR_TOKEN.search(raw)
    if match is None:
        return raw.strip(), None
    names = raw[: match.start()].rstrip().rstrip(",").strip()
    return names, match.group(1)


def _source_year(source: Source) -> str:
    return str(source.publication_date.year) if source.publication_date else "n.d."


def _citation_matches_source(citation: _InTextCitation, source: Source) -> bool:
    """Does this single in-text citation resolve to this source?

    Deliberately conservative: it answers "could a reader reasonably read this
    citation as pointing at this source", so a citation is only reported as
    unresolved when no collected source is a plausible referent. It is used
    only to detect unresolved citations and never to decide which sources are
    considered used, so it cannot change which entries reach the References
    page.
    """
    if citation.source_id is not None:
        return source.id == citation.source_id

    if citation.year is not None and citation.year != _source_year(source):
        return False

    names = citation.names.lower()
    if not names:
        return False

    name_tokens = set(_WORD_TOKEN.findall(names))
    if source.authors:
        for author in source.authors:
            surname = author.split(",")[0].split()[-1].strip().lower()
            # Whole-word only: "Rosen" must not resolve to "Rose".
            if surname and surname in name_tokens:
                return True
        return False

    title_keyword = source.title.split()[0].lower() if source.title else ""
    return len(title_keyword) > 4 and title_keyword in name_tokens


@dataclass
class CitationAnalysis(DataClassSerializationMixin):
    in_text_citation_count: int = 0
    used_sources: list[Source] = field(default_factory=list)
    unused_sources: list[Source] = field(default_factory=list)
    unmatched_in_text_citations: list[str] = field(default_factory=list)
    warnings: list[CitationWarning] = field(default_factory=list)
    references_section_text: str = ""


class AcademicCitationManager:
    """Manages APA 7 in-text citation matching and deterministic References section generation."""

    def __init__(self, formatter: APA7Formatter | None = None) -> None:
        self.formatter = formatter or APA7Formatter()

    def analyze_and_build_references(
        self,
        document: Document,
        available_sources: list[Source],
    ) -> CitationAnalysis:
        """Finds in-text citations in the paper, matches them to sources, and generates APA 7 References."""
        text = document.text

        raw_in_text: list[str] = []
        # Structured form of the same matches, used to check the opposite
        # direction: does each in-text citation resolve to a real source?
        extracted: list[_InTextCitation] = []

        for match in _PARENTHETICAL_GROUP.finditer(text):
            # One set of parentheses can hold several citations separated by
            # semicolons; each is its own citation and must resolve on its own.
            for segment in match.group(1).split(";"):
                segment = segment.strip()
                if not _looks_like_citation(segment):
                    continue
                raw_in_text.append(segment)
                names, year = _split_names_and_year(segment)
                extracted.append(
                    _InTextCitation(raw=segment, names=names, year=year)
                )

        for match in _NARRATIVE_PATTERN.finditer(text):
            names = match.group(1).strip()
            year = match.group(2).strip()
            raw = f"{names} ({year})"
            raw_in_text.append(raw)
            extracted.append(_InTextCitation(raw=raw, names=names, year=year))

        for match in _SOURCE_ID_PATTERN.finditer(text):
            raw = match.group(1).strip()
            raw_in_text.append(raw)
            extracted.append(
                _InTextCitation(raw=raw, names="", year=None, source_id=raw)
            )

        # Only sources that pass the relevance gate are eligible for use.
        eligible_sources = [s for s in available_sources if s.is_usable]

        used_sources: list[Source] = []
        unused_sources: list[Source] = []
        all_warnings: list[CitationWarning] = []

        # Both directions are decided by the same per-citation matcher. When a
        # source was matched by whole-text search while a citation was matched
        # per-citation, the two could disagree -- a source could be listed in
        # the References page while the only citation naming it was
        # simultaneously reported unresolvable, or a cited work could be left
        # out of the references entirely.
        for source in eligible_sources:
            if any(_citation_matches_source(c, source) for c in extracted):
                used_sources.append(source)
            else:
                unused_sources.append(source)

        # Build the References Section from the sources the paper actually
        # cites. APA 7 admits only cited works, so a paper that cites nothing
        # gets an empty page rather than a list of everything that was
        # retrieved -- publishing uncited works as references misrepresents
        # them as having supported the text.
        ref_page_result = self.formatter.reference_page(used_sources)
        all_warnings.extend(ref_page_result.warnings)
        if eligible_sources and not used_sources:
            all_warnings.append(
                CitationWarning(
                    code=CITATION_NO_IN_TEXT_CITATIONS,
                    field="references",
                    message=(
                        f"{len(eligible_sources)} source(s) were collected but "
                        "none are cited in the text, so the References page is "
                        "empty. Cite the sources you used."
                    ),
                )
            )

        references_markdown = f"# References\n\n{ref_page_result.text}\n"

        # Resolve the opposite direction. An in-text citation that matches no
        # eligible source is either fabricated or points at a source that was
        # dropped from the set; either way the reader is being shown a citation
        # that cannot be traced to a source object. Deduplicate by the raw
        # citation text so a claim repeated three times is reported once.
        unmatched: list[str] = []
        seen: set[str] = set()
        for citation in extracted:
            if citation.raw in seen:
                continue
            seen.add(citation.raw)
            if any(_citation_matches_source(citation, s) for s in eligible_sources):
                continue
            unmatched.append(citation.raw)

        for raw in unmatched:
            all_warnings.append(
                CitationWarning(
                    code=CITATION_UNRESOLVED,
                    field="in_text_citation",
                    message=(
                        f"In-text citation \u201c{raw}\u201d does not resolve to any "
                        "collected source. It must be removed or backed by a real "
                        "source; it cannot appear in the References page."
                    ),
                )
            )

        return CitationAnalysis(
            in_text_citation_count=len(raw_in_text),
            used_sources=used_sources,
            unused_sources=unused_sources,
            unmatched_in_text_citations=unmatched,
            warnings=all_warnings,
            references_section_text=references_markdown,
        )

    def attach_references(
        self, document: Document, analysis: CitationAnalysis
    ) -> Document:
        """Appends the deterministic References section to the end of the document text."""
        # Strip any pre-existing References block first
        clean_text = document.text
        ref_match = re.search(r"(?:^|\n)#{1,3}\s*References(?:\s*\n|\Z)", clean_text, re.IGNORECASE)
        if ref_match:
            clean_text = clean_text[:ref_match.start()].strip()

        combined = f"{clean_text.strip()}\n\n{analysis.references_section_text.strip()}\n"
        return Document.parse(combined, title=document.title, mode=document.mode)
