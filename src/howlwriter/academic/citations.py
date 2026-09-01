"""APA 7 in-text citation extraction, reference matching, and bibliography construction."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.citations.apa7 import APA7Formatter, CitationWarning
from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source


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

        parenthetical_pattern = re.compile(
            r"\(([A-Z][A-Za-z\s&',.-]+?,\s*(?:\d{4}|n\.d\.)(?:,\s*p{1,2}\.\s*\d+)?)\)"
        )
        narrative_pattern = re.compile(
            r"\b([A-Z][A-Za-z]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z]+|\s+et\s+al\.)?)\s+\((\d{4}|n\.d\.)\)"
        )
        source_id_pattern = re.compile(r"\b(S\d{3})\b")

        raw_in_text: list[str] = []
        for match in parenthetical_pattern.finditer(text):
            raw_in_text.append(match.group(1).strip())
        for match in narrative_pattern.finditer(text):
            raw_in_text.append(f"{match.group(1).strip()} ({match.group(2).strip()})")
        for match in source_id_pattern.finditer(text):
            raw_in_text.append(match.group(1).strip())

        # Only sources that pass the relevance gate are eligible for use.
        eligible_sources = [s for s in available_sources if s.is_usable]

        used_sources: list[Source] = []
        unused_sources: list[Source] = []
        all_warnings: list[CitationWarning] = []

        # Check each eligible source to see if it was cited
        for source in eligible_sources:
            cited = False

            # Check by Source ID: S001
            if source.id in text:
                cited = True

            # Check by Author surname(s) and year
            if not cited and source.authors:
                first_author_surname = (
                    source.authors[0].split(",")[0].split()[-1].strip()
                )
                year_str = str(source.publication_date.year) if source.publication_date else "n.d."

                # E.g. "Smith" and "2024" in proximity
                if first_author_surname.lower() in text.lower() and year_str in text:
                    cited = True

            # Check by title keywords if no authors
            if not cited and not source.authors:
                title_keyword = source.title.split()[0].lower() if source.title else ""
                if len(title_keyword) > 4 and title_keyword in text.lower():
                    cited = True

            if cited:
                used_sources.append(source)
            else:
                unused_sources.append(source)

        # Build References Section for sources that are actually used in the
        # paper. If no in-text citations were detected, still only include
        # eligible sources; irrelevant or tangential items must not satisfy the
        # minimum requirement or appear in the bibliography.
        sources_for_bib = used_sources if used_sources else eligible_sources
        ref_page_result = self.formatter.reference_page(sources_for_bib)
        all_warnings.extend(ref_page_result.warnings)

        references_markdown = f"# References\n\n{ref_page_result.text}\n"

        return CitationAnalysis(
            in_text_citation_count=len(raw_in_text),
            used_sources=used_sources,
            unused_sources=unused_sources,
            unmatched_in_text_citations=[],
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
