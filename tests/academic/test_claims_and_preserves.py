"""Tests for academic pipeline claims provenance, outline preserve gating, and reviewer independence."""

from __future__ import annotations

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


def _configure_backend(body_markdown: str, claims_made: list[dict] | None = None) -> FakeAgentBackend:
    registry = RoleBindingRegistry()
    for role in ("writer", "humanizer", "final_reviewer"):
        registry.register_binding(
            RoleBinding(domain="writing", role=role, provider="fake_provider")
        )

    claims_yaml = "claims_made: []\n"
    if claims_made:
        claims_lines = ["claims_made:"]
        for c in claims_made:
            claims_lines.append(f"  - claim: {c.get('claim', '')}")
            claims_lines.append(f"    source_id: {c.get('source_id', '')}")
            claims_lines.append(f"    evidence_snippet: {c.get('evidence_snippet', '')}")
        claims_yaml = "\n".join(claims_lines) + "\n"

    indented = "\n".join(f"  {line}" for line in body_markdown.splitlines())
    backend = FakeAgentBackend(
        agent_id="fake_provider",
        default_stdout=(
            "```yaml\n"
            f"body_markdown: |\n{indented}\n"
            f"resulting_text: |\n{indented}\n"
            f"{claims_yaml}"
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

    # Arm 2: Writer alters the preserved sentence -> authorship check fails -> gates to NEEDS_REVIEW
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
    res_fail = run_academic_pipeline(
        spec_fail,
        outline=outline,
        custom_backend=backend_fail,
        deterministic_only=False,
    )
    assert res_fail.authorship_coverage is not None
    assert res_fail.authorship_coverage.status == "FAIL"
    assert res_fail.report.status == "NEEDS_REVIEW"
    assert res_fail.authorship_coverage.preserved_retained == 0
    assert len(res_fail.authorship_coverage.altered_preserved) == 1


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
    valid_statuses = (
        "SAME_PROVIDER",
        "INDEPENDENT_PROVIDER",
        "SAME_AGENT",
        "INDEPENDENT_AGENT",
        "NO_REVIEWER",
        "UNKNOWN",
    )
    assert indep["meaning_review"] in valid_statuses
    assert "consistency_review" in indep
    assert indep["consistency_review"] in valid_statuses
