"""A basic, deterministic APA 7 formatter.

Operates only on metadata actually present on a Source. Missing metadata
never gets invented: a missing publication_date produces the APA7
undated-source form ("n.d.") plus a CITATION_METADATA_MISSING warning; a
missing author moves the title into the author position per APA7 rules,
also with a warning. This is a basic representation (author/year/title/
publisher/locator) -- it does not attempt full academic-citation depth
(volume/issue/page ranges, edition, translator, etc.), which is out of
scope for the MVP's "basic APA7 citation representation" goal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source

CITATION_METADATA_MISSING = "CITATION_METADATA_MISSING"

_ORG_SUFFIXES = (
    "organization",
    "association",
    "institute",
    "university",
    "inc.",
    "inc",
    "company",
    "agency",
    "foundation",
    "committee",
    "department",
    "administration",
    "corporation",
)


@dataclass
class CitationWarning(DataClassSerializationMixin):
    code: str
    field: str
    message: str


@dataclass
class CitationResult(DataClassSerializationMixin):
    text: str
    warnings: list[CitationWarning] = field(default_factory=list)


def _is_organizational(author: str) -> bool:
    lowered = author.lower().strip()
    return any(lowered.endswith(suffix) for suffix in _ORG_SUFFIXES)


def _surname(author: str) -> str:
    if _is_organizational(author):
        return author
    parts = author.strip().split()
    return parts[-1] if parts else author


def _format_author(author: str) -> str:
    if _is_organizational(author):
        return author
    parts = author.strip().split()
    if len(parts) < 2:
        return author
    *given, last = parts
    initials = " ".join(f"{p[0]}." for p in given if p)
    return f"{last}, {initials}"


def _author_list_str(authors: list[str]) -> tuple[str, CitationWarning | None]:
    if not authors:
        warning = CitationWarning(
            code=CITATION_METADATA_MISSING,
            field="authors",
            message="Author(s) could not be verified. APA reference will lead with the title instead.",
        )
        return "", warning
    formatted = [_format_author(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0], None
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}", None
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}", None


def _year_str(source: Source) -> tuple[str, CitationWarning | None]:
    if source.publication_date is None:
        warning = CitationWarning(
            code=CITATION_METADATA_MISSING,
            field="publication_date",
            message=(
                "Publication date could not be verified. "
                "APA reference will use the appropriate undated-source format."
            ),
        )
        return "n.d.", warning
    return str(source.publication_date.year), None


def _locator_str(source: Source) -> tuple[str, CitationWarning | None]:
    if source.doi:
        return f"https://doi.org/{source.doi}", None
    if source.url:
        return source.url, None
    warning = CitationWarning(
        code=CITATION_METADATA_MISSING,
        field="url",
        message="No URL or DOI on file for this source; reference omits a locator.",
    )
    return "", warning


def _short_title(title: str, *, max_words: int = 6) -> str:
    words = title.split()
    return title if len(words) <= max_words else " ".join(words[:max_words]) + "..."


class APA7Formatter:
    def reference_entry(self, source: Source) -> CitationResult:
        warnings: list[CitationWarning] = []

        author_str, author_warning = _author_list_str(source.authors)
        if author_warning:
            warnings.append(author_warning)

        year_str, year_warning = _year_str(source)
        if year_warning:
            warnings.append(year_warning)

        segments: list[str] = []
        if author_str:
            segments.append(f"{author_str} ({year_str}).")
            segments.append(f"{source.title}.")
        else:
            # APA7: with no known author, the title moves into the author position.
            segments.append(f"{source.title} ({year_str}).")

        if source.publisher:
            segments.append(f"{source.publisher}.")

        locator, locator_warning = _locator_str(source)
        if locator:
            segments.append(locator)
        if locator_warning:
            warnings.append(locator_warning)

        return CitationResult(text=" ".join(segments), warnings=warnings)

    def in_text_parenthetical(self, source: Source) -> CitationResult:
        year_str, year_warning = _year_str(source)
        warnings = [year_warning] if year_warning else []

        if not source.authors:
            warnings.append(
                CitationWarning(
                    code=CITATION_METADATA_MISSING,
                    field="authors",
                    message="Author(s) could not be verified. In-text citation uses a shortened title.",
                )
            )
            return CitationResult(text=f'("{_short_title(source.title)}", {year_str})', warnings=warnings)

        surnames = [_surname(a) for a in source.authors]
        if len(surnames) == 1:
            who = surnames[0]
        elif len(surnames) == 2:
            who = f"{surnames[0]} & {surnames[1]}"
        else:
            who = f"{surnames[0]} et al."
        return CitationResult(text=f"({who}, {year_str})", warnings=warnings)

    def narrative(self, source: Source) -> CitationResult:
        year_str, year_warning = _year_str(source)
        warnings = [year_warning] if year_warning else []

        if not source.authors:
            warnings.append(
                CitationWarning(
                    code=CITATION_METADATA_MISSING,
                    field="authors",
                    message="Author(s) could not be verified. Narrative citation uses a shortened title.",
                )
            )
            return CitationResult(text=f'"{_short_title(source.title)}" ({year_str})', warnings=warnings)

        surnames = [_surname(a) for a in source.authors]
        if len(surnames) == 1:
            who = surnames[0]
        elif len(surnames) == 2:
            who = f"{surnames[0]} and {surnames[1]}"
        else:
            who = f"{surnames[0]} et al."
        return CitationResult(text=f"{who} ({year_str})", warnings=warnings)

    def reference_page(self, sources: list[Source]) -> CitationResult:
        """Alphabetized by first-author surname (or title, when no author)."""

        def sort_key(source: Source) -> str:
            if source.authors:
                return _surname(source.authors[0]).lower()
            return source.title.lower()

        warnings: list[CitationWarning] = []
        entries: list[str] = []
        for source in sorted(sources, key=sort_key):
            result = self.reference_entry(source)
            entries.append(result.text)
            warnings.extend(result.warnings)
        return CitationResult(text="\n".join(entries), warnings=warnings)
