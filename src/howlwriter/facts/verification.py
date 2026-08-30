"""ClaimVerifier: attaching real Evidence to a Claim, unconfigured by
default. Deliberately Protocol-only for the MVP -- deciding a claim is
SUPPORTED requires either a model call, a real search backend, or a human
supplying sources, none of which HowlWriter performs on its own. See
domain/provenance.py for the real, working data structure this would
populate once a verifier is wired in.
"""

from __future__ import annotations

from typing import Protocol

from howlwriter.domain.claim import Claim
from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole


class ClaimVerifier(Protocol):
    role: WritingRole

    def verify(self, claim: Claim, provenance: ProvenanceGraph) -> Claim: ...


class NotConfiguredClaimVerifier(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.FACT_CHECKER)

    def verify(self, claim: Claim, provenance: ProvenanceGraph) -> Claim:
        return self.run(claim, provenance)
