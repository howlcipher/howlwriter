import pytest

from howlwriter.integration.model_role import ModelRoleNotConfiguredError, NotConfiguredRole, WritingRole


def test_not_configured_role_raises_named_error():
    role = NotConfiguredRole(WritingRole.RESEARCHER)
    with pytest.raises(ModelRoleNotConfiguredError) as excinfo:
        role.run("anything")
    assert excinfo.value.role is WritingRole.RESEARCHER
    assert "researcher" in str(excinfo.value)
    assert "not configured" in str(excinfo.value)


@pytest.mark.parametrize("role", list(WritingRole))
def test_every_role_raises_when_not_configured(role):
    with pytest.raises(ModelRoleNotConfiguredError):
        NotConfiguredRole(role).run()
