import pytest

from howlwriter.integration.model_role import ModelRoleNotConfiguredError, WritingRole
from howlwriter.research.researcher import NotConfiguredResearcher, ResearchQuery


def test_not_configured_researcher_raises():
    researcher = NotConfiguredResearcher()
    with pytest.raises(ModelRoleNotConfiguredError) as excinfo:
        researcher.research(ResearchQuery(text="climate policy"))
    assert excinfo.value.role is WritingRole.RESEARCHER
