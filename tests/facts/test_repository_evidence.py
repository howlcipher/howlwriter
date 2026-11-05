"""Regression tests for deterministic repository evidence validation.

Tests both:
1. Negative case: Known POST_30 evidence defect (HowlFrame claim citing HowlWriter with nonexistent path).
2. Positive control: Valid HowlFrame claim citing HowlFrame repository with real paths.
3. Missing evidence handling.
"""

from pathlib import Path
from howlwriter.facts.repository_evidence import validate_repository_claim_evidence

def test_rejects_post_30_evidence_mismatch():
    """Reproduces the defect in Season 3 baseline where POST_30 cited HowlWriter for HowlFrame."""
    defective_claim = {
        "claim_id": "POST_30-C1",
        "exact_evaluated_claim": "In our HowlFrame project, we took an alternative architectural path: a minimal, stack-based bytecode virtual machine implemented in Go.",
        "classification": "VERIFIED_IMPLEMENTATION",
        "source_document": "HowlFrame Virtual Machine Dispatch Implementation & Unit Test Suite",
        "source_url_or_revision": "https://github.com/howlcipher/howlwriter (git rev 7d27e33)",
        "exact_location": "src/howlwriter/integration/howlplane_bridge.py & howlframe/vm/vm.go",
        "verification_method": "Unit test execution of instruction budget exhaustion test cases confirming deterministic termination with ErrBudgetExceeded",
        "limitations": "Instruction budgets meter pure VM opcode dispatch cycles",
        "current_status": "VERIFIED"
    }

    result = validate_repository_claim_evidence(defective_claim)
    assert result.is_valid is False
    assert result.status == "UNRESOLVED"
    finding_codes = [f.code for f in result.findings]
    assert "PROJECT_MISMATCH" in finding_codes
    assert "PATH_NOT_FOUND" in finding_codes


def test_accepts_valid_howlframe_evidence_control():
    """Positive control: Correctly bound HowlFrame claim citing real repository and paths."""
    valid_claim = {
        "claim_id": "POST_30-C1",
        "exact_evaluated_claim": "In our HowlFrame project, we took an alternative architectural path: a minimal, stack-based bytecode virtual machine implemented in Go.",
        "classification": "VERIFIED_IMPLEMENTATION",
        "source_document": "HowlFrame Virtual Machine Engine and Execution Limits",
        "source_url_or_revision": "https://github.com/howlcipher/howlframe (commit 41ee7b80c6a5eb6b08941f9415a88156b9d0875f)",
        "exact_location": "internal/vm/vm.go & internal/vm/error.go",
        "verification_method": "Inspection of DefaultLimits.MaxInstructions (100,000 opcodes) and opcode dispatch loop",
        "limitations": "Instruction budgets govern VM bytecode execution cycles only; host I/O and external capability execution require host timeouts",
        "current_status": "VERIFIED"
    }

    result = validate_repository_claim_evidence(valid_claim)
    assert result.is_valid is True
    assert result.status == "VERIFIED"
    assert len(result.findings) == 0
    assert "internal/vm/vm.go" in result.resolved_paths


def test_rejects_missing_source_evidence():
    """Missing evidence must not silently retain VERIFIED status."""
    empty_claim = {
        "claim_id": "C-EMPTY",
        "exact_evaluated_claim": "Some claim without backing source documentation.",
        "source_document": "",
        "source_url_or_revision": "",
        "exact_location": "",
        "current_status": "VERIFIED"
    }

    result = validate_repository_claim_evidence(empty_claim)
    assert result.is_valid is False
    assert result.status == "UNRESOLVED"
    assert any(f.code == "MISSING_EVIDENCE_SOURCE" for f in result.findings)
