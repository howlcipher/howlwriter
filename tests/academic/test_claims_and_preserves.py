"""Tests for academic pipeline claims provenance, outline preserve gating, and reviewer independence."""

from __future__ import annotations

import pytest

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.domain.outline import NodeKind, Outline, OutlineNode
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


class _SequenceBackend(FakeAgentBackend):
    """Return one deterministic structured response per model stage."""

    def __init__(self, outputs: list[str]):
        super().__init__(agent_id="fake_provider")
        self.outputs = list(outputs)

    def execute(self, *args, **kwargs):
        if not self.outputs:
            raise AssertionError("pipeline made more model calls than expected")
        self.default_stdout = self.outputs.pop(0)
        return super().execute(*args, **kwargs)


def _configure_backend(
    body_markdown: str,
    claims_made: list[dict] | None = None,
    added_claims: list[dict] | None = None,
) -> FakeAgentBackend:
    registry = RoleBindingRegistry()
    for role in ("writer", "humanizer", "final_reviewer"):
        registry.register_binding(
            RoleBinding(domain="writing", role=role, provider="fake_provider")
        )

    def _claims_yaml(label: str, entries: list[dict] | None) -> str:
        if not entries:
            return f"{label}: []\n"
        claims_lines = [f"{label}:"]
        for c in entries:
            claims_lines.append(f"  - claim: {c.get('claim', '')}")
            claims_lines.append(f"    source_id: {c.get('source_id', '')}")
            claims_lines.append(f"    evidence_snippet: {c.get('evidence_snippet', '')}")
            if c.get("basis"):
                claims_lines.append(f"    basis: {c['basis']}")
        return "\n".join(claims_lines) + "\n"

    claims_yaml = _claims_yaml("claims_made", claims_made)
    additions_yaml = _claims_yaml("added_claims", added_claims)

    indented = "\n".join(f"  {line}" for line in body_markdown.splitlines())
    backend = FakeAgentBackend(
        agent_id="fake_provider",
        default_stdout=(
            "```yaml\n"
            f"body_markdown: |\n{indented}\n"
            f"resulting_text: |\n{indented}\n"
            f"{claims_yaml}"
            f"{additions_yaml}"
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


def test_model_stated_claims_populate_added_claims_and_contribution():
    claims = [
        {
            "claim": "Consensus protocols require a strict majority quorum under crash faults.",
            "source_id": "lamport1998",
            "evidence_snippet": "Section 3, page 5.",
        }
    ]
    body = (
        "# Fault Tolerance\n\n"
        "Consensus protocols require a strict majority quorum under crash faults. "
        "This guarantees safety across network partitions."
    )
    backend = _configure_backend(body, claims_made=claims)
    spec = AssignmentSpec(
        title="Consensus Analysis",
        topic="fault tolerance and consensus quorums",
        target_words=50,
    )

    result = run_academic_pipeline(
        spec, custom_backend=backend, deterministic_only=False
    )

    # 1. Added claims captured in provenance
    assert len(result.provenance.added_claims) == 1
    added = result.provenance.added_claims[0]
    assert "strict majority quorum" in added["claim"]
    assert added["source_id"] == "lamport1998"

    # 2. Contribution model_added_claims incremented
    assert result.provenance.contribution is not None
    assert result.provenance.contribution.model_added_claims == 1

    # 3. AI Use statement discloses model added claims
    statement = result.ai_use_statement or getattr(result.provenance, "ai_use_statement", None)
    assert statement is not None
    statement_str = statement.statement if hasattr(statement, "statement") else str(statement)
    assert "factual assertion" in statement_str.lower() or "claim" in statement_str.lower()


def test_user_outline_claim_is_not_relabeled_as_a_model_added_fact():
    user_claim = "Bounded queues absorb short traffic bursts."
    model_fact = "A 2024 study reported that 70 percent of queues were unbounded."
    claims = [
        {"claim": user_claim},
        {"claim": model_fact, "source_id": ""},
    ]
    backend = _configure_backend(
        f"# Queues\n\n{user_claim}\n\n{model_fact}",
        claims_made=claims,
        # Deliberately mislabel both. The pipeline must not trust this list
        # enough to attribute the user's own commitment to the model.
        added_claims=claims,
    )
    outline = Outline(
        title="Queues",
        topic="queue design",
        nodes=[OutlineNode(id="c1", kind=NodeKind.CLAIM, text=user_claim)],
    )
    spec = AssignmentSpec(
        title="Queues",
        topic="queue design",
        target_words=25,
        word_tolerance_percent=50,
        source_requirements=dict(minimum_sources=0),
    )

    result = run_academic_pipeline(
        spec,
        outline=outline,
        custom_backend=backend,
        max_length_retries=0,
    )

    assert [item["claim"] for item in result.provenance.added_claims] == [
        model_fact
    ]
    counts = result.provenance.review["model_additions"]["counts"]
    assert counts["NEW_FACTUAL"] == 1
    assert result.provenance.contribution.model_added_claims == 1
    assert result.report.status == "NEEDS_REVIEW"


def test_preserved_outline_node_survival_and_gating():
    preserved_sentence = "This specific mathematical proof step must be preserved verbatim."
    outline = Outline(
        title="Proof Section",
        topic="formal proof",
        nodes=[
            OutlineNode(
                id="h1",
                kind=NodeKind.HEADING,
                text="Derivation",
            ),
            OutlineNode(
                id="p1",
                kind=NodeKind.PRESERVE,
                text=preserved_sentence,
            ),
        ],
    )

    # Arm 1: Writer preserves the sentence verbatim -> authorship check passes
    body_pass = f"# Derivation\n\n{preserved_sentence}\n\nHence the lemma holds."
    backend_pass = _configure_backend(body_pass)
    spec_pass = AssignmentSpec(
        title="Formal Proof",
        topic="mathematical proof",
        target_words=40,
    )
    res_pass = run_academic_pipeline(
        spec_pass, outline=outline, custom_backend=backend_pass, deterministic_only=False
    )
    assert res_pass.authorship_coverage is not None
    assert res_pass.authorship_coverage.status == "PASS"
    assert res_pass.provenance.coverage["status"] == "PASS"
    assert res_pass.authorship_coverage.preserved_retained == 1

    # Arm 2: a writer that alters verbatim text is rejected before an altered
    # artifact can enter later stages.
    body_fail = (
        "# Derivation\n\n"
        "This proof step was rewritten and paraphrased by the model.\n\n"
        "Hence the lemma holds."
    )
    backend_fail = _configure_backend(body_fail)
    spec_fail = AssignmentSpec(
        title="Formal Proof",
        topic="mathematical proof",
        target_words=40,
    )
    with pytest.raises(RuntimeError, match="verbatim-preserve contract"):
        run_academic_pipeline(
            spec_fail,
            outline=outline,
            custom_backend=backend_fail,
            deterministic_only=False,
        )


def test_humanizer_that_alters_preserved_text_is_rejected_and_recorded():
    preserved = "This sentence remains exactly as the author supplied it."
    original = f"# Derivation\n\n{preserved}\n\nThe argument then concludes."
    altered = original.replace("exactly as", "in the form")

    def yaml_block(field: str, text: str, tail: str) -> str:
        indented = "\n".join(f"  {line}" for line in text.splitlines())
        return (
            "\x60\x60\x60yaml\n"
            f"{field}: |\n{indented}\n"
            f"{tail}"
            "\x60\x60\x60"
        )

    backend = _SequenceBackend(
        [
            yaml_block(
                "body_markdown",
                original,
                "claims_made: []\nadded_claims: []\nwarnings: []\n",
            ),
            yaml_block(
                "resulting_text",
                altered,
                "changes_made: []\nwarnings: []\n",
            ),
            yaml_block(
                "rationale",
                "No semantic change.",
                "verdict: PASS\ndifferences: []\n",
            ),
            yaml_block(
                "rationale",
                "Internally consistent.",
                "verdict: PASS\nfindings: []\n",
            ),
        ]
    )
    registry = RoleBindingRegistry()
    for role in ("writer", "humanizer", "final_reviewer"):
        registry.register_binding(
            RoleBinding(domain="writing", role=role, provider="fake_provider")
        )
    set_howlplane_bridge(
        HowlPlaneWritingBridge(
            dispatcher=RoleDispatcher(binding_registry=registry), registry=registry
        )
    )
    outline = Outline(
        title="Proof",
        topic="proof",
        nodes=[
            OutlineNode(id="h1", kind=NodeKind.HEADING, text="Derivation"),
            OutlineNode(id="p1", kind=NodeKind.PRESERVE, text=preserved),
        ],
    )
    spec = AssignmentSpec(
        title="Proof",
        topic="proof",
        target_words=20,
        word_tolerance_percent=50,
        source_requirements=dict(minimum_sources=0),
    )

    result = run_academic_pipeline(
        spec,
        outline=outline,
        custom_backend=backend,
        max_length_retries=0,
    )

    assert preserved in result.final_document.text
    assert altered not in result.final_document.text
    assert result.provenance.coverage["preserved_retained"] == 1
    assert result.provenance.review["preserve_guard"][0]["stage"] == "humanizer"
    assert any("prior artifact was retained" in item for item in result.provenance.warnings)


def test_reviewer_independence_tracking_across_stages():
    body = (
        "# Staged Intrusion\n\n"
        "## Stage 1: Initial access\n\nPhishing yields valid user credentials.\n\n"
        "## Stage 2: Lateral movement\n\nEnumeration identifies reachable servers.\n"
    )
    backend = _configure_backend(body)
    spec = AssignmentSpec(
        title="Intrusion Lifecycle",
        topic="attack phases",
        target_words=50,
    )

    result = run_academic_pipeline(
        spec, custom_backend=backend, deterministic_only=False
    )

    # Reviewer independence tracked per stage
    indep = result.provenance.reviewer_independence_by_stage
    assert indep == {
        "meaning_review": "SAME_PROVIDER",
        "consistency_review": "SAME_PROVIDER",
    }
    assert result.provenance.reviewer_independence() == "SAME_PROVIDER"
    assert result.report.reviewer_independence == "SAME_PROVIDER"
