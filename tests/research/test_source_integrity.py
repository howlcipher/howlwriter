"""Tests for source and citation integrity verification, SSRF protection,
per-hop redirect safety, DNS rebinding defenses, bounded retrieval, and DOI validation.
"""

from unittest.mock import MagicMock
import httpx
import pytest

from howlwriter.domain.source import Source
from howlwriter.research.integrity import (
    ACCESS_BROKEN,
    ACCESS_REDIRECTED,
    ACCESS_UNKNOWN,
    ACCESS_VALID,
    DEFAULT_MAX_REDIRECTS,
    MAX_INSPECT_BYTES,
    METADATA_MATCH,
    METADATA_MISMATCH,
    METADATA_UNKNOWN,
    SEV_BLOCKING,
    SEV_PASS,
    SEV_WARNING,
    SSRFSafeSyncBackend,
    SSRFSecurityError,
    SourceIntegrityVerifier,
    _compute_string_similarity,
    is_prohibited_ip,
    normalize_doi,
    validate_url_security,
)


def test_validate_url_security_blocks_ssrf():
    # Loopback and local names
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://localhost:8000/api")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://service.localhost/app")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://127.0.0.1/secrets")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://127.0.0.2:8080/internal")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://[::1]/admin")

    # Cloud metadata endpoints & aliases
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://instance-data/latest")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://metadata.google.internal/computeMetadata/v1/")

    # Private IP ranges (RFC 1918)
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://10.0.0.1/admin")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://172.16.0.1/dashboard")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://192.168.1.1/router")

    # IPv4-mapped IPv6 representations
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://[::ffff:127.0.0.1]/status")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://[::ffff:169.254.169.254]/meta")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://[::ffff:10.0.0.1]/internal")

    # Unspecified IP addresses
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://0.0.0.0/")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("http://[::]/")

    # Non-HTTP/HTTPS schemes
    with pytest.raises(SSRFSecurityError):
        validate_url_security("file:///etc/passwd")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("ftp://ftp.example.com/file")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("gopher://example.com/item")

    with pytest.raises(SSRFSecurityError):
        validate_url_security("data:text/html,<h1>Hello</h1>")

    # Missing hostname
    with pytest.raises(SSRFSecurityError):
        validate_url_security("http:///path/only")


def test_is_prohibited_ip_helper():
    assert is_prohibited_ip("127.0.0.1") is True
    assert is_prohibited_ip("::1") is True
    assert is_prohibited_ip("10.10.10.10") is True
    assert is_prohibited_ip("172.20.0.5") is True
    assert is_prohibited_ip("192.168.0.1") is True
    assert is_prohibited_ip("169.254.169.254") is True
    assert is_prohibited_ip("::ffff:127.0.0.1") is True
    assert is_prohibited_ip("::ffff:10.0.0.1") is True
    assert is_prohibited_ip("0.0.0.0") is True
    assert is_prohibited_ip("::") is True
    assert is_prohibited_ip("240.0.0.1") is True  # Reserved
    assert is_prohibited_ip("224.0.0.1") is True  # Multicast

    # Valid public IP addresses
    assert is_prohibited_ip("8.8.8.8") is False
    assert is_prohibited_ip("1.1.1.1") is False
    assert is_prohibited_ip("93.184.216.34") is False
    assert is_prohibited_ip("2606:4700:4700::1111") is False


def test_dns_resolution_checks_all_ips(monkeypatch):
    """If a hostname resolves to multiple addresses and ANY address is private, reject."""
    import socket

    def mock_getaddrinfo(host, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),  # Private!
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    with pytest.raises(SSRFSecurityError) as exc_info:
        validate_url_security("https://dual-homed.example.com/doc")

    assert "prohibited or private range" in str(exc_info.value)


def test_dns_resolution_failure(monkeypatch):
    import socket

    def mock_getaddrinfo(host, port):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    with pytest.raises(ConnectionError) as exc_info:
        validate_url_security("https://nonexistent.invalid/doc")

    assert "DNS resolution failed" in str(exc_info.value)


def test_post_connect_peer_ip_verification():
    """Verify that SSRFSafeSyncBackend checks sock.getpeername() after TCP connection."""
    if SSRFSafeSyncBackend is None:
        pytest.skip("SSRFSafeSyncBackend not available")

    backend = SSRFSafeSyncBackend()
    mock_sock = MagicMock()
    mock_sock.getpeername.return_value = ("127.0.0.1", 8080)
    mock_stream = MagicMock()
    mock_stream._sock = mock_sock

    with pytest.MonkeyPatch.context() as mp:
        import httpcore
        mp.setattr(httpcore.SyncBackend, "connect_tcp", lambda self, *a, **k: mock_stream)
        with pytest.raises(SSRFSecurityError) as exc_info:
            backend.connect_tcp("internal.company.com", 8080)

        assert "Post-connect peer IP 127.0.0.1" in str(exc_info.value)
        assert mock_stream.close.called


