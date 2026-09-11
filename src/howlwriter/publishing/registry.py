"""Central registry for artifact publishers."""

from __future__ import annotations

from typing import Callable

from howlwriter.publishing.base import ArtifactPublisher


class UnsupportedDestinationError(ValueError):
    """Raised when an artifact publisher for a destination type is not registered."""


class PublisherRegistry:
    """Registry maintaining active and lazy-loaded publishers."""

    def __init__(self) -> None:
        self._publishers: dict[str, ArtifactPublisher] = {}
        self._factories: dict[str, Callable[[], ArtifactPublisher]] = {}

    def register(
        self,
        destination_type: str,
        publisher: ArtifactPublisher | Callable[[], ArtifactPublisher],
    ) -> None:
        key = destination_type.strip().lower()
        if callable(publisher) and not hasattr(publisher, "publish"):
            self._factories[key] = publisher
            self._publishers.pop(key, None)
        else:
            self._publishers[key] = publisher  # type: ignore[assignment]
            self._factories.pop(key, None)

    def get(self, destination_type: str) -> ArtifactPublisher:
        key = destination_type.strip().lower()
        if key in self._publishers:
            return self._publishers[key]

        if key in self._factories:
            publisher = self._factories[key]()
            self._publishers[key] = publisher
            return publisher

        # Built-in lazy resolution for google_docs
        if key in ("google_docs", "google-docs", "gdocs", "google"):
            from howlwriter.publishing.google.publisher import GoogleDocsPublisher

            pub = GoogleDocsPublisher()
            self._publishers[key] = pub
            return pub

        supported = sorted(set(list(self._publishers.keys()) + list(self._factories.keys()) + ["google_docs"]))
        raise UnsupportedDestinationError(
            f"Unsupported publishing destination '{destination_type}'. "
            f"Supported destinations: {', '.join(supported)}"
        )

    def list_supported(self) -> list[str]:
        keys = set(self._publishers.keys()) | set(self._factories.keys()) | {"google_docs"}
        return sorted(keys)


_GLOBAL_REGISTRY = PublisherRegistry()


def get_publisher(destination_type: str) -> ArtifactPublisher:
    """Convenience getter from global registry."""
    return _GLOBAL_REGISTRY.get(destination_type)


def register_publisher(
    destination_type: str,
    publisher: ArtifactPublisher | Callable[[], ArtifactPublisher],
) -> None:
    """Convenience registration on global registry."""
    _GLOBAL_REGISTRY.register(destination_type, publisher)
