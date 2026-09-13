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
    """Preserves all-uppercase initialisms/acronyms (e.g., HTTP, NASA, U.S.)."""
    return token.isupper() and len(token) > 1


# Dotted initialisms ("U.S.", "D.C.", "Ph.D.") are one token: splitting them on
# the periods used to turn "U.S. Financial" into "u.S. Financial" because each
# period looked like a sentence boundary.
_TITLE_TOKEN = re.compile(r"(?:[A-Za-z]\.){2,}|[A-Za-z0-9_'-]+|[^A-Za-z0-9_'-]+")
_WORD_RUN = re.compile(r"(?:[A-Za-z]\.){2,}|[A-Za-z0-9_'-]+")


def _has_internal_upper(word: str) -> bool:
    """Mixed-case words ("iPhone", "McDonald") are probable proper nouns; the
    check runs per hyphen part so Title-Cased compounds ("Pre-Mortem") are not
    mistaken for them."""
    return any(any(c.isupper() for c in piece[1:]) for piece in word.split("-"))


def _looks_title_cased(title: str) -> bool:
    """True when most words are capitalized, i.e. the title needs converting.

    A title whose words are mostly lowercase is already sentence case, and the
    capitals it does carry ("China", "Microsoft", "Yellen") are the author's
    proper nouns. Converting such a title would only strip those, so it is
    left alone; no mechanical rule can tell "Financial" from "China" in a
    Title-Cased string, which is why the decision is made per title.
    """
    # Skip the first word and words after sentence punctuation: those are
    # capitalized in sentence case too and carry no signal. Acronyms and
    # mixed-case words are preserved either way, so they carry none either.
    signal: list[str] = []
    capitalize_expected = True
    for part in _TITLE_TOKEN.findall(title):
        if not _WORD_RUN.fullmatch(part):
            if any(p in part for p in _TITLE_PUNCTUATION):
                capitalize_expected = True
            continue
        if capitalize_expected:
            capitalize_expected = False
            continue
        if not part[0].isalpha() or _token_is_likely_acronym(part) or _has_internal_upper(part):
            continue
        signal.append(part)
    if not signal:
        return False
    capitalized = sum(1 for w in signal if w[0].isupper())
    return capitalized / len(signal) >= 0.5


#: Words that stay capitalized inside a sentence-case title.
_ALWAYS_CAPITALIZED = frozenset({
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
})


def _sentence_case(title: str) -> tuple[str, bool]:
    """Converts a work title to APA 7 sentence case.

    Returns the transformed title and a flag indicating whether any change was
    made. All-uppercase acronyms/initialisms (including dotted ones such as
    "U.S.") are preserved; words that already contain internal capitals (e.g.
    "iPhone") are left as-is to avoid mangling proper nouns. Other words are
    lowercased except the first word and the first word after a
    colon/semicolon/question/exclamation/dash. A title that is already in
    sentence case is returned unchanged so its proper nouns survive.
    """
    if not title:
        return title, False
    if not _looks_title_cased(title):
        return title, False

    # Preserve hyphenated words, apostrophes and dotted initialisms as single tokens.
    parts = _TITLE_TOKEN.findall(title)
    changed = False
    capitalize_next = True
    result: list[str] = []

    for part in parts:
        if not part:
            continue
        # Non-word runs are punctuation/whitespace.
        if not _WORD_RUN.fullmatch(part):
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
        if _has_internal_upper(part):
            result.append(part)
            capitalize_next = False
            continue

        if capitalize_next or part.lower() in _ALWAYS_CAPITALIZED:
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

# Words that essentially never occur inside a person's name written in
# natural order ("Jane A. Smith") but are common in group-author names
# ("Financial Stability Oversight Council", "Office of the Director of
# National Intelligence"). Checked only when the author string has no comma:
# a comma means the caller already wrote an inverted person name
# ("Hill, French"), which must stay a person.
_ORG_WORDS = frozenset({
    "of", "for", "the", "and", "&",
    "u.s.", "us", "united", "national", "international", "federal", "state",
    "office", "council", "board", "bureau", "commission", "committee",
    "department", "ministry", "service", "services", "fund", "bank", "center",
    "centre", "group", "union", "house", "endowment", "authority", "society",
    "association", "institute", "institution", "agency", "administration",
    "corporation", "company", "inc", "inc.", "llc", "ltd", "university",
    "college", "foundation", "team", "project", "studies", "laboratory", "lab",
    "partners", "press", "journal", "law", "register", "network", "alliance",
    "system", "systems", "forum", "consortium", "coalition", "program",
    "programme", "initiative", "trust", "exchange", "assembly", "congress",
    "senate", "parliament", "government", "secretariat", "organisation",
    "organization", "translate", "research",
})


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
    if any(lowered.endswith(suffix) for suffix in _ORG_SUFFIXES):
        return True
    if "," in lowered:
        # "Surname, Given" is an explicit person form.
        return False
    tokens = [t.strip("()[]{}:;\"'") for t in lowered.split()]
    return any(t in _ORG_WORDS for t in tokens)


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

        # APA 7 omits a site/publisher name when it is identical to the sole
        # organizational author (for example, GAO as both author and publisher).
        # Besides being redundant, repeating it needlessly lengthens reference
        # lists for government-heavy papers.
        publisher_duplicates_author = (
            bool(source.publisher)
            and len(source.authors) == 1
            and _is_organizational(source.authors[0])
            and source.publisher.strip().casefold() == source.authors[0].strip().casefold()
        )
        if source.publisher and not publisher_duplicates_author:
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
        """Alphabetize references, then order one author's works by year."""

        def sort_key(source: Source) -> tuple[str, int, str]:
            if source.authors:
                author_or_title = _surname(source.authors[0]).casefold()
            else:
                author_or_title = source.title.casefold()
            # Undated works precede dated works for the same author. Title is
            # a stable tie-breaker for multiple works from the same year.
            year = source.publication_date.year if source.publication_date else -1
            return author_or_title, year, source.title.casefold()

        warnings: list[CitationWarning] = []
        entries: list[str] = []
        for source in sorted(sources, key=sort_key):
            result = self.reference_entry(source)
            entries.append(result.text)
            warnings.extend(result.warnings)
        return CitationResult(text="\n".join(entries), warnings=warnings)
