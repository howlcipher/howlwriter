"""Source and Evidence: first-class provenance objects.

Evidence is kept separate from Claim (not a field on it) so the provenance
graph in domain/provenance.py can answer questions in both directions:
"which sources support this claim" and "which claims does this source
support" without denormalizing data into either object.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date

from howlwriter.domain.serialization import DataClassSerializationMixin


class SourceType(enum.Enum):
    WEBSITE = "website"
    JOURNAL_ARTICLE = "journal_article"
    BOOK = "book"
    NEWS_ARTICLE = "news_article"
    REPORT = "report"
    DATASET = "dataset"
    INTERVIEW = "interview"
    OTHER = "other"


# Source relevance to the assignment topic / query / outline.
RELEVANCE_DIRECT = "DIRECT"
RELEVANCE_SUPPORTING = "SUPPORTING"
RELEVANCE_TANGENTIAL = "TANGENTIAL"
RELEVANCE_IRRELEVANT = "IRRELEVANT"

# Evidence depth actually retrieved for the source.
DEPTH_FULL_TEXT = "FULL_TEXT"
DEPTH_ABSTRACT = "ABSTRACT"
DEPTH_METADATA_ONLY = "METADATA_ONLY"
DEPTH_OTHER = "OTHER"


@dataclass
class Source(DataClassSerializationMixin):
    id: str
    title: str
    authors: list[str]
    publisher: str | None = None
    publication_date: date | None = None
    url: str | None = None
    doi: str | None = None
    access_date: date | None = None
    source_type: SourceType = SourceType.OTHER
    retrieved_text: str | None = None
    reliability_notes: str = ""
    # Source-relevance classification assigned during research.
    relevance: str = RELEVANCE_DIRECT
    # Explicit evidence depth, independent of the free-text field.
    evidence_depth: str = DEPTH_OTHER

    @property
    def was_accessed(self) -> bool:
        """True only if this source was actually retrieved, not just cited by id."""
        return self.retrieved_text is not None or self.access_date is not None

    @property
    def is_usable(self) -> bool:
        """A source is usable for an assignment if it is relevant enough.

        Usability counts toward the minimum source requirement. Depth is a
        separate check: a usable source whose evidence is metadata-only can
        support only metadata facts, not arbitrary technical claims.
        """
        return self.relevance in (RELEVANCE_DIRECT, RELEVANCE_SUPPORTING)

    @property
    def is_substantive_evidence(self) -> bool:
        """True only if the source has some real retrieved text beyond metadata."""
        text = (self.retrieved_text or "").strip()
        if not text:
            return False
        return self.evidence_depth in (DEPTH_FULL_TEXT, DEPTH_ABSTRACT, DEPTH_OTHER)


@dataclass
class Evidence(DataClassSerializationMixin):
    id: str
    source_id: str
    claim_id: str
    snippet: str
    supports: bool
    notes: str = ""


def source_from_dict(entry: dict) -> Source:
    """Builds a Source from a plain JSON-decoded dict, parsing its date
    fields. Shared by every CLI command that reads a sources.json file, so
    the parsing rules live in exactly one place."""
    entry = dict(entry)
    if entry.get("publication_date"):
        entry["publication_date"] = date.fromisoformat(entry["publication_date"])
    if entry.get("access_date"):
        entry["access_date"] = date.fromisoformat(entry["access_date"])
    if entry.get("source_type"):
        entry["source_type"] = SourceType(entry["source_type"])
    return Source.from_dict(entry)
