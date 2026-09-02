"""Did the artifact actually honour the outline? Measured, never asked.

A writer model asked whether it followed the outline will say yes. It will say
yes when it dropped a required point, when it reordered the argument, and when
it paraphrased a sentence marked verbatim. So nothing here consults the model:
every finding is computed from the outline and the finished text.

The checks differ in how strict they can honestly be.

Verbatim retention is exact. Preserved text either appears character for
character or it does not, and near-misses are reported as violations with the
closest thing found, because "almost verbatim" is the failure mode that matters
-- a silently smoothed sentence looks fine and is not what the user wrote.

Point representation cannot be exact. A required point is a short phrase and
the artifact is prose; demanding a literal substring would fail on every
well-written expansion. So it is a lexical overlap test with a documented
threshold, and it is deliberately biased toward reporting a point as MISSING
when it is uncertain: a false alarm costs a glance, a false clear costs the
guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.domain.outline import NodeKind, Outline, OutlineNode

#: Share of a required point's meaningful words that must appear in the
#: artifact before it counts as represented. Heuristic. Set where a genuine
#: expansion of a point passes while an unrelated paragraph does not, and
#: deliberately biased toward reporting MISSING when uncertain.
REPRESENTATION_OVERLAP = 0.60

#: Overlap at or above which a preserved passage that failed the exact check is
#: reported as ALTERED rather than MISSING, so the user is shown the changed
#: form rather than told their sentence vanished.
ALTERATION_OVERLAP = 0.50

PRESENT = "PRESENT"
MISSING = "MISSING"
ALTERED = "ALTERED"

PASS = "PASS"
FAIL = "FAIL"

_WORD = re.compile(r"[a-z0-9']+")

#: Words too common to carry evidence of representation.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have how i if in into is it its
    of on or that the their there they this to was were what when which who will
    with you your we our us not no than then so such can could would should may
    might must do does did done being been over under about after before more
    most some any each other same only own too very just also""".split()
)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _content_words(text: str) -> set[str]:
    return {word for word in _words(text) if word not in _STOPWORDS and len(word) > 2}


def _overlap(needle: str, haystack_words: set[str]) -> float:
    wanted = _content_words(needle)
    if not wanted:
        return 0.0
    return len(wanted & haystack_words) / len(wanted)


def _normalize_for_exact(text: str) -> str:
    """Collapse whitespace only.

    Everything else -- punctuation, capitalisation, contractions -- is part of
    what "verbatim" means and must not be normalised away, or the check would
    approve the very edits it exists to catch.
    """
    return " ".join(text.split())


@dataclass
class PointFinding:
    node_id: str
    kind: str
    text: str
    status: str
    overlap: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "text": self.text,
            "status": self.status,
            "overlap": round(self.overlap, 3),
            "detail": self.detail,
        }


@dataclass
class OrderFinding:
    earlier_id: str
    later_id: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "earlier_id": self.earlier_id,
            "later_id": self.later_id,
            "detail": self.detail,
        }


@dataclass
class CoverageReport:
    """What the outline asked for, and what the artifact delivered."""

    status: str = PASS
    required_supplied: int = 0
    required_represented: int = 0
    preserved_supplied: int = 0
    preserved_retained: int = 0
    examples_supplied: int = 0
    examples_represented: int = 0
    order_enforced: bool = True
    order_satisfied: bool = True
    findings: list[PointFinding] = field(default_factory=list)
    order_findings: list[OrderFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[PointFinding]:
        return [f for f in self.findings if f.status == MISSING]

    @property
    def altered_preserved(self) -> list[PointFinding]:
        return [
            f for f in self.findings
            if f.status in (ALTERED, MISSING) and f.kind == NodeKind.PRESERVE.value
        ]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "required_supplied": self.required_supplied,
            "required_represented": self.required_represented,
            "preserved_supplied": self.preserved_supplied,
            "preserved_retained": self.preserved_retained,
            "examples_supplied": self.examples_supplied,
            "examples_represented": self.examples_represented,
            "order_enforced": self.order_enforced,
            "order_satisfied": self.order_satisfied,
            "findings": [f.to_dict() for f in self.findings],
            "order_findings": [f.to_dict() for f in self.order_findings],
            "notes": list(self.notes),
        }


