"""In-text APA citation extraction, shared by drafting checks, revalidation and the registry.

Lives apart from howlwriter.academic so that citation tooling can use it without
importing the academic pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

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


def extract_in_text_citations(text: str) -> list[_InTextCitation]:
    """Every in-text citation in `text`, in the structured form used to resolve it.

    Parenthetical groups may hold several semicolon-separated citations; narrative
    forms ("Author (2024)") and bare source ids are included.
    """
    extracted: list[_InTextCitation] = []
    for match in _PARENTHETICAL_GROUP.finditer(text):
        # One set of parentheses can hold several citations separated by
        # semicolons; each is its own citation and must resolve on its own.
        for segment in match.group(1).split(";"):
            segment = segment.strip()
            if not _looks_like_citation(segment):
                continue
            names, year = _split_names_and_year(segment)
            extracted.append(_InTextCitation(raw=segment, names=names, year=year))
    for match in _NARRATIVE_PATTERN.finditer(text):
        names = match.group(1).strip()
        year = match.group(2).strip()
        extracted.append(_InTextCitation(raw=f"{names} ({year})", names=names, year=year))
    for match in _SOURCE_ID_PATTERN.finditer(text):
        raw = match.group(1).strip()
        extracted.append(_InTextCitation(raw=raw, names="", year=None, source_id=raw))
    return extracted