def test_redirect_ssrf_blocking_per_hop(monkeypatch):
    """Test that redirects targeting internal, metadata, or loopback IPs are blocked before request."""
    import socket

    def mock_dns(host, port):
        if host in ("127.0.0.1", "localhost"):
            return [(2, 1, 6, "", ("127.0.0.1", 0))]
        if host == "169.254.169.254":
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        if host == "10.0.0.1":
            return [(2, 1, 6, "", ("10.0.0.1", 0))]
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_dns)

    requested_urls: list[str] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        requested_urls.append(url_str)

        if url_str == "https://public.example.com/redir-loopback":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/admin"})
        if url_str == "https://public.example.com/redir-metadata":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
        if url_str == "https://public.example.com/redir-private":
            return httpx.Response(302, headers={"Location": "http://10.0.0.1/dashboard"})
        if url_str == "https://public.example.com/redir-file":
            return httpx.Response(302, headers={"Location": "file:///etc/passwd"})
        if url_str == "https://public.example.com/redir-public":
            return httpx.Response(302, headers={"Location": "https://other.example.org/destination"})
        if url_str == "https://other.example.org/destination":
            return httpx.Response(
                200, headers={"Content-Type": "text/html"}, text="<title>Destination</title>"
            )

        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(mock_handler)
    verifier = SourceIntegrityVerifier(mock_transport=transport)

    # 1. Redirect to 127.0.0.1 must be blocked and request NEVER sent to 127.0.0.1
    s_loop = Source(
        id="S1",
        title="Loopback Target",
        authors=["A"],
        url="https://public.example.com/redir-loopback",
    )
    f_loop = verifier.verify_source(s_loop)
    assert f_loop.access_status == ACCESS_BROKEN
    assert f_loop.severity == SEV_BLOCKING
    assert "SSRF Security Violation on redirect" in f_loop.diagnostics[0]
    assert "http://127.0.0.1:8000/admin" not in requested_urls

    # 2. Redirect to cloud metadata must be blocked
    s_meta = Source(
        id="S2",
        title="Metadata Target",
        authors=["A"],
        url="https://public.example.com/redir-metadata",
    )
    f_meta = verifier.verify_source(s_meta)
    assert f_meta.access_status == ACCESS_BROKEN
    assert f_meta.severity == SEV_BLOCKING
    assert "http://169.254.169.254" not in requested_urls

    # 3. Redirect to RFC 1918 private IP must be blocked
    s_priv = Source(
        id="S3",
        title="Private Target",
        authors=["A"],
        url="https://public.example.com/redir-private",
    )
    f_priv = verifier.verify_source(s_priv)
    assert f_priv.access_status == ACCESS_BROKEN
    assert f_priv.severity == SEV_BLOCKING
    assert "http://10.0.0.1/dashboard" not in requested_urls

    # 4. Redirect to file scheme must be blocked
    s_file = Source(id="S4", title="File Scheme", authors=["A"], url="https://public.example.com/redir-file")
    f_file = verifier.verify_source(s_file)
    assert f_file.access_status == ACCESS_BROKEN
    assert f_file.severity == SEV_BLOCKING

    # 5. Public-to-public redirect is allowed, marked cross-domain
    s_pub = Source(
        id="S5",
        title="Destination",
        authors=["A"],
        url="https://public.example.com/redir-public",
    )
    f_pub = verifier.verify_source(s_pub)
    assert f_pub.access_status == ACCESS_REDIRECTED
    assert f_pub.resolved_url == "https://other.example.org/destination"
    assert any("domain changed: True" in d for d in f_pub.diagnostics)


