from howlwriter.integration.model_role import WritingRole
from howlwriter.review.roles import RoleRegistry
from howlwriter.voice.model_hook import NotConfiguredVoiceAnalyzer


def test_registry_returns_none_for_unregistered_role():
    registry = RoleRegistry()
    assert registry.get(WritingRole.RESEARCHER) is None


def test_registry_registers_and_looks_up_by_role():
    registry = RoleRegistry()
    executor = NotConfiguredVoiceAnalyzer()
    registry.register(executor)
    assert registry.get(WritingRole.VOICE_REVIEWER) is executor
