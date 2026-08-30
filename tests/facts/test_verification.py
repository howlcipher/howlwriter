import pytest

from howlwriter.domain.claim import Claim
from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.facts.verification import NotConfiguredClaimVerifier
from howlwriter.integration.model_role import ModelRoleNotConfiguredError, WritingRole


def test_not_configured_claim_verifier_raises():
    verifier = NotConfiguredClaimVerifier()
    with pytest.raises(ModelRoleNotConfiguredError) as excinfo:
        verifier.verify(Claim(id="c1", text="x"), ProvenanceGraph())
    assert excinfo.value.role is WritingRole.FACT_CHECKER
