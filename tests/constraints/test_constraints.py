"""Focused regression tests for the constraint-aware writing pass."""

from howlwriter.academic.spec import AssignmentSpec, extract_constraints
from howlwriter.constraints.enforcer import ConstraintEnforcer
from howlwriter.constraints.length import estimate_pages, words_for_pages
from howlwriter.constraints.specs import ConstraintSet
from howlwriter.constraints.validators import (
    RedundancyDetector,
    SequenceValidator,
    UnsupportedSpecificityValidator,
)
from howlwriter.domain.document import Document
from howlwriter.domain.modes import WritingMode
from src.control_plane.agent_execution import FakeAgentBackend


def _doc(text: str, mode: WritingMode = WritingMode.ACADEMIC) -> Document:
    return Document.parse(text, title="Test", mode=mode)


def test_extract_constraints_from_assignment_spec():
    spec = AssignmentSpec(
        title="Constraint Demo",
        topic="Demo topic.",
        target_words=1500,
        max_words=2200,
        max_pages=10,
        outline=["Intro", "Body", "Conclusion"],
        requirements=["include tools", "include telemetry"],
        required_evidence=["MITRE mapping"],
        prohibited_content=["invented Event IDs", "fake URLs"],
        source_fidelity="strict",
        compression_notes="do not overdo this",
    )
    cs = extract_constraints(spec)
    assert cs.target_words == 1500
    assert cs.max_words == 2200
    assert cs.max_pages == 10
    assert cs.effective_max_words() == 2200
    assert cs.required_sections == ["Intro", "Body", "Conclusion"]
    assert "include tools" in cs.required_items
    assert "MITRE mapping" in cs.required_evidence
    assert "invented Event IDs" in cs.prohibited_content
    assert cs.source_fidelity == "strict"


def test_hard_max_is_respected():
    cs = ConstraintSet(max_words=2000)
    assert cs.effective_max_words() == 2000


def test_page_limit_converts_to_words():
    cs = ConstraintSet(max_pages=10)
    assert cs.effective_max_words() == 10 * 275


def test_soft_target_aims_below_hard_max():
    cs = ConstraintSet(max_pages=10)
    target = cs.effective_target_words()
    assert target is not None
    assert target < cs.effective_max_words()


def test_estimate_pages():
    assert estimate_pages(550, words_per_page=275) == 2.0
    assert estimate_pages(550, has_tables=True) > 2.0
    assert words_for_pages(4) == 4 * 275


def test_enforcer_compresses_to_hard_max_and_preserves_rubric():
    long_text = "\n\n".join([
        "# Long Draft",
        "This section contains many redundant words and repeated explanations.",
        "It also includes invented specifics such as CVE-2024-00001.",
    ] + ["Additional elaboration sentence number {}.".format(i) for i in range(50)])

    doc = _doc(long_text)
    cs = ConstraintSet(max_words=100, required_items=["include tools"], source_fidelity="strict")

    compressed = """# Concise Draft

This section covers the required points briefly.

## Tools
The chain uses common open-source tools.

rubric_items_preserved: 1
redundancy_removed: 3
unsupported_specificity_generalized: 1
sequence_repairs: 0
"""

    fake_backend = FakeAgentBackend(
        agent_id="fake_enforcer",
        default_stdout=f"""```yaml
body_markdown: |
  # Concise Draft

  This section covers the required points briefly.

  ## Tools
  The chain uses common open-source tools.
changes_made:
  - description: Removed redundant elaboration sentences
    reason: LENGTH_CONSTRAINT
  - description: Generalized CVE placeholder
    reason: UNSUPPORTED_SPECIFICITY
warnings: []
rubric_items_preserved: 1
redundancy_removed: 3
unsupported_specificity_generalized: 1
sequence_repairs: 0
rationale: Compressed to satisfy hard maximum while preserving required rubric item.
```""",
    )

    result = ConstraintEnforcer().enforce(
        doc,
        cs,
        custom_backend=fake_backend,
    )
    assert "## Tools" in result.document.text
    assert result.rubric_items_preserved == 1
    assert result.redundancy_removed == 3
    assert result.unsupported_specificity_generalized == 1
    assert result.max_words == 100


