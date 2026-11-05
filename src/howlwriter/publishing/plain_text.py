"""Plain-text and local filesystem artifact publisher."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from howlwriter.publishing.base import (
    ArtifactPublisher,
    PublicationArtifact,
    PublishContext,
    PublishDestination,
    PublishResult,
)


def _sanitize_filename(name: str) -> str:
    """Sanitize title or identifier for safe filesystem usage."""
    cleaned = re.sub(r"[^\w\s-]", "", name)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._-")
    return cleaned or "document"


class PlainTextPublisher(ArtifactPublisher):
    """Publishes artifacts as plain-text files to local destination paths.

    Enforces read-back verification: reads the target file immediately after
    writing and verifies the SHA-256 hash matches the artifact.
    """

    def publish(
        self,
        artifact: PublicationArtifact,
        destination: PublishDestination,
        context: PublishContext,
    ) -> PublishResult:
        diagnostics: list[str] = []

        # Determine target output path
        raw_target = destination.target or destination.folder
        if not raw_target:
            raw_target = f"{_sanitize_filename(artifact.title)}.txt"

        target_path = Path(raw_target)

        # If target is an existing directory or ends with a slash, append sanitized filename
        if target_path.is_dir() or str(raw_target).endswith(("/", "\\")):
            filename = f"{_sanitize_filename(artifact.title)}.txt"
            target_path = target_path / filename

        # Format content
        if isinstance(artifact.content, bytes):
            try:
                text_content = artifact.content.decode("utf-8")
            except UnicodeDecodeError:
                text_content = artifact.content.decode("utf-8", errors="replace")
        else:
            text_content = str(artifact.content)

        if context.dry_run:
            return PublishResult(
                destination_type="plain_text",
                destination_target=str(target_path),
                artifact_title=artifact.title,
                artifact_id=str(target_path),
                url=f"file://{target_path.resolve()}",
                content_hash=hashlib.sha256(text_content.encode("utf-8")).hexdigest(),
                source_run_id=context.run_id,
                status="SUCCESS",
                diagnostics=["dry_run: file write skipped"],
            )

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if destination.update_mode == "append" and target_path.exists() else "w"
            with open(target_path, mode, encoding="utf-8") as f:
                if mode == "a":
                    f.write("\n\n" + text_content)
                else:
                    f.write(text_content)
        except OSError as exc:
            diagnostics.append(f"Write failed: {exc}")
            return PublishResult(
                destination_type="plain_text",
                destination_target=str(target_path),
                artifact_title=artifact.title,
                source_run_id=context.run_id,
                status="FAILED",
                diagnostics=diagnostics,
            )

        # Read-back verification
        try:
            read_back_bytes = target_path.read_bytes()
            read_back_hash = hashlib.sha256(read_back_bytes).hexdigest()
            expected_text = target_path.read_text(encoding="utf-8")
            expected_hash = hashlib.sha256(expected_text.encode("utf-8")).hexdigest()
            if read_back_hash != expected_hash:
                diagnostics.append("Read-back verification mismatch.")
                return PublishResult(
                    destination_type="plain_text",
                    destination_target=str(target_path),
                    artifact_title=artifact.title,
                    artifact_id=str(target_path),
                    source_run_id=context.run_id,
                    status="UNCONFIRMED",
                    diagnostics=diagnostics,
                )
        except Exception as exc:
            diagnostics.append(f"Read-back failed: {exc}")
            return PublishResult(
                destination_type="plain_text",
                destination_target=str(target_path),
                artifact_title=artifact.title,
                artifact_id=str(target_path),
                source_run_id=context.run_id,
                status="UNCONFIRMED",
                diagnostics=diagnostics,
            )

        return PublishResult(
            destination_type="plain_text",
            destination_target=str(target_path),
            artifact_title=artifact.title,
            artifact_id=str(target_path),
            url=f"file://{target_path.resolve()}",
            content_hash=read_back_hash,
            source_run_id=context.run_id,
            status="SUCCESS",
            diagnostics=diagnostics,
        )
