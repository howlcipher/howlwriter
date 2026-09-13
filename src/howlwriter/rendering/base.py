"""Base abstractions, protocols, and data models for document renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Protocol

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin


#: Ordered keys of a ``RenderContext.title_page`` mapping, rendered top to
#: bottom as centered lines beneath the title (APA 7 student title page order).
TITLE_PAGE_FIELDS = ("author", "affiliation", "course", "assignment", "instructor", "date")


@dataclass
class RenderContext(DataClassSerializationMixin):
    """Context and options provided to renderers.

    ``line_spacing`` is a multiple of single spacing (1.0, 1.5, 2.0, etc.).
    ``page_numbers`` places the page number in the top-right header (APA 7).
    ``title_page`` holds the lines for a separate title page keyed by
    :data:`TITLE_PAGE_FIELDS`; when present the body starts on page two.
    """

    title: str = ""
    author: str = ""
    institution: str = ""
    citation_style: str = "apa7"
    include_ai_disclosure: bool = False
    ai_disclosure_text: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    font_family: str = "Times New Roman"
    font_size_pt: float = 12.0
    line_spacing: float = 1.0
    margin_top_in: float = 1.0
    margin_bottom_in: float = 1.0
    margin_left_in: float = 1.0
    margin_right_in: float = 1.0
    page_numbers: bool = False
    title_page: dict[str, str] | None = None

    def title_page_lines(self) -> list[str]:
        """The non-empty title-page lines in APA order (title excluded)."""
        if not self.title_page:
            return []
        return [
            str(self.title_page[key]).strip()
            for key in TITLE_PAGE_FIELDS
            if self.title_page.get(key) and str(self.title_page[key]).strip()
        ]


@dataclass
class RenderedArtifact:
    """A rendered document ready for local saving or cloud publication."""

    format: str  # "md" | "docx" | "pdf"
    content: str | bytes
    mime_type: str
    title: str
    filename_extension: str

    @property
    def is_binary(self) -> bool:
        return isinstance(self.content, bytes)

    @property
    def text_content(self) -> str | None:
        return self.content if isinstance(self.content, str) else None

    @property
    def binary_content(self) -> bytes | None:
        return self.content if isinstance(self.content, bytes) else None

    @property
    def raw_bytes(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        return self.content.encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw_bytes).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.raw_bytes)


class DocumentRenderer(Protocol):
    """Protocol for transforming a Document into a rendered deliverable."""

    def render(
        self, document: Document, context: RenderContext | None = None
    ) -> RenderedArtifact:
        ...
