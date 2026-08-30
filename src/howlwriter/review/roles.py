"""The writing-role vocabulary and a minimal lookup registry.

WritingRole itself lives in integration/model_role.py (the single source
of truth for the seam every model-backed capability shares); this module
re-exports it and adds RoleExecutor/RoleRegistry, a small lookup table for
whichever concrete implementation currently handles a given role. The
registry does not execute anything on HowlWriter's behalf -- it is just a
place to look up "who handles WRITER right now" when assembling a pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from howlwriter.integration.model_role import WritingRole

__all__ = ["WritingRole", "RoleExecutor", "RoleRegistry"]


class RoleExecutor(Protocol):
    role: WritingRole

    def run(self, request: object) -> object: ...


@dataclass
class RoleRegistry:
    executors: dict[WritingRole, RoleExecutor] = field(default_factory=dict)

    def register(self, executor: RoleExecutor) -> None:
        self.executors[executor.role] = executor

    def get(self, role: WritingRole) -> RoleExecutor | None:
        return self.executors.get(role)
