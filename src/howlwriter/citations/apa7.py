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
import re

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source

CITATION_METADATA_MISSING = "CITATION_METADATA_MISSING"
CITATION_TITLE_CASE = "CITATION_TITLE_CASE"

# Word separators that signal a new sentence/subtitle in APA 7.
_TITLE_PUNCTUATION = frozenset({".", ":", ";", "?", "!", "—"})


def _token_is_likely_acronym(token: str) -> bool:
    """Preserves all-uppercase initialisms/acronyms (e.g., HTTP, NASA, API)."""
    return token.isupper() and len(token) > 1


def _sentence_case(title: str) -> tuple[str, bool]:
    """Converts a work title to APA 7 sentence case.

    Returns the transformed title and a flag indicating whether any change was
    made. All-uppercase acronyms/initialisms are preserved; words that already
    contain internal capitals (e.g. "iPhone") are left as-is to avoid mangling
    proper nouns. Other words are lowercased except the first word and the first
    word after a colon/semicolon/question/exclamation/dash.
    """
    if not title:
        return title, False

    # Preserve hyphenated words and apostrophes as single tokens.
    parts = re.findall(r"[A-Za-z0-9_'-]+|[^A-Za-z0-9_'-]+", title)
    changed = False
    capitalize_next = True
    result: list[str] = []

    for part in parts:
        if not part:
            continue
        # Non-word runs are punctuation/whitespace.
        if not re.match(r"[A-Za-z0-9_'-]+", part):
            result.append(part)
            if any(p in part for p in _TITLE_PUNCTUATION):
                # Next alphabetic token after punctuation gets capitalized if
                # it is not already an acronym/proper noun.
                capitalize_next = True
            continue

        if _token_is_likely_acronym(part):
            result.append(part)
            capitalize_next = False
            continue

        # Preserve mixed-case tokens (e.g., iPhone, McDonald) as probable
        # proper nouns; otherwise apply sentence-case rules.
        has_internal_upper = any(c.isupper() for c in part[1:])
        if has_internal_upper:
            result.append(part)
            capitalize_next = False
            continue

        if capitalize_next:
            new_part = part[0].upper() + part[1:].lower() if part else part
            capitalize_next = False
        else:
            new_part = part.lower()

        if new_part != part:
            changed = True
        result.append(new_part)

    return "".join(result), changed


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
    if "," in author:
        return author.split(",")[0].strip()
    parts = author.strip().split()
    return parts[-1] if parts else author


def _format_author(author: str) -> str:
    if _is_organizational(author):
        return author
    if "," in author:
        last, rest = author.split(",", 1)
        given = rest.strip().split()
        if not given:
            return last.strip()
        initials = " ".join(f"{p[0]}." for p in given if p and p[0].isalpha())
        return f"{last.strip()}, {initials}" if initials else last.strip()
    parts = author.strip().split()
    if len(parts) < 2:
        return author
    *given, last = parts
    initials = " ".join(f"{p[0]}." for p in given if p and p[0].isalpha())
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
    sentence_title, _ = _sentence_case(title)
    words = sentence_title.split()
    return sentence_title if len(words) <= max_words else " ".join(words[:max_words]) + "..."


class APA7Formatter:
    def reference_entry(self, source: Source) -> CitationResult:
        warnings: list[CitationWarning] = []

        author_str, author_warning = _author_list_str(source.authors)
        if author_warning:
            warnings.append(author_warning)

        year_str, year_warning = _year_str(source)
        if year_warning:
            warnings.append(year_warning)

        # APA 7 article/work titles use sentence case. Preserve acronyms and
        # mixed-case proper nouns; surface a warning so any mis-cased proper
        # noun can be reviewed.
        title, title_was_changed = _sentence_case(source.title)
        if title_was_changed:
            warnings.append(
                CitationWarning(
                    code=CITATION_TITLE_CASE,
                    field="title",
                    message=(
                        "Title was converted to APA 7 sentence case. "
                        "Proper nouns may need manual review."
                    ),
                )
            )

        segments: list[str] = []
        if author_str:
            segments.append(f"{author_str} ({year_str}).")
            segments.append(f"{title}.")
        else:
            # APA7: with no known author, the title moves into the author position.
            segments.append(f"{title} ({year_str}).")

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
