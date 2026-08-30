import pytest

from howlwriter.domain.voice import VoiceProfile
from howlwriter.integration.model_role import ModelRoleNotConfiguredError, WritingRole
from howlwriter.voice.model_hook import NotConfiguredVoiceAnalyzer


def test_not_configured_voice_analyzer_raises():
    analyzer = NotConfiguredVoiceAnalyzer()
    with pytest.raises(ModelRoleNotConfiguredError) as excinfo:
        analyzer.analyze(["some text"], VoiceProfile(author_name="x"))
    assert excinfo.value.role is WritingRole.VOICE_REVIEWER
