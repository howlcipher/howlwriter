"""Sequence-dependency and heading/label consistency review.

Two failure modes from the dogfood incident that neither the deterministic
outline/claim checkers nor the meaning-preservation reviewer catch, because
both require judging what a passage *means*, not just pattern-matching text:

1. Sequence/dependency contradictions in staged or procedural content (e.g.
   an attack chain, workflow, or incident timeline where a later stage uses
   a capability an earlier stage was supposed to grant, out of order).
2. Heading/scenario-label vs. actual-content mismatches (e.g. a section
   titled "Software Supply-Chain Compromise" whose body actually describes
   leaked cloud credentials).

Also folds in citation-to-claim topical fit (whether an attached citation
actually supports the *specific* claim next to it, not merely the general
topic) rather than building a separate deterministic engine for that.

Modeled directly on review/meaning.py's RealModelMeaningReviewer /
SemanticMeaningResult and reuses WritingRole.FINAL_REVIEWER -- this is not a
new WritingRole, since that enum is part of the external HowlPlane contract.
When no model is configured, callers should catch ModelRoleNotConfiguredError
and leave the corresponding report fields None, exactly like semantic
meaning review degrades today -- never fabricate a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from howlwriter.academic.prompts import ACADEMIC_PRIORITY_ORDERING_GUIDANCE
from howlwriter.domain.document import Document
from howlwriter.domain.generation_provenance import ReviewerFallbackRecord
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.review.meaning import MAX_SINGLE_PASS_CHARS

_STAGE_MARKER_RE = re.compile(r"\b(?:stage|phase|step)\s+\d+\b", re.IGNORECASE)
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s+\S", re.MULTILINE)
_MIN_STAGE_HITS = 2

_ConsistencyKind = str  # "SEQUENCE_CONTRADICTION" | "LABEL_MISMATCH" | "CITATION_TOPICAL_MISFIT"
_ConsistencyVerdict = str  # "PASS" | "PASS_WITH_WARNINGS" | "FAIL"


@dataclass
class ConsistencyFinding(DataClassSerializationMixin):
    kind: _ConsistencyKind
    description: str
    severity: str = "warning"  # "blocker" | "warning" | "info"
    location_hint: str | None = None


@dataclass
class ConsistencyReviewResult(DataClassSerializationMixin):
    verdict: _ConsistencyVerdict = "PASS"
    findings: list[ConsistencyFinding] = field(default_factory=list)
    rationale: str = ""
    provider: str = ""
    model: str | None = None
    duration_seconds: float = 0.0
    sequence_check_performed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    fallback_record: ReviewerFallbackRecord | None = None


def has_staged_content(document: Document) -> bool:
    """Cheap deterministic gate: does this document contain enough staged/
    sequential markers (numbered steps, "Stage N"/"Phase N"/"Step N") to be
    worth asking the model to validate ordering/dependency consistency?

    This does not gate whether the model call itself fires -- that is gated
    only on the model role being configured, same as semantic meaning review.
    It gates whether the sequence-contradiction instructions are included in
    the prompt, keeping the prompt focused for non-procedural documents.
    """
    text = document.text
    stage_hits = len(_STAGE_MARKER_RE.findall(text))
    numbered_hits = len(_NUMBERED_LIST_RE.findall(text))
    return (stage_hits + numbered_hits) >= _MIN_STAGE_HITS


class RealModelConsistencyReviewer:
    """Real model-backed sequence/label/citation-fit reviewer wired via HowlPlane."""

    role: WritingRole = WritingRole.FINAL_REVIEWER

    def review(
        self,
        document: Document,
        sources: list[Source],
        staged_content_detected: bool,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
        fallback_backend: Any | None = None,
        writer_provider: str | None = None,
        run_id: str | None = None,
    ) -> ConsistencyReviewResult:
        if len(document.text) > MAX_SINGLE_PASS_CHARS:
            raise ValueError(
                f"Document size exceeds safe single-pass limit "
                f"({MAX_SINGLE_PASS_CHARS} chars) for consistency review."
            )

        bridge = get_howlplane_bridge()

        sequence_instructions = ""
        if staged_content_detected:
            sequence_instructions = """
2. SEQUENCE/DEPENDENCY CONTRADICTIONS: This document contains staged or
   procedural content (numbered steps, stages, or phases). For each stage,
   determine what access/capability the actor already possesses at that
   point, and what new capability the stage claims to provide. Flag any
   stage that uses a capability the actor has not yet acquired by that
   point in the sequence, or any later stage that redundantly re-establishes
   access an earlier stage already assumed. Kind: SEQUENCE_CONTRADICTION."""

        source_titles = "\n".join(f"- [{s.id}] {s.title}" for s in sources) or "- (no sources)"

        prompt = f"""You are an independent Consistency Reviewer executing the FINAL_REVIEWER role.
Your mission is to check the document below for internal consistency problems that a
purely textual diff cannot catch.