def test_redirect_loop_and_limit_enforcement():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == "https://example.com/loop-a":
            return httpx.Response(302, headers={"Location": "https://example.com/loop-b"})
        if url_str == "https://example.com/loop-b":
            return httpx.Response(302, headers={"Location": "https://example.com/loop-a"})
        if "chain-" in url_str:
            num = int(url_str.split("chain-")[1])
            return httpx.Response(302, headers={"Location": f"https://example.com/chain-{num+1}"})
        return httpx.Response(200, text="OK")

    transport = httpx.MockTransport(mock_handler)
    verifier = SourceIntegrityVerifier(mock_transport=transport, max_redirects=DEFAULT_MAX_REDIRECTS)

    # 1. Loop detection
    s_loop = Source(id="S_LOOP", title="Loop", authors=["A"], url="https://example.com/loop-a")
    f_loop = verifier.verify_source(s_loop)
    assert f_loop.access_status == ACCESS_BROKEN
    assert f_loop.severity == SEV_BLOCKING
    assert any("Redirect loop detected" in d for d in f_loop.diagnostics)

    # 2. Max redirect count exceeded
    s_chain = Source(id="S_CHAIN", title="Long Chain", authors=["A"], url="https://example.com/chain-1")
    f_chain = verifier.verify_source(s_chain)
    assert f_chain.access_status == ACCESS_BROKEN
    assert f_chain.severity == SEV_WARNING
    assert any("Exceeded maximum redirect limit" in d for d in f_chain.diagnostics)


def test_bounded_retrieval_and_binary_content_types():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "oversized.html" in url_str:
            # Huge HTML response (> 2 MB)
            large_body = "<title>Oversized Document Title</title>" + ("A" * (2 * 1024 * 1024))
            return httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, text=large_body)
        elif "document.pdf" in url_str:
            return httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=b"%PDF-1.4 dummy pdf bytes",
            )
        elif "archive.zip" in url_str:
            return httpx.Response(
                200,
                headers={"Content-Type": "application/zip"},
                content=b"PK dummy zip bytes",
            )
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(mock_handler)
    verifier = SourceIntegrityVerifier(mock_transport=transport, max_inspect_bytes=MAX_INSPECT_BYTES)

    # 1. Oversized HTML page: stream terminates at 1 MiB, title parsed without downloading full 2 MiB
    s_html = Source(
        id="S_HTML",
        title="Oversized Document Title",
        authors=["A"],
        url="https://example.com/oversized.html",
    )
    f_html = verifier.verify_source(s_html)
    assert f_html.access_status == ACCESS_VALID
    assert f_html.metadata_status == METADATA_MATCH
    assert f_html.retrieved_title == "Oversized Document Title"

    # 2. PDF response: body is not read, reachability confirmed, metadata UNKNOWN
    s_pdf = Source(
        id="S_PDF",
        title="Sample Whitepaper",
        authors=["B"],
        url="https://example.com/document.pdf",
    )
    f_pdf = verifier.verify_source(s_pdf)
    assert f_pdf.access_status == ACCESS_VALID
    assert f_pdf.metadata_status == METADATA_UNKNOWN
    assert f_pdf.severity == SEV_PASS
    assert any("non-HTML content-type 'application/pdf'" in d for d in f_pdf.diagnostics)

    # 3. Zip archive response: body is not read
    s_zip = Source(id="S_ZIP", title="Dataset Archive", authors=["C"], url="https://example.com/archive.zip")
    f_zip = verifier.verify_source(s_zip)
    assert f_zip.access_status == ACCESS_VALID
    assert f_zip.metadata_status == METADATA_UNKNOWN


def test_title_similarity_calibration():
    # 1. Real fixture from NIST CSF
    sim_csf = _compute_string_similarity(
        "Cybersecurity Framework 2.0",
        "The NIST Cybersecurity Framework (CSF) 2.0",
    )
    assert sim_csf >= 0.70

    # 2. Subtitle variation
    sim_sub = _compute_string_similarity(
        "A Unified Architecture for Distributed Verification",
        "A Unified Architecture for Distributed Verification: Principles and Protocols",
    )
    assert sim_sub >= 0.70

    # 3. Publisher / journal suffix noise
    sim_suffix = _compute_string_similarity(
        "Quantum Cryptography Protocols",
        "Quantum Cryptography Protocols | Nature",
    )
    assert sim_suffix >= 0.90

    # 4. Punctuation and quotes normalization
    sim_punct = _compute_string_similarity(
        'Zero-Trust Architecture: "NIST Guidelines"',
        "Zero Trust Architecture: NIST Guidelines",
    )
    assert sim_punct >= 0.90

    # 5. Completely unrelated titles
    sim_mismatch = _compute_string_similarity(
        "A Unified Architecture for Distributed Verification",
        "Modern Agricultural Economics in Sub-Saharan Africa",
    )
    assert sim_mismatch < 0.35