def test_enforcer_repairs_sequence_contradiction():
    text = """# Chain

Step 1. The attacker has only development credentials.

Step 2. The attacker executes commands inside a production Kubernetes pod.

Step 3. The attacker gains production credentials from a leaked secret store.
"""
    doc = _doc(text)
    cs = ConstraintSet(required_items=["logical stage order"])

    fake_backend = FakeAgentBackend(
        agent_id="fake_enforcer",
        default_stdout="""```yaml
body_markdown: |
  # Chain

  Step 1. The attacker has only development credentials.

  Step 2. The attacker gains production credentials from a leaked secret store.

  Step 3. The attacker executes commands inside a production Kubernetes pod.
changes_made:
  - description: Reordered stages so production credentials are acquired before use
    reason: SEQUENCE_DEPENDENCY
warnings: []
rubric_items_preserved: 1
redundancy_removed: 0
unsupported_specificity_generalized: 0
sequence_repairs: 1
rationale: Repaired dependency order.
```""",
    )

    result = ConstraintEnforcer().enforce(doc, cs, custom_backend=fake_backend)
    assert "Step 2. The attacker gains production credentials" in result.document.text
    assert "Step 3. The attacker executes commands" in result.document.text
    assert result.sequence_repairs == 1


def test_enforcer_fixes_semantic_mismatch():
    text = """# Supply-Chain Compromise

The incident began when a developer committed credentials to a public repository.
"""
    doc = _doc(text)
    cs = ConstraintSet(required_items=["accurate scenario label"])

    fake_backend = FakeAgentBackend(
        agent_id="fake_enforcer",
        default_stdout="""```yaml
body_markdown: |
  # Cloud Credential Exposure

  The incident began when a developer committed credentials to a public repository.
changes_made:
  - description: Relabeled heading to match the described mechanism
    reason: SEMANTIC_MISMATCH
warnings: []
rubric_items_preserved: 1
redundancy_removed: 0
unsupported_specificity_generalized: 0
sequence_repairs: 0
rationale: Heading now matches content.
```""",
    )

    result = ConstraintEnforcer().enforce(doc, cs, custom_backend=fake_backend)
    assert "# Cloud Credential Exposure" in result.document.text
    assert "Supply-Chain Compromise" not in result.document.text


def test_clean_human_text_not_over_compressed():
    text = "I've spent more time debugging than I'd like to admit. It's the kind of work that looks simple until it isn't."
    doc = _doc(text, mode=WritingMode.CASUAL)
    cs = ConstraintSet(target_words=50)

    fake_backend = FakeAgentBackend(
        agent_id="fake_enforcer",
        default_stdout=f"""```yaml
body_markdown: |
  {text}
changes_made: []
warnings: []
rubric_items_preserved: 0
redundancy_removed: 0
unsupported_specificity_generalized: 0
sequence_repairs: 0
rationale: Already concise and natural; no changes needed.
```""",
    )

    result = ConstraintEnforcer().enforce(doc, cs, custom_backend=fake_backend)
    assert result.document.text == text
    assert result.document.mode == WritingMode.CASUAL
    assert len(result.changes) == 0


def test_redundancy_detector_flags_table_then_prose():
    text = """| Tool | Telemetry |
|------|-----------|
| Mimikatz | Event ID 4624 |

Mimikatz Event ID 4624 telemetry. Mimikatz Event ID 4624.
"""
    doc = _doc(text)
    findings = RedundancyDetector().detect(doc)
    assert len(findings) >= 1
    assert findings[0].overlap_ratio >= 0.5


def test_specificity_validator_flags_candidate_exact_identifiers():
    text = """The attacker used CVE-2024-12345. GuardDuty finding StealthS3AnomalousAPI produced an alert.
Entropy >7.2 indicates packing. The beacon uses 35% jitter.
"""
    doc = _doc(text)
    findings = UnsupportedSpecificityValidator().validate(doc)
    labels = {f.pattern for f in findings}
    assert "CVE" in labels
    assert " GuardDuty / service finding" in labels or "finding name" in labels
    assert "entropy threshold" in labels
    assert "jitter percentage" in labels


def test_sequence_validator_flags_late_grant_of_early_resource():
    text = """Step 1. Actor has dev credentials only.

Step 2. Actor logs into the production account and creates a Kubernetes pod.

Step 3. Actor discovers production credentials in a secret store.
"""
    doc = _doc(text)
    findings = SequenceValidator().validate(doc)
    # The heuristic may flag the contradiction because Step 3 grants production
    # credentials after Step 2 already used production access.
    assert len(findings) >= 1
    assert any(
        word in findings[0].issue.lower() for word in ("production", "credentials")
    )
