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

import sys

import enum
from typing import Protocol, runtime_checkable


class WritingRole(enum.Enum):
    WRITER = "writer"
    EDITOR = "editor"
    HUMANIZER = "humanizer"
    VOICE_REVIEWER = "voice_reviewer"
    # Abstract style analysis over a corpus of the user's own writing. Kept
    # distinct from VOICE_REVIEWER, which judges one transformed document
    # against its original; this role never sees a draft and never edits.
    VOICE_ANALYST = "voice_analyst"
    FACT_CHECKER = "fact_checker"
    RESEARCHER = "researcher"
    RED_PEN = "red_pen"
    CITATION_VALIDATOR = "citation_validator"
    FINAL_REVIEWER = "final_reviewer"


class ModelRoleNotConfiguredError(RuntimeError):
    """Raised when a model-backed capability is invoked with no implementation wired in."""

    def __init__(self, role: WritingRole, detail: str = ""):
        self.role = role
        if detail:
            super().__init__(f"{role.value}: {detail}")
            return
        # Imported here: the bridge imports this module.
        from howlwriter.integration.howlplane_bridge import howlplane_import_problem

        problem = howlplane_import_problem()
        if problem:
            super().__init__(
                f"{role.value} cannot run: {problem}. Install the missing package in that "
                f"Python environment and run again. See docs/howlplane-integration.md."
            )
            return
        super().__init__(
            f"{role.value} needs a model. Run interactively to be asked which one, or pass "
            f"--provider claude|agy|codex|local (or set HOWLWRITER_PROVIDER). "
            f"{role.value} is not configured. HowlWriter defines the contract; "
            f"provide an implementation (e.g. via HowlPlane model execution) "
            f"to enable this capability. Install HowlPlane in the same Python "
            f"environment or set HOWLPLANE_ROOT to its source checkout. "
            f"Explicitly select an available provider with "
            f"HOWLPLANE_ROLE_WRITING_{role.value.upper()}=<provider>. "
            f"See docs/howlplane-integration.md for setup."
        )


class HowlPlaneUnavailableError(RuntimeError):
    """A model was chosen for a step, but HowlPlane, which runs it, cannot be imported.

    Distinct from ModelRoleNotConfiguredError ("no model chosen"): choosing a model
    again cannot help, and a rule-based fallback would silently ignore the choice.
    """

    def __init__(self, role: WritingRole, provider: str):
        self.role = role
        self.provider = provider
        from howlwriter.integration.howlplane_bridge import howlplane_import_problem

        why = howlplane_import_problem() or (
            f"HowlPlane is not installed in this Python environment ({sys.executable})"
        )
        super().__init__(
            f"{role.value}: model {provider!r} was chosen, but it runs through HowlPlane and {why}. "
            f"Install it with `pip install 'howlwriter[plane]'` (a Howl install provides it), "
            f"or point HOWLPLANE_ROOT (or HOWLPLANE_HOME) at a HowlPlane checkout. "
            f"See docs/howlplane-integration.md."
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
