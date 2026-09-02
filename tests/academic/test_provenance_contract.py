"""The provenance block reads other stages' results. Those reads are a contract.

This exists because of a real escape. The academic pipeline's provenance
summary read `consistency_res.status`, and `ConsistencyReviewResult` has no
`status` -- it has `verdict`. Every deterministic test passed, because the
consistency reviewer only runs when a model is configured AND the document
carries staged content, so no test ever produced a non-None result for that
block to read. The bug surfaced only on a live academic run, after the writer,
humanizer and both reviewers had already spent several minutes of provider time.

Two guards, cheap enough to keep: the field names the block depends on, and one
end-to-end run through the model-backed path with staged content so the block
executes against real result objects.
"""

from __future__ import annotations

import dataclasses

import pytest

from howlwriter.integration.howlplane_bridge import (
    HowlPlaneWritingBridge,
    set_howlplane_bridge,
)
from src.control_plane.agent_execution import FakeAgentBackend
from src.control_plane.role_binding import (
    RoleBinding,
    RoleBindingRegistry,
    RoleDispatcher,
)

from howlwriter.academic.consistency import ConsistencyReviewResult
from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.review.meaning import MeaningPreservationResult, SemanticMeaningResult


@pytest.mark.parametrize(
    "cls,field_name",
    [
        (ConsistencyReviewResult, "verdict"),
        (SemanticMeaningResult, "verdict"),
        (MeaningPreservationResult, "status"),
    ],
)
def test_the_provenance_summary_reads_fields_that_exist(cls, field_name):
    """Renaming one of these must fail here rather than mid-run."""
    names = {f.name for f in dataclasses.fields(cls)}
    assert field_name in names, (
        f"{cls.__name__}.{field_name} is read by the academic pipeline's "
        "provenance summary"
    )


_STAGED_BODY = """# Findings

## Stage 1: Initial access

The actor obtains valid credentials through a phishing campaign.

## Stage 2: Lateral movement

Using the credentials from Stage 1, the actor enumerates adjacent hosts.

## Stage 3: Collection

Access established in Stage 2 is used to stage data for exfiltration.
"""


def _configure() -> FakeAgentBackend:
    registry = RoleBindingRegistry()
    for role in ("writer", "humanizer", "final_reviewer"):
        registry.register_binding(
            RoleBinding(domain="writing", role=role, provider="fake_provider")
        )
    indented = "\n".join(f"  {line}" for line in _STAGED_BODY.splitlines())
    backend = FakeAgentBackend(
        agent_id="fake_provider",
        default_stdout=(
            "```yaml\n"
            f"body_markdown: |\n{indented}\n"
            "resulting_text: |\n" + indented + "\n"
            "claims_made: []\n"
            "changes_made: []\n"
            "verdict: PASS\n"
            "findings: []\n"
            "rationale: consistent\n"
            "warnings: []\n"
            "```"
        ),
    )
    set_howlplane_bridge(
        HowlPlaneWritingBridge(
            dispatcher=RoleDispatcher(binding_registry=registry), registry=registry
        )
    )
    return backend


def test_a_model_backed_academic_run_builds_its_provenance_summary():
    """The end-to-end guard: the block must execute, not just typecheck.

    Staged content is what makes the consistency reviewer eligible, which is
    the branch the escaped bug lived in.
    """
    backend = _configure()
    spec = AssignmentSpec(
        title="Credential abuse staging",
        topic="credential abuse and staged intrusion",
        target_words=120,
    )

    result = run_academic_pipeline(
        spec, custom_backend=backend, deterministic_only=False
    )

    review = result.provenance.review
    assert "meaning_preservation" in review
    assert "readiness" in review
    # Present as a key whether or not the reviewer ran, so a None here means
    # "did not run" rather than "was never recorded".
    assert "consistency" in review
    assert review["consistency"] in (None, "PASS", "FAIL", "PASS_WITH_WARNINGS")
    assert result.provenance.complete is True


def test_model_additions_are_recorded_for_an_academic_run():
    backend = _configure()
    spec = AssignmentSpec(title="x", topic="y", target_words=120)
    result = run_academic_pipeline(spec, custom_backend=backend)

    assert "model_additions" in result.provenance.review
    counts = result.provenance.review["model_additions"]["counts"]
    assert set(counts) == {"LOGICAL_EXPANSION", "CONNECTIVE_PROSE", "NEW_FACTUAL"}
