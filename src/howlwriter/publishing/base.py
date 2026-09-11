"""Destination-neutral artifact publishing abstractions and data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any, Protocol

from howlwriter.domain.serialization import DataClassSerializationMixin


@dataclass
class PublicationArtifact(DataClassSerializationMixin):
    """The verified, authorized artifact prepared for publication."""

    title: str
    content: str | bytes
    format: str  # "md" | "docx" | "pdf"
    source_run_id: str
    authorized_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_bytes(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        return self.content.encode("utf-8")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.raw_bytes).hexdigest()


@dataclass
class PublishDestination(DataClassSerializationMixin):
    """Target destination descriptor for an artifact publication."""

    destination_type: str  # "google_docs", "local", etc.
    target: str = ""  # folder name/id, path, or document id
    folder: str | None = None
    update_doc_id: str | None = None
    update_mode: str = "create"  # "create" | "replace" | "append"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishContext(DataClassSerializationMixin):
    """Context governing publication execution and authority boundaries."""

    run_id: str
    dry_run: bool = False
    allow_unverified: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult(DataClassSerializationMixin):
    """Deterministic result record of a publication attempt."""

    destination_type: str
    destination_target: str
    artifact_title: str
    artifact_id: str | None = None
    url: str | None = None
    published_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    content_hash: str = ""
    source_run_id: str = ""
    revision_metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "SUCCESS"  # "SUCCESS" | "FAILED"
    diagnostics: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.status == "SUCCESS"


class ArtifactPublisher(Protocol):
    """Protocol implemented by destination publishers."""

    def publish(
        self,
        artifact: PublicationArtifact,
        destination: PublishDestination,
        context: PublishContext,
    ) -> PublishResult:
        ...