def _best_window_overlap(text: str, artifact: str) -> tuple[float, str]:
    """Closest sentence-sized match for a passage that is not present exactly.

    Used only to describe a failure, never to excuse one.
    """
    wanted = _content_words(text)
    if not wanted:
        return 0.0, ""
    best_score = 0.0
    best_text = ""
    for candidate in re.split(r"(?<=[.!?])\s+|\n+", artifact):
        candidate = candidate.strip()
        if not candidate:
            continue
        score = len(wanted & _content_words(candidate)) / len(wanted)
        if score > best_score:
            best_score, best_text = score, candidate
    return best_score, best_text


def _check_preserved(node: OutlineNode, artifact: str, normalized: str) -> PointFinding:
    wanted = _normalize_for_exact(node.text)
    if not wanted:
        return PointFinding(node.id, node.kind.value, node.text, PRESENT, 1.0, "empty")
    if wanted in normalized:
        return PointFinding(node.id, node.kind.value, node.text, PRESENT, 1.0)

    score, closest = _best_window_overlap(node.text, artifact)
    if score >= ALTERATION_OVERLAP:
        return PointFinding(
            node.id,
            node.kind.value,
            node.text,
            ALTERED,
            score,
            f"closest text in the artifact: {closest[:200]!r}",
        )
    return PointFinding(
        node.id,
        node.kind.value,
        node.text,
        MISSING,
        score,
        "no comparable passage found in the artifact",
    )


def check_coverage(outline: Outline, artifact_text: str) -> CoverageReport:
    """Compare a finished artifact against the outline that specified it."""
    report = CoverageReport(order_enforced=outline.enforce_order)
    artifact_words = _content_words(artifact_text)
    normalized = _normalize_for_exact(artifact_text)
    lowered_normalized = normalized.lower()

    # --- verbatim, checked exactly ---
    for node in outline.preserved():
        finding = _check_preserved(node, artifact_text, normalized)
        # Case-only differences still count as a change to preserved text, but
        # are worth naming precisely rather than reporting as a disappearance.
        if finding.status != PRESENT:
            if _normalize_for_exact(node.text).lower() in lowered_normalized:
                finding.status = ALTERED
                finding.detail = "present but with different capitalisation"
                finding.overlap = 1.0
        report.findings.append(finding)
    report.preserved_supplied = len(outline.preserved())
    report.preserved_retained = sum(
        1 for f in report.findings
        if f.kind == NodeKind.PRESERVE.value and f.status == PRESENT
    )

    # --- required points, checked by overlap ---
    required = [n for n in outline.required_points() if n.kind is not NodeKind.PRESERVE]
    represented_ids: set[str] = {
        f.node_id for f in report.findings if f.status == PRESENT
    }
    for node in required:
        score = _overlap(node.text, artifact_words)
        status = PRESENT if score >= REPRESENTATION_OVERLAP else MISSING
        if status == PRESENT:
            represented_ids.add(node.id)
        report.findings.append(
            PointFinding(
                node.id,
                node.kind.value,
                node.text,
                status,
                score,
                "" if status == PRESENT else (
                    f"{score:.0%} of this point's content words appear in the "
                    f"artifact, below the {REPRESENTATION_OVERLAP:.0%} needed "
                    "to call it represented"
                ),
            )
        )
    report.required_supplied = len(required) + report.preserved_supplied
    report.required_represented = len(represented_ids)

    examples = outline.nodes_of(NodeKind.EXAMPLE, NodeKind.EXPERIENCE)
    report.examples_supplied = len(examples)
    report.examples_represented = sum(
        1 for node in examples if node.id in represented_ids
    )

    # --- ordering ---
    if outline.enforce_order:
        positions: list[tuple[str, int]] = []
        for node in outline.required_points():
            probe = _normalize_for_exact(node.text)
            index = normalized.find(probe) if probe else -1
            if index < 0:
                score, closest = _best_window_overlap(node.text, artifact_text)
                index = normalized.find(closest) if closest and score >= REPRESENTATION_OVERLAP else -1
            if index >= 0:
                positions.append((node.id, index))
        for (earlier_id, earlier_at), (later_id, later_at) in zip(positions, positions[1:]):
            if later_at < earlier_at:
                report.order_satisfied = False
                report.order_findings.append(
                    OrderFinding(
                        earlier_id,
                        later_id,
                        f"{later_id!r} appears before {earlier_id!r}, reversing "
                        "the order the outline specified",
                    )
                )
        if len(positions) < 2:
            report.notes.append(
                "too few required points could be located in the artifact to "
                "check ordering; reported as satisfied rather than as a pass "
                "the evidence does not support"
            )

    if report.missing or report.altered_preserved or not report.order_satisfied:
        report.status = FAIL

    return report
