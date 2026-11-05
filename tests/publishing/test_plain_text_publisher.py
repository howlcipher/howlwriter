"""Tests for the native PlainTextPublisher and local publishing flows."""

from __future__ import annotations

import hashlib
from pathlib import Path

from howlwriter.publishing.base import (
    PublicationArtifact,
    PublishContext,
    PublishDestination,
)
from howlwriter.publishing.plain_text import PlainTextPublisher
from howlwriter.publishing.registry import get_publisher, list_supported_destinations


def test_plain_text_publisher_basic_write(tmp_path: Path) -> None:
    target_file = tmp_path / "post_01.txt"
    content = "Hello, production engineering world!\nLine two of content."
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    artifact = PublicationArtifact(
        title="Post 01",
        content=content,
        format="txt",
        source_run_id="run-123",
        authorized_sha256=content_hash,
    )
    dest = PublishDestination(destination_type="plain_text", target=str(target_file))
    ctx = PublishContext(run_id="run-123")

    publisher = PlainTextPublisher()
    result = publisher.publish(artifact, dest, ctx)

    assert result.is_success
    assert result.status == "SUCCESS"
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == content
    assert result.content_hash == content_hash
    assert result.destination_type == "plain_text"


def test_plain_text_publisher_directory_target(tmp_path: Path) -> None:
    output_dir = tmp_path / "campaign_posts"
    output_dir.mkdir()

    artifact = PublicationArtifact(
        title="AI: Fast Code, Slow Verification?",
        content="Testing directory destination auto-filename.",
        format="txt",
        source_run_id="run-456",
        authorized_sha256="abc",
    )
    dest = PublishDestination(destination_type="plain_text", target=str(output_dir))
    ctx = PublishContext(run_id="run-456")

    publisher = PlainTextPublisher()
    result = publisher.publish(artifact, dest, ctx)

    assert result.is_success
    expected_file = output_dir / "AI_Fast_Code_Slow_Verification.txt"
    assert expected_file.exists()
    assert expected_file.read_text(encoding="utf-8") == "Testing directory destination auto-filename."


def test_plain_text_publisher_append_mode(tmp_path: Path) -> None:
    target_file = tmp_path / "changelog.txt"
    target_file.write_text("Initial log entry.", encoding="utf-8")

    artifact = PublicationArtifact(
        title="Update",
        content="Second log entry.",
        format="txt",
        source_run_id="run-789",
        authorized_sha256="xyz",
    )
    dest = PublishDestination(
        destination_type="plain_text",
        target=str(target_file),
        update_mode="append",
    )
    ctx = PublishContext(run_id="run-789")

    publisher = PlainTextPublisher()
    result = publisher.publish(artifact, dest, ctx)

    assert result.is_success
    final_text = target_file.read_text(encoding="utf-8")
    assert "Initial log entry." in final_text
    assert "Second log entry." in final_text


def test_plain_text_publisher_dry_run(tmp_path: Path) -> None:
    target_file = tmp_path / "should_not_exist.txt"
    artifact = PublicationArtifact(
        title="Dry Run Test",
        content="Ephemeral content.",
        format="txt",
        source_run_id="run-dry",
        authorized_sha256="123",
    )
    dest = PublishDestination(destination_type="plain_text", target=str(target_file))
    ctx = PublishContext(run_id="run-dry", dry_run=True)

    publisher = PlainTextPublisher()
    result = publisher.publish(artifact, dest, ctx)

    assert result.is_success
    assert not target_file.exists()
    assert "dry_run: file write skipped" in result.diagnostics


def test_registry_supports_plain_text_aliases() -> None:
    supported = list_supported_destinations()
    assert "plain_text" in supported
    assert "local" in supported

    for alias in ["plain_text", "plain-text", "txt", "local", "text", "file"]:
        pub = get_publisher(alias)
        assert isinstance(pub, PlainTextPublisher)
