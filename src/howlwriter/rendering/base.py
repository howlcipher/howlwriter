"""Base abstractions, protocols, and data models for document renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Protocol

from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin


@dataclass
class RenderContext(DataClassSerializationMixin):
    """Context and options provided to renderers."""

    title: str = ""
    author: str = ""
    institution: str = ""
    citation_style: str = "apa7"
    include_ai_disclosure: bool = False
    ai_disclosure_text: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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
