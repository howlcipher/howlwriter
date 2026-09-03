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
from howlwriter.domain.generation_provenance import (
    GenerationProvenance,
    ReviewerFallbackRecord,
)
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBinding,
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


def test_model_meaning_reviewer_fallback_backend_produces_fallback_record():
    primary_backend = FakeAgentBackend(
        agent_id="primary_failing_reviewer",
        default_exit_code=1,
        default_stderr="Primary reviewer crashed with 500 error",
    )
    fallback_backend = FakeAgentBackend(
        agent_id="secondary_fallback_reviewer",
        default_exit_code=0,
        default_stdout="""```yaml
verdict: "PASS"
differences: []
rationale: "Fallback review verified prose integrity."
```""",
    )

    orig = Document.parse("Deploy safely to staging first.")
    rev = Document.parse("Roll out safely to staging first.")

    reviewer = RealModelMeaningReviewer()
    res = reviewer.compare(
        orig,
        rev,
        humanizer_provider="claude_humanizer",
        custom_backend=primary_backend,
        fallback_backend=fallback_backend,
    )

    assert isinstance(res, SemanticMeaningResult)
    assert res.verdict == "PASS"
    assert res.fallback_record is not None
    assert isinstance(res.fallback_record, ReviewerFallbackRecord)
    assert res.fallback_record.stage == "meaning_review"
    assert res.fallback_record.requested_reviewer == str(primary_backend)
    assert res.fallback_record.fallback_reviewer == str(fallback_backend)
    assert "Exit code 1" in res.fallback_record.failure_reason
    assert res.fallback_record.provider == "secondary_fallback_reviewer"
    assert res.fallback_record.independence_status == "INDEPENDENT"

    prov = GenerationProvenance(
        run_id="test-run", reviewer_fallbacks=[res.fallback_record]
    )
    d = prov.to_dict()
    assert len(d["reviewer_fallbacks"]) == 1
    assert d["reviewer_fallbacks"][0]["stage"] == "meaning_review"
    assert d["reviewer_fallbacks"][0]["independence_status"] == "INDEPENDENT"


def test_model_meaning_reviewer_same_provider_fallback():
    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(
            domain="writing",
            role="final_reviewer",
            provider="claude_humanizer",
        )
    )
    dispatcher = RoleDispatcher(binding_registry=registry)
    bridge = HowlPlaneWritingBridge(dispatcher=dispatcher, registry=registry)
    set_howlplane_bridge(bridge)

    call_count = 0

    def side_effect(task, cwd, prompt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("avoiding claude_humanizer: no independent reviewer available")

    fake_backend = FakeAgentBackend(
        agent_id="claude_humanizer",
        default_stdout="""```yaml
verdict: "PASS"
differences: []
rationale: "Same provider fallback review verified prose integrity."
```""",
        side_effect=side_effect,
    )

    orig = Document.parse("Deploy safely to staging first.")
    rev = Document.parse("Roll out safely to staging first.")

    reviewer = RealModelMeaningReviewer()
    res = reviewer.compare(
        orig,
        rev,
        humanizer_provider="claude_humanizer",
        custom_backend=fake_backend,
    )

    assert isinstance(res, SemanticMeaningResult)
    assert res.verdict == "PASS"
    assert res.fallback_record is not None
    assert isinstance(res.fallback_record, ReviewerFallbackRecord)
    assert res.fallback_record.stage == "meaning_review"
    assert res.fallback_record.failure_reason == "No independent reviewer available"
    assert res.fallback_record.requested_reviewer == str(fake_backend)
    assert res.fallback_record.fallback_reviewer == str(fake_backend)
    assert res.fallback_record.provider == "claude_humanizer"
    assert res.fallback_record.independence_status == "SAME_PROVIDER"
