"""Tests for the sequence-dependency + heading/label consistency reviewer."""

import pytest

from howlwriter.academic.consistency import (
    ConsistencyReviewResult,
    RealModelConsistencyReviewer,
    has_staged_content,
)
from howlwriter.domain.document import Document
from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from howlwriter.integration.model_role import (
    ModelRoleNotConfiguredError,
    WritingRole,
)
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import RoleBindingRegistry, RoleDispatcher


def test_has_staged_content_detects_numbered_stages():
    doc = Document.parse(
        "# Attack Chain\n\n"
        "Stage 1: Initial Access via leaked credentials.\n\n"
        "Stage 2: Discovery of IAM permissions."
    )
    assert has_staged_content(doc) is True


def test_has_staged_content_false_for_prose_without_stages():
    doc = Document.parse(
        "# Zero Trust Overview\n\n"
        "Zero trust architectures assume no implicit trust between network "
        "segments and continuously verify every request."
    )
    assert has_staged_content(doc) is False


def test_model_consistency_reviewer_unconfigured_raises():
    registry = RoleBindingRegistry()
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)

    doc = Document.parse("# Title\n\nSome content.")
    reviewer = RealModelConsistencyReviewer()
    with pytest.raises(ModelRoleNotConfiguredError) as exc_info:
        reviewer.review(doc, sources=[], staged_content_detected=False)
    assert exc_info.value.role == WritingRole.FINAL_REVIEWER


def test_model_consistency_reviewer_pass_verdict():
    fake_backend = FakeAgentBackend(
        agent_id="gpt_reviewer",
        default_stdout="""```yaml
verdict: "PASS"
findings: []
rationale: "Headings match content and citations are topically well-attached."
```""",
    )
    doc = Document.parse("# Zero Trust Overview\n\nZero trust assumes no implicit trust.")

    reviewer = RealModelConsistencyReviewer()
    res = reviewer.review(
        doc, sources=[], staged_content_detected=False, custom_backend=fake_backend
    )

    assert isinstance(res, ConsistencyReviewResult)
    assert res.verdict == "PASS"
    assert len(res.findings) == 0
    assert res.sequence_check_performed is False


def test_model_consistency_reviewer_fail_verdict_with_sequence_contradiction():
    fake_backend = FakeAgentBackend(
        agent_id="adversarial_reviewer",
        default_stdout="""```yaml
verdict: "FAIL"
findings:
  - kind: "SEQUENCE_CONTRADICTION"
    description: "Stage 2 pivots into the production Kubernetes pod before Stage 3 grants that access."
    severity: "blocker"
    location_hint: "Stage 2"
  - kind: "LABEL_MISMATCH"
    description: "Section titled Software Supply-Chain Compromise only describes leaked credentials."
    severity: "blocker"
    location_hint: "Chain One heading"
rationale: "Two blocker-severity inconsistencies detected."
```""",
    )
    doc = Document.parse(
        "# Software Supply-Chain Compromise\n\n"
        "Stage 1: Leaked credentials found in a public repository.\n\n"
        "Stage 2: Attacker pivots into the production Kubernetes pod.\n\n"
        "Stage 3: Attacker escalates from the development account to production."
    )

    reviewer = RealModelConsistencyReviewer()
    res = reviewer.review(
        doc, sources=[], staged_content_detected=True, custom_backend=fake_backend
    )

    assert res.verdict == "FAIL"
    assert len(res.findings) == 2
    kinds = {f.kind for f in res.findings}
    assert "SEQUENCE_CONTRADICTION" in kinds
    assert "LABEL_MISMATCH" in kinds
    assert res.sequence_check_performed is True
