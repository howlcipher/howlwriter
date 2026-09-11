"""Multi-artifact combined document builder.

Combines related academic components (e.g. Main Discussion Post + Peer Response 1 +
Peer Response 2) into one cleanly separated document with unified references.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.citations.apa7 import APA7Formatter
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source


@dataclass
class DocumentSection(DataClassSerializationMixin):
    """An individual section of a multi-artifact deliverable."""

    id: str
    title: str
    content: str
    sources: list[Source] = field(default_factory=list)


@dataclass
class CombinedDocument(DataClassSerializationMixin):
    """Aggregates multiple sections into a single canonical document."""

    title: str
    sections: list[DocumentSection] = field(default_factory=list)
    common_sources: list[Source] = field(default_factory=list)

    def to_document(self) -> Document:
        """Assembles the combined document into a single span-addressable Document."""
        blocks: list[str] = [f"# {self.title}\n"]

        all_sources: dict[str, Source] = {}
        for s in self.common_sources:
            all_sources[s.id] = s

        for idx, sec in enumerate(self.sections):
            for s in sec.sources:
                all_sources[s.id] = s

            # Section title (Heading 2)
            blocks.append(f"## {sec.title}\n")
            clean_content = sec.content.strip()

            # If section content already has a top-level # title matching sec.title, strip it
            if clean_content.startswith("# "):
                lines = clean_content.split("\n", 1)
                clean_content = lines[1].strip() if len(lines) > 1 else ""

            blocks.append(clean_content)

            # Add divider if not the last section
            if idx < len(self.sections) - 1:
                blocks.append("\n---\n")

        # Compile unified references section
        if all_sources:
            formatter = APA7Formatter()
            sorted_sources = sorted(
                all_sources.values(),
                key=lambda s: (s.authors[0] if s.authors else s.title or "").lower(),
            )
            ref_entries = [formatter.reference_entry(s).text for s in sorted_sources]
            blocks.append("\n---\n")
            blocks.append("## References\n")
            blocks.append("\n\n".join(ref_entries))

        full_text = "\n\n".join(blocks).strip() + "\n"
        return Document.parse(full_text, title=self.title, mode=WritingMode.ACADEMIC)


def build_combined_document(
    title: str,
    sections: list[DocumentSection],
    common_sources: list[Source] | None = None,
) -> Document:
    """Builds a combined academic document from distinct sections."""
    combined = CombinedDocument(
        title=title,
        sections=sections,
        common_sources=common_sources or [],
    )
    return combined.to_document()
