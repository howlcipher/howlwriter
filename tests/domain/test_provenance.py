import pytest

from howlwriter.domain.claim import Claim, VerificationStatus
from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.domain.source import Evidence, Source


def _graph_with_one_supported_claim():
    graph = ProvenanceGraph()
    claim = Claim(id="c1", text="The sky is blue.", verification_status=VerificationStatus.SUPPORTED)
    source = Source(
        id="s1", title="A Sky Study", authors=["A. Author"], retrieved_text="the sky appears blue"
    )
    graph.add_claim(claim)
    graph.add_source(source)
    evidence = Evidence(
        id="e1", source_id="s1", claim_id="c1", snippet="the sky appears blue", supports=True
    )
    graph.add_evidence(evidence)
    return graph


def test_sources_for_claim_and_claims_for_source_are_symmetric():
    graph = _graph_with_one_supported_claim()
    assert [s.id for s in graph.sources_for_claim("c1")] == ["s1"]
    assert [c.id for c in graph.claims_for_source("s1")] == ["c1"]


def test_evidence_for_claim_and_for_source():
    graph = _graph_with_one_supported_claim()
    assert [e.id for e in graph.evidence_for_claim("c1")] == ["e1"]
    assert [e.id for e in graph.evidence_for_source("s1")] == ["e1"]


def test_unsupported_claims_excludes_supported_ones():
    graph = _graph_with_one_supported_claim()
    unverifiable = VerificationStatus.UNVERIFIABLE
    graph.add_claim(Claim(id="c2", text="Unverified thing.", verification_status=unverifiable))
    unsupported_ids = {c.id for c in graph.unsupported_claims()}
    assert unsupported_ids == {"c2"}


def test_unaccessed_sources_flags_sources_never_retrieved():
    graph = ProvenanceGraph()
    graph.add_source(Source(id="s1", title="Retrieved", authors=[], retrieved_text="text"))
    graph.add_source(Source(id="s2", title="Never fetched", authors=[]))
    assert [s.id for s in graph.unaccessed_sources()] == ["s2"]


def test_add_evidence_rejects_dangling_claim_id():
    graph = ProvenanceGraph()
    graph.add_source(Source(id="s1", title="S", authors=[]))
    with pytest.raises(ValueError):
        graph.add_evidence(Evidence(id="e1", source_id="s1", claim_id="missing", snippet="x", supports=True))


def test_add_evidence_rejects_dangling_source_id():
    graph = ProvenanceGraph()
    graph.add_claim(Claim(id="c1", text="X"))
    with pytest.raises(ValueError):
        graph.add_evidence(Evidence(id="e1", source_id="missing", claim_id="c1", snippet="x", supports=True))
