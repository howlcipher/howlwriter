"""Researcher: real network research, unconfigured by default.

Deliberately Protocol-only for the MVP. Even a "simple" HTTP fetch built
here would risk exactly the provider-coupling and duplicated execution
logic that HowlPlane is meant to own -- see docs/howlplane-integration.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole


@dataclass
class ResearchQuery(DataClassSerializationMixin):
    text: str
    max_sources: int = 5


class Researcher(Protocol):
    role: WritingRole

    def research(self, query: ResearchQuery) -> list[Source]: ...


class NotConfiguredResearcher(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.RESEARCHER)

    def research(self, query: ResearchQuery) -> list[Source]:
        return self.run(query)
