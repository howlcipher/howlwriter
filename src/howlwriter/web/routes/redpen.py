"""Red Pen rhetorical critique endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from howlwriter.domain.claim import Claim
from howlwriter.domain.document import Document
from howlwriter.redpen.critic import RedPenEngine
from howlwriter.web.models import RedPenFindingDto, RedPenRequest, RedPenResponse

router = APIRouter(prefix="/api/redpen", tags=["redpen"])


@router.post("", response_model=RedPenResponse)
def run_redpen(req: RedPenRequest) -> RedPenResponse:
    document = Document.parse(req.text, title=req.title or "Untitled")

    domain_claims = []
    for c in req.claims:
        if isinstance(c, dict) and "claim_text" in c:
            domain_claims.append(
                Claim(
                    id=c.get("id", "C001"),
                    claim_text=c["claim_text"],
                    source_ids=c.get("source_ids", []),
                    evidence_ids=c.get("evidence_ids", []),
                    paragraph_index=c.get("paragraph_index"),
                )
            )

    findings = RedPenEngine().critique(document, claims=domain_claims or None)
    dtos = [
        RedPenFindingDto(
            finding=f.finding,
            reason=f.reason,
            recommendation=f.recommendation,
            category=f.category,
            severity=f.severity,
            location=f.location,
            paragraph_index=f.paragraph_index,
            snippet=f.snippet,
        )
        for f in findings
    ]

    return RedPenResponse(
        findings=dtos,
        total_count=len(dtos),
    )
