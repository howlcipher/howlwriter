"""Tests for destination-neutral publisher registry and authority gate boundaries."""

import pytest

from howlwriter.publishing.base import (
    ArtifactPublisher,
    PublicationArtifact,
    PublishContext,
    PublishDestination,
    PublishResult,
)
from howlwriter.publishing.google.fake import FakeGoogleDocsAdapter
from howlwriter.publishing.google.publisher import GoogleDocsPublisher
from howlwriter.publishing.registry import (
    PublisherRegistry,
    UnsupportedDestinationError,
)


class DummyPublisher(ArtifactPublisher):
    def __init__(self, name: str = "dummy") -> None:
        self.name = name

    def publish(
        self,
        artifact: PublicationArtifact,
        destination: PublishDestination,
        context: PublishContext,
    ) -> PublishResult:
        return PublishResult(
            destination_type=destination.destination_type,
            destination_target=destination.target,
            artifact_title=artifact.title,
            artifact_id="dummy-123",
            url="https://dummy.example.com/doc",
            status="SUCCESS",
        )


def test_publisher_registry():
    reg = PublisherRegistry()
    dummy = DummyPublisher()
    reg.register("my_custom_dest", dummy)

    assert reg.get("my_custom_dest") is dummy
    assert reg.get("MY_CUSTOM_DEST") is dummy

    with pytest.raises(UnsupportedDestinationError):
        reg.get("nonexistent_dest")


def test_publisher_lazy_google_docs():
    reg = PublisherRegistry()
    pub1 = reg.get("google_docs")
    assert isinstance(pub1, GoogleDocsPublisher)

    pub2 = reg.get("gdocs")
    assert isinstance(pub2, GoogleDocsPublisher)


def test_publishing_authority_gate_blocks_unverified():
    fake_adapter = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake_adapter)

    artifact = PublicationArtifact(
        title="Unverified Draft",
        content="Some draft content",
        format="md",
        source_run_id="run-1",
        authorized_sha256="hash-1",
        metadata={"status": "DRAFT"},  # Not READY or PASS
    )
    dest = PublishDestination(destination_type="google_docs", target="Folder")
    ctx = PublishContext(run_id="run-1", allow_unverified=False)

    result = publisher.publish(artifact, dest, ctx)
    assert not result.is_success
    assert result.status == "FAILED"
    assert any("authority gate" in d.lower() or "unverified" in d.lower() for d in result.diagnostics)


def test_publishing_authority_gate_passes_when_authorized():
    fake_adapter = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake_adapter)

    # 1. Status is READY
    ready_artifact = PublicationArtifact(
        title="Verified Ready Paper",
        content="Polished verified content",
        format="md",
        source_run_id="run-2",
        authorized_sha256="hash-2",
        metadata={"status": "READY"},
    )
    dest = PublishDestination(destination_type="google_docs", target="Folder")
    ctx = PublishContext(run_id="run-2", allow_unverified=False)

    result = publisher.publish(ready_artifact, dest, ctx)
    assert result.is_success
    assert result.artifact_id is not None
    assert "docs.google.com" in result.url

    # 2. Status is UNVERIFIED but allow_unverified=True was explicitly set
    unverified_artifact = PublicationArtifact(
        title="Draft Override Paper",
        content="Draft content",
        format="md",
        source_run_id="run-3",
        authorized_sha256="hash-3",
        metadata={"status": "DRAFT"},
    )
    ctx_override = PublishContext(run_id="run-3", allow_unverified=True)
    result_override = publisher.publish(unverified_artifact, dest, ctx_override)
    assert result_override.is_success
