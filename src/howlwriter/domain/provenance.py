"""The SOURCE <-> EVIDENCE <-> CLAIM provenance graph.

This is a real, working in-memory data structure -- not a stub. It exists to
answer, honestly and precisely, the questions a writing-report reader will
actually ask: which source supports this sentence, which claims depend on
this source, was this source actually accessed, and which claims remain
unsupported. See docs/provenance.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from howlwriter.domain.claim import Claim
from howlwriter.domain.source import Evidence, Source


@dataclass
class ProvenanceGraph:
    claims: dict[str, Claim] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)

    def add_claim(self, claim: Claim) -> None:
        self.claims[claim.id] = claim

    def add_source(self, source: Source) -> None:
        self.sources[source.id] = source

    def add_evidence(self, evidence: Evidence) -> None:
        if evidence.claim_id not in self.claims:
            raise ValueError(f"evidence {evidence.id!r} references unknown claim {evidence.claim_id!r}")
        if evidence.source_id not in self.sources:
            raise ValueError(f"evidence {evidence.id!r} references unknown source {evidence.source_id!r}")
        self.evidence.append(evidence)

    def evidence_for_claim(self, claim_id: str) -> list[Evidence]:
        return [e for e in self.evidence if e.claim_id == claim_id]

    def evidence_for_source(self, source_id: str) -> list[Evidence]:
        return [e for e in self.evidence if e.source_id == source_id]

    def sources_for_claim(self, claim_id: str) -> list[Source]:
        source_ids = {e.source_id for e in self.evidence_for_claim(claim_id)}
        return [self.sources[sid] for sid in source_ids]

    def claims_for_source(self, source_id: str) -> list[Claim]:
        claim_ids = {e.claim_id for e in self.evidence_for_source(source_id)}
        return [self.claims[cid] for cid in claim_ids]

    def unsupported_claims(self) -> list[Claim]:
        from howlwriter.domain.claim import VerificationStatus

        unsupported_statuses = {VerificationStatus.UNSUPPORTED, VerificationStatus.UNVERIFIABLE}
        return [c for c in self.claims.values() if c.verification_status in unsupported_statuses]

    def unaccessed_sources(self) -> list[Source]:
        """Sources cited but never actually retrieved -- an honesty check."""
        return [s for s in self.sources.values() if not s.was_accessed]
