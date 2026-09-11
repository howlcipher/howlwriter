"""Standard local output directory manager and deliverable tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from howlwriter.domain.io import atomic_write_bytes, atomic_write_text
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.output.naming import OutputCollisionError, safe_filename


@dataclass
class OutputDeliverable(DataClassSerializationMixin):
    """Metadata for a generated finished local artifact."""

    format: str
    path: str
    sha256: str
    size_bytes: int
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class OutputManifest(DataClassSerializationMixin):
    """Manifest describing all local deliverables generated from an authorized run."""

    run_id: str
    title: str
    authorized_artifact_hash: str
    created_at: str
    deliverables: list[OutputDeliverable] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalOutputManager:
    """Manages writing polished user deliverables to the local output directory."""

    def __init__(
        self,
        output_dir: Path | str = "output",
        overwrite: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.overwrite = overwrite

    def ensure_dir(self) -> Path:
        """Ensures the output directory exists."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir

    def resolve_destination(
        self,
        title_or_slug: str,
        format_extension: str,
        explicit_path: Path | str | None = None,
    ) -> Path:
        """Resolves target output path, respecting explicit paths or safe naming in output_dir."""
        if explicit_path:
            p = Path(explicit_path).expanduser().resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            return p

        self.ensure_dir()
        filename = safe_filename(title_or_slug, format_extension)
        return self.output_dir / filename

    def write_deliverable(
        self,
        content: str | bytes,
        format_extension: str,
        title_or_slug: str,
        explicit_path: Path | str | None = None,
        overwrite: bool | None = None,
    ) -> OutputDeliverable:
        """Atomically writes deliverable, verifying collision safety."""
        target_path = self.resolve_destination(
            title_or_slug, format_extension, explicit_path=explicit_path
        )
        should_overwrite = self.overwrite if overwrite is None else overwrite

        if target_path.exists() and not should_overwrite:
            raise OutputCollisionError(
                f"Output deliverable already exists at '{target_path}'. "
                f"Specify --overwrite to replace it or choose a different title/path."
            )

        if isinstance(content, str):
            raw_bytes = content.encode("utf-8")
            atomic_write_text(target_path, content, encoding="utf-8")
        else:
            raw_bytes = content
            atomic_write_bytes(target_path, content)

        sha = hashlib.sha256(raw_bytes).hexdigest()
        deliverable = OutputDeliverable(
            format=format_extension.lstrip(".").lower(),
            path=str(target_path),
            sha256=sha,
            size_bytes=len(raw_bytes),
        )
        return deliverable

    def write_manifest(
        self,
        run_id: str,
        title: str,
        authorized_artifact_hash: str,
        deliverables: list[OutputDeliverable],
        manifest_filename: str = "publication-manifest.json",
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Writes publication-manifest.json linking all local outputs to the authorized run."""
        self.ensure_dir()
        manifest_path = self.output_dir / manifest_filename
        manifest = OutputManifest(
            run_id=run_id,
            title=title,
            authorized_artifact_hash=authorized_artifact_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
            deliverables=deliverables,
            metadata=metadata or {},
        )
        manifest_json = json.dumps(manifest.to_dict(), indent=2) + "\n"
        atomic_write_text(manifest_path, manifest_json)
        return manifest_path
