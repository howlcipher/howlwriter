"""Tests for RealModelMeaningReviewer executing via HowlPlane."""

import pytest

from howlwriter.domain.document import Document
from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from howlwriter.integration.model_role import (
    ModelRoleNotConfiguredError,
    WritingRole,
)
from howlwriter.review.meaning import (
    RealModelMeaningReviewer,
    SemanticMeaningResult,
)
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBindingRegistry,
    RoleDispatcher,
)


def test_model_meaning_reviewer_unconfigured_raises():
    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)

    orig = Document.parse("Original 10 apples.")
    rev = Document.parse("Revised 10 apples.")

    reviewer = RealModelMeaningReviewer()
    with pytest.raises(ModelRoleNotConfiguredError) as exc_info:
        reviewer.compare(orig, rev)
    assert exc_info.value.role == WritingRole.FINAL_REVIEWER


def test_model_meaning_reviewer_pass_verdict():
    fake_backend = FakeAgentBackend(
        agent_id="gpt_reviewer",
        default_stdout="""```yaml
verdict: "PASS"
differences: []
rationale: "Prose was tightened without altering factual claims."
```""",
    )

    orig = Document.parse("The team deployed the update on Tuesday.")
    rev = Document.parse("The team rolled out the update on Tuesday.")

    reviewer = RealModelMeaningReviewer()
    res = reviewer.compare(
        orig, rev, humanizer_provider="claude_humanizer", custom_backend=fake_backend
    )

    assert isinstance(res, SemanticMeaningResult)
    assert res.verdict == "PASS"
    assert len(res.differences) == 0
    assert "tightened" in res.rationale
    assert res.provider == "gpt_reviewer"


def test_model_meaning_reviewer_fail_verdict():
    fake_backend = FakeAgentBackend(
        agent_id="adversarial_reviewer",
        default_stdout="""```yaml
verdict: "FAIL"
differences:
  - kind: "altered_fact"
    description: "Changed release day from Tuesday to Friday."
    severity: "blocker"
  - kind: "stronger_claim"
    description: "Claimed 100% reliability instead of 99%."
    severity: "blocker"
rationale: "Factual deviations detected."
```""",
    )

    orig = Document.parse("The release is planned for Tuesday with 99% uptime.")
    rev = Document.parse("The release is guaranteed Friday with 100% uptime.")

    reviewer = RealModelMeaningReviewer()
    res = reviewer.compare(
        orig, rev, humanizer_provider="claude_humanizer", custom_backend=fake_backend
    )

    assert res.verdict == "FAIL"
    assert len(res.differences) == 2
    assert res.differences[0].kind == "altered_fact"
    assert "Tuesday to Friday" in res.differences[0].description