def test_doi_normalization_and_registrar_discrimination():
    # Test normalization helper
    assert normalize_doi("10.1000/182") == "10.1000/182"
    assert normalize_doi("https://doi.org/10.1000/182") == "10.1000/182"
    assert normalize_doi("http://doi.org/10.1000/182") == "10.1000/182"
    assert normalize_doi("https://dx.doi.org/10.1000/182") == "10.1000/182"
    assert normalize_doi("doi:10.1000/182") == "10.1000/182"
    assert normalize_doi("DOI: 10.1000/182") == "10.1000/182"
    assert normalize_doi("https://doi.org/10.1000/182.") == "10.1000/182"

    def crossref_mock(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "valid-work" in url_str:
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "message": {"title": ["Verified Crossref Publication Title"]},
                },
            )
        elif "missing-title" in url_str:
            return httpx.Response(200, json={"status": "ok", "message": {"title": []}})
        elif "rate-limited" in url_str:
            return httpx.Response(429, text="Too Many Requests")
        elif "server-error" in url_str:
            return httpx.Response(503, text="Service Unavailable")
        elif "fabricated" in url_str:
            return httpx.Response(404, text="Not Found")
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(crossref_mock)
    verifier = SourceIntegrityVerifier(mock_transport=transport)

    # 1. Matching title -> PASS
    s_ok = Source(
        id="D1",
        title="Verified Crossref Publication Title",
        authors=["X"],
        doi="https://doi.org/10.1000/valid-work",
    )
    f_ok = verifier.verify_source(s_ok)
    assert f_ok.access_status == ACCESS_VALID
    assert f_ok.metadata_status == METADATA_MATCH
    assert f_ok.severity == SEV_PASS

    # 2. Fabricated 404 -> BLOCKING
    s_fab = Source(id="D2", title="Fake", authors=["X"], doi="10.1000/fabricated")
    f_fab = verifier.verify_source(s_fab)
    assert f_fab.access_status == ACCESS_BROKEN
    assert f_fab.metadata_status == METADATA_MISMATCH
    assert f_fab.severity == SEV_BLOCKING

    # 3. Rate limited 429 -> WARNING (not fabrication)
    s_rate = Source(id="D3", title="Rate Limited", authors=["X"], doi="10.1000/rate-limited")
    f_rate = verifier.verify_source(s_rate)
    assert f_rate.access_status == ACCESS_UNKNOWN
    assert f_rate.severity == SEV_WARNING
    assert "rate-limited" in f_rate.diagnostics[0]

    # 4. Registrar 503 error -> WARNING (temporary outage)
    s_503 = Source(id="D4", title="503 Error", authors=["X"], doi="10.1000/server-error")
    f_503 = verifier.verify_source(s_503)
    assert f_503.access_status == ACCESS_UNKNOWN
    assert f_503.severity == SEV_WARNING

    # 5. Registrar record without title -> WARNING
    s_notitle = Source(id="D5", title="Has No Title", authors=["X"], doi="10.1000/missing-title")
    f_notitle = verifier.verify_source(s_notitle)
    assert f_notitle.access_status == ACCESS_VALID
    assert f_notitle.metadata_status == METADATA_UNKNOWN
    assert f_notitle.severity == SEV_WARNING


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
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text=(
                    "<html><head><title>Valid Paper</title></head>"
                    "<body>Academic Paper Content</body></html>"
                ),
            )
        elif "missing-paper" in url_str:
            return httpx.Response(404, text="Not Found")
        elif "redirect-paper" in url_str:
            return httpx.Response(301, headers={"Location": "https://example.com/canonical-paper"})
        return httpx.Response(500, text="Server Error")

    transport = httpx.MockTransport(mock_handler)
    verifier = SourceIntegrityVerifier(mock_transport=transport)

    # 1. Valid source
    s_valid = Source(
        id="S001",
        title="Valid Paper",
        authors=["A. Smith"],
        url="https://example.com/valid-paper",
    )
    f_valid = verifier.verify_source(s_valid)
    assert f_valid.access_status == ACCESS_VALID
    assert f_valid.severity == SEV_PASS
    assert f_valid.http_status == 200

    # 2. Missing (404) source
    s_404 = Source(
        id="S002",
        title="Missing Paper",
        authors=["B. Jones"],
        url="https://example.com/missing-paper",
    )
    f_404 = verifier.verify_source(s_404)
    assert f_404.access_status == ACCESS_BROKEN
    assert f_404.severity == SEV_BLOCKING
    assert f_404.http_status == 404

    # 3. Redirected source
    s_redir = Source(
        id="S003",
        title="Old Link",
        authors=["C. Brown"],
        url="https://example.com/redirect-paper",
    )
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
