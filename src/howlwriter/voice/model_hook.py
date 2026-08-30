"""Reserved model-backed hook for qualitative voice analysis (tone, humor,
formality judgment) that a deterministic corpus scan cannot honestly
produce. Unconfigured by default -- see integration/model_role.py."""

from __future__ import annotations

from typing import Protocol

from howlwriter.domain.voice import VoiceProfile
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole


class VoiceAnalyzer(Protocol):
    role: WritingRole

    def analyze(self, corpus: list[str], existing_profile: VoiceProfile) -> VoiceProfile: ...


class NotConfiguredVoiceAnalyzer(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.VOICE_REVIEWER)

    def analyze(self, corpus: list[str], existing_profile: VoiceProfile) -> VoiceProfile:
        return self.run(corpus, existing_profile)
