"""Tests for source and citation integrity verification, SSRF protection, and DOI validation."""

import pytest
import httpx

from howlwriter.domain.source import Source
from howlwriter.research.integrity import (
    ACCESS_BROKEN,
    ACCESS_REDIRECTED,
    ACCESS_VALID,
    METADATA_MATCH,
    METADATA_MISMATCH,
    SEV_BLOCKING,
    SEV_PASS,
    SEV_WARNING,
    SSRFSecurityError,
    SourceIntegrityVerifier,
    validate_url_security,
)


def test_validate_url_security_blocks_ssrf():
    # Loopback and local names
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://localhost:8000/api")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://127.0.0.1/secrets")

    # Cloud metadata
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://169.254.169.254/latest/meta-data/")

    # Private IP ranges
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://10.0.0.1/admin")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://192.168.1.1/router")

    # Non-HTTP/HTTPS schemes
    with pytest.raises(SSRFSecurityError):
        validate_url_security("file:///etc/passwd")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("ftp://ftp.example.com/file")

    # Legitimate external URL should not raise
    validate_url_security("https://example.com/paper.pdf")
    validate_url_security("https://doi.org/10.1000/182")


def test_source_missing_identifier():
    source = Source(
        id="S001",
        title="Unidentified Document",
        authors=["Unknown"],
    )
    verifier = SourceIntegrityVerifier()
    finding = verifier.verify_source(source)

    assert finding.severity == SEV_WARNING
    assert finding.url_or_doi == "<missing>"
    assert "lacks both URL and DOI" in finding.diagnostics[0]


def test_source_reachability_mock():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "valid-paper" in url_str or "canonical-paper" in url_str:
            return httpx.Response(200, text="<html><body>Academic Paper Content</body></html>")
        elif "missing-paper" in url_str:
            return httpx.Response(404, text="Not Found")
        elif "redirect-paper" in url_str:
            return httpx.Response(301, headers={"Location": "https://example.com/canonical-paper"})
        return httpx.Response(500, text="Server Error")

    transport = httpx.MockTransport(mock_handler)
    verifier = SourceIntegrityVerifier(mock_transport=transport)

    # 1. Valid source
    s_valid = Source(id="S001", title="Valid Paper", authors=["A. Smith"], url="https://example.com/valid-paper")
    f_valid = verifier.verify_source(s_valid)
    assert f_valid.access_status == ACCESS_VALID
    assert f_valid.severity == SEV_PASS
    assert f_valid.http_status == 200

    # 2. Missing (404) source
    s_404 = Source(id="S002", title="Missing Paper", authors=["B. Jones"], url="https://example.com/missing-paper")
    f_404 = verifier.verify_source(s_404)
    assert f_404.access_status == ACCESS_BROKEN
    assert f_404.severity == SEV_BLOCKING
    assert f_404.http_status == 404

    # 3. Redirected source
    s_redir = Source(id="S003", title="Old Link", authors=["C. Brown"], url="https://example.com/redirect-paper")
    f_redir = verifier.verify_source(s_redir)
    assert f_redir.access_status in (ACCESS_REDIRECTED, ACCESS_VALID)
    assert f_redir.resolved_url == "https://example.com/canonical-paper"


def test_doi_crossref_verification():
    def crossref_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "10.1000/valid-doi" in url_str:
            payload = {
                "status": "ok",
                "message": {
                    "title": ["A Unified Architecture for Distributed Verification"],
                    "author": [{"family": "Shannon", "given": "Claude"}],
                    "issued": {"date-parts": [[1948]]},
                },
            }
            return httpx.Response(200, json=payload)
        elif "10.1000/mismatched-doi" in url_str:
            payload = {
                "status": "ok",
                "message": {
                    "title": ["Deep Reinforcement Learning for Autonomous Drone Racing"],
                    "author": [{"family": "Kaufmann", "given": "Elia"}],
                },
            }
            return httpx.Response(200, json=payload)
        return httpx.Response(404, text="DOI Not Found")

    transport = httpx.MockTransport(crossref_handler)
    verifier = SourceIntegrityVerifier(mock_transport=transport)

    # 1. Matching DOI
    s_match = Source(
        id="S010",
        title="A Unified Architecture for Distributed Verification",
        authors=["Shannon, C."],
        doi="10.1000/valid-doi",
    )
    f_match = verifier.verify_source(s_match)
    assert f_match.access_status == ACCESS_VALID
    assert f_match.metadata_status == METADATA_MATCH
    assert f_match.severity == SEV_PASS

    # 2. Mismatched Title DOI (Severe mismatch flags SEV_BLOCKING)
    s_mismatch = Source(
        id="S011",
        title="Modern Agricultural Economics in Sub-Saharan Africa",
        authors=["Different, A."],
        doi="10.1000/mismatched-doi",
    )
    f_mismatch = verifier.verify_source(s_mismatch)
    assert f_mismatch.access_status == ACCESS_VALID
    assert f_mismatch.metadata_status == METADATA_MISMATCH
    assert f_mismatch.severity == SEV_BLOCKING

    # 3. Fabricated / Not Found DOI
    s_fake = Source(
        id="S012",
        title="Completely Hallucinated Paper",
        authors=["Ghost, G."],
        doi="10.9999/fabricated-doi",
    )
    f_fake = verifier.verify_source(s_fake)
    assert f_fake.access_status == ACCESS_BROKEN
    assert f_fake.severity == SEV_BLOCKING


def test_source_integrity_orthogonality():
    """Verify that source integrity does not mutate domain relevance or claim support."""
    source = Source(
        id="S020",
        title="Orthogonal Source",
        authors=["Tester, T."],
        url="https://example.com/valid-paper",
    )
    source.relevance = "DIRECT"

    verifier = SourceIntegrityVerifier(
        mock_transport=httpx.MockTransport(lambda req: httpx.Response(200, text="OK"))
    )
    report = verifier.verify_all([source])

    # Relevance and domain fields remain untouched
    assert source.relevance == "DIRECT"
    assert report.status == "PASS"
    assert report.findings[0].evidence_support == "DIRECT"
