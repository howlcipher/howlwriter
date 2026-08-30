"""The one seam every model-backed capability in HowlWriter shares.

HowlWriter never calls a model API itself -- provider routing, retries, and
execution are a HowlPlane concern (see docs/howlplane-integration.md).
Every capability that needs a model (rewriting, semantic claim
verification, research, qualitative voice analysis, semantic meaning
comparison) is defined here as a typed Protocol plus a NotConfigured*
default that fails loudly and specifically, instead of silently returning a
fake or empty result.
"""

from __future__ import annotations

import enum
from typing import Protocol, runtime_checkable


class WritingRole(enum.Enum):
    WRITER = "writer"
    EDITOR = "editor"
    HUMANIZER = "humanizer"
    VOICE_REVIEWER = "voice_reviewer"
    FACT_CHECKER = "fact_checker"
    RESEARCHER = "researcher"
    RED_PEN = "red_pen"
    CITATION_VALIDATOR = "citation_validator"
    FINAL_REVIEWER = "final_reviewer"


class ModelRoleNotConfiguredError(RuntimeError):
    """Raised when a model-backed capability is invoked with no implementation wired in."""

    def __init__(self, role: WritingRole):
        self.role = role
        super().__init__(
            f"{role.value} is not configured. HowlWriter defines the contract; "
            f"provide an implementation (e.g. via HowlPlane model execution) "
            f"to enable this capability."
        )


@runtime_checkable
class ModelBackedRole(Protocol):
    """Shared shape for a model-backed capability. `request` and the return
    type are intentionally capability-specific -- each concrete Protocol
    (HumanizerRewriter, ClaimVerifier, Researcher, VoiceAnalyzer,
    ModelMeaningReviewer, ...) narrows `run`'s signature for its own use."""

    role: WritingRole

    def run(self, request: object) -> object: ...


class NotConfiguredRole:
    """Default implementation for any ModelBackedRole: always raises."""

    role: WritingRole

    def __init__(self, role: WritingRole):
        self.role = role

    def run(self, *args: object, **kwargs: object) -> object:
        raise ModelRoleNotConfiguredError(self.role)
