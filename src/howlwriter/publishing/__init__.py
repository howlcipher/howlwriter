"""Artifact publishing abstraction and destination adapters."""

from howlwriter.publishing.base import (
    ArtifactPublisher,
    PublicationArtifact,
    PublishContext,
    PublishDestination,
    PublishResult,
)
from howlwriter.publishing.registry import (
    PublisherRegistry,
    UnsupportedDestinationError,
    get_publisher,
    register_publisher,
)

__all__ = [
    "ArtifactPublisher",
    "PublicationArtifact",
    "PublishContext",
    "PublishDestination",
    "PublishResult",
    "PublisherRegistry",
    "UnsupportedDestinationError",
    "get_publisher",
    "register_publisher",
]