{ACADEMIC_PRIORITY_ORDERING_GUIDANCE}

CHECK FOR:
1. HEADING/LABEL MISMATCHES: Does every section heading, and the document's own thesis or
   scenario name, accurately describe what that section's content actually contains? Flag any
   heading, title, or scenario label that no longer matches the mechanism actually described
   (e.g. a section titled "Software Supply-Chain Compromise" whose body only describes leaked
   credentials, which is a credential-exposure scenario, not a supply-chain compromise). Kind:
   LABEL_MISMATCH.{sequence_instructions}
3. CITATION-TO-CLAIM TOPICAL FIT: For any in-text citation, does the specific source actually
   relate to the factual topic of the paragraph citing it? (e.g. citing an Active Directory
   security paper to support a claim about AWS IAM role abuse is a topical misfit, even if both
   involve "credentials"). Kind: CITATION_TOPICAL_MISFIT.

SOURCES RETRIEVED FOR THIS RUN:
{source_titles}

DOCUMENT TO REVIEW:
{document.text}

Respond in structured YAML format:
```yaml
verdict: PASS # PASS | PASS_WITH_WARNINGS | FAIL
findings:
  - kind: "LABEL_MISMATCH" # LABEL_MISMATCH | SEQUENCE_CONTRADICTION | CITATION_TOPICAL_MISFIT
    description: "<what is inconsistent and why>"
    severity: "warning" # blocker | warning | info
    location_hint: "<heading or short quoted phrase locating the issue>"
rationale: "<summary explanation of verdict>"
```"""

        result = bridge.execute_writing_role(
            role=self.role,
            prompt=prompt,
            system_instruction=ACADEMIC_PRIORITY_ORDERING_GUIDANCE,
            context={
                "document_title": document.title,
                "staged_content_detected": staged_content_detected,
                "run_id": run_id,
            },
            timeout_seconds=300,
            cwd=cwd,
            custom_backend=custom_backend,
        )

        fallback_rec: ReviewerFallbackRecord | None = None
        if not result.success and fallback_backend:
            primary_err = result.error_message or "Reviewer execution failed"
            primary_backend_name = str(custom_backend or self.role.value)
            fb_res = bridge.execute_writing_role(
                role=self.role,
                prompt=prompt,
                system_instruction=ACADEMIC_PRIORITY_ORDERING_GUIDANCE,
                context={
                    "document_title": document.title,
                    "staged_content_detected": staged_content_detected,
                    "run_id": run_id,
                },
                timeout_seconds=300,
                cwd=cwd,
                custom_backend=fallback_backend,
            )
            if fb_res.success:
                result = fb_res
                indep = (
                    "INDEPENDENT"
                    if (writer_provider and fb_res.provider != writer_provider)
                    else "SAME_PROVIDER"
                )
                fallback_rec = ReviewerFallbackRecord(
                    stage="consistency_review",
                    requested_reviewer=primary_backend_name,
                    failure_reason=primary_err,
                    fallback_reviewer=str(fallback_backend),
                    provider=fb_res.provider,
                    model=fb_res.model,
                    independence_status=indep,
                )

        if not result.success:
            err = result.error_message or "Reviewer execution failed"
            return ConsistencyReviewResult(
                verdict="FAIL",
                findings=[
                    ConsistencyFinding(
                        kind="reviewer_failure",
                        description=f"Consistency reviewer failed: {err}",
                        severity="blocker",
                    )
                ],
                rationale=f"Reviewer execution failed: {err}",
                provider=result.provider,
                model=result.model,
                duration_seconds=result.duration_seconds,
                sequence_check_performed=staged_content_detected,
                metadata=result.metadata,
                fallback_record=fallback_rec,
            )

        structured = result.structured_output or {}
        raw_verdict = str(structured.get("verdict") or "").upper().strip()
        if raw_verdict not in ("PASS", "PASS_WITH_WARNINGS", "FAIL"):
            raw_verdict = "PASS" if not structured.get("findings") else "PASS_WITH_WARNINGS"

        findings: list[ConsistencyFinding] = []
        raw_findings = structured.get("findings", [])
        if isinstance(raw_findings, list):
            for item in raw_findings:
                if not isinstance(item, dict):
                    continue
                findings.append(
                    ConsistencyFinding(
                        kind=str(item.get("kind") or "UNSPECIFIED"),
                        description=str(item.get("description") or ""),
                        severity=str(item.get("severity") or "warning"),
                        location_hint=(
                            str(item.get("location_hint"))
                            if item.get("location_hint") is not None
                            else None
                        ),
                    )
                )

        return ConsistencyReviewResult(
            verdict=raw_verdict,
            findings=findings,
            rationale=str(structured.get("rationale") or ""),
            provider=result.provider,
            model=result.model,
            duration_seconds=result.duration_seconds,
            sequence_check_performed=staged_content_detected,
            metadata=result.metadata,
            fallback_record=fallback_rec,
        )
