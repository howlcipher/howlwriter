"""Focused dogfood exercise for Milestone 25.1: Source Integrity Hardening & Verification Accuracy.

Verifies:
- Valid official page
- Valid DOI with metadata match
- Cross-domain redirect
- Broken URL (HTTP 404)
- Direct private IP URL (SSRF blocked)
- Public URL redirecting to private IP (SSRF blocked per-hop before request)
- Oversized HTML body (> 2 MiB) with bounded streaming
- Binary PDF fixture with reachability confirmation and uninspected metadata
- DOI metadata mismatch
"""

from __future__ import annotations

import json
import sys
import httpx

from howlwriter.domain.source import Source, SourceAuthority, SourceType
from howlwriter.research.integrity import (
    ACCESS_BROKEN,
    ACCESS_REDIRECTED,
    ACCESS_VALID,
    MAX_INSPECT_BYTES,
    METADATA_MATCH,
    METADATA_MISMATCH,
    METADATA_UNKNOWN,
    SEV_BLOCKING,
    SEV_PASS,
    SEV_WARNING,
    SourceIntegrityVerifier,
)


def create_dogfood_mock_transport() -> httpx.MockTransport:
    """Hermetic mock transport providing deterministic responses for dogfood scenarios."""
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        # 1. Valid official page
        if "csrc.nist.gov" in url_str:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html><head><title>NIST SP 800-53 Rev. 5 Security Controls</title></head></html>",
            )

        # 2. Valid Crossref DOI
        if "api.crossref.org/works/10.1000/182" in url_str:
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "message": {"title": ["Digital Object Identifier Handbook"]},
                },
            )

        # 3. Cross-domain redirect
        if "example.com/external-redirect" in url_str:
            return httpx.Response(
                302,
                headers={"Location": "https://standards.ieee.org/standard/802_3-2022.html"},
            )
        if "standards.ieee.org" in url_str:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<html><head><title>IEEE 802.3 Ethernet Standard</title></head></html>",
            )

        # 4. Broken 404
        if "example.com/nonexistent-link" in url_str:
            return httpx.Response(404, text="404 Not Found")

        # 5. Public redirecting to private SSRF target
        if "example.com/redir-to-metadata" in url_str:
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})

        # 6. Oversized HTML body (> 2 MiB)
        if "example.com/oversized-report" in url_str:
            body = "<title>Comprehensive National Cyber Strategy 2026</title>" + ("Z" * (2 * 1024 * 1024))
            return httpx.Response(200, headers={"Content-Type": "text/html"}, text=body)

        # 7. Binary PDF
        if "example.com/guideline.pdf" in url_str:
            return httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=b"%PDF-1.7 binary content here",
            )

        # 8. Mismatched Crossref DOI
        if "api.crossref.org/works/10.1000/mismatched" in url_str:
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "message": {"title": ["Deep Neural Architecture Search for Embedded Systems"]},
                },
            )

        return httpx.Response(404, text="Not Found")

    return httpx.MockTransport(handler)


def main() -> int:
    print("=" * 70)
    print("HowlWriter Milestone 25.1 Dogfood: Source Integrity & SSRF Hardening")
    print("=" * 70)

    transport = create_dogfood_mock_transport()
    verifier = SourceIntegrityVerifier(mock_transport=transport)

    dogfood_sources = [
        # S1: Valid official HTTPS page
        Source(
            id="S01",
            title="NIST SP 800-53 Rev. 5 Security Controls",
            authors=["National Institute of Standards and Technology"],
            url="https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final",
            source_type=SourceType.REPORT,
            authority=SourceAuthority.STANDARD,
        ),
        # S2: Valid DOI with matching Crossref title
        Source(
            id="S02",
            title="Digital Object Identifier Handbook",
            authors=["Paskin, N."],
            doi="https://doi.org/10.1000/182",
            source_type=SourceType.JOURNAL_ARTICLE,
            authority=SourceAuthority.SCHOLARLY,
        ),
        # S3: Cross-domain redirect to a distinct public domain
        Source(
            id="S03",
            title="IEEE 802.3 Ethernet Standard",
            authors=["IEEE Standards Association"],
            url="https://example.com/external-redirect",
            source_type=SourceType.REPORT,
            authority=SourceAuthority.STANDARD,
        ),
        # S4: Broken dead link (HTTP 404)
        Source(
            id="S04",
            title="Defunct Advisory Notice",
            authors=["Unknown Agency"],
            url="https://example.com/nonexistent-link",
            source_type=SourceType.REPORT,
            authority=SourceAuthority.UNKNOWN,
        ),
        # S5: Direct private IP target (SSRF blocked upfront)
        Source(
            id="S05",
            title="Internal Gateway Router",
            authors=["Internal Admin"],
            url="http://192.168.1.1/admin",
            source_type=SourceType.WEBSITE,
            authority=SourceAuthority.UNKNOWN,
        ),
        # S6: Public URL redirecting to AWS/GCP metadata (SSRF blocked at redirect hop)
        Source(
            id="S06",
            title="Malicious Redirect Beacon",
            authors=["Adversary"],
            url="https://example.com/redir-to-metadata",
            source_type=SourceType.WEBSITE,
            authority=SourceAuthority.UNKNOWN,
        ),
        # S7: Oversized HTML document (> 2 MiB)
        Source(
            id="S07",
            title="Comprehensive National Cyber Strategy 2026",
            authors=["Executive Office"],
            url="https://example.com/oversized-report",
            source_type=SourceType.REPORT,
            authority=SourceAuthority.GOVERNMENT,
        ),
        # S8: Binary PDF document (body metadata unread)
        Source(
            id="S08",
            title="Technical Implementation Guide (PDF)",
            authors=["Security Agency"],
            url="https://example.com/guideline.pdf",
            source_type=SourceType.REPORT,
            authority=SourceAuthority.STANDARD,
        ),
        # S9: Registered DOI with completely mismatched title (hallucinated citation)
        Source(
            id="S09",
            title="Macroeconomic Implications of Global Carbon Taxation",
            authors=["Nordhaus, W."],
            doi="10.1000/mismatched",
            source_type=SourceType.JOURNAL_ARTICLE,
            authority=SourceAuthority.SCHOLARLY,
        ),
    ]

    print(f"\n1. Running verification across {len(dogfood_sources)} diverse sources...\n")
    report = verifier.verify_all(dogfood_sources)

    print(report.render_text())

    print("-" * 70)
    print("2. Validating Strict Semantic Criteria...")
    print("-" * 70)

    # Validate S01: Valid official
    f01 = report.findings[0]
    assert f01.access_status == ACCESS_VALID, f"S01 access {f01.access_status}"
    assert f01.metadata_status == METADATA_MATCH, f"S01 metadata {f01.metadata_status}"
    assert f01.severity == SEV_PASS, f"S01 severity {f01.severity}"
    print("✓ [S01] Official page: VALID, MATCH, PASS")

    # Validate S02: Valid DOI
    f02 = report.findings[1]
    assert f02.access_status == ACCESS_VALID, f"S02 access {f02.access_status}"
    assert f02.metadata_status == METADATA_MATCH, f"S02 metadata {f02.metadata_status}"
    assert f02.severity == SEV_PASS, f"S02 severity {f02.severity}"
    print("✓ [S02] Valid DOI: VALID, MATCH, PASS")

    # Validate S03: Cross-domain redirect
    f03 = report.findings[2]
    assert f03.access_status == ACCESS_REDIRECTED, f"S03 access {f03.access_status}"
    assert f03.severity == SEV_WARNING, f"S03 severity {f03.severity}"
    assert any("domain changed: True" in d for d in f03.diagnostics)
    print("✓ [S03] Cross-domain redirect: REDIRECTED, WARNING, domain-change tracked")

    # Validate S04: Broken 404
    f04 = report.findings[3]
    assert f04.access_status == ACCESS_BROKEN, f"S04 access {f04.access_status}"
    assert f04.severity == SEV_BLOCKING, f"S04 severity {f04.severity}"
    print("✓ [S04] Broken link (404): BROKEN, BLOCKING")

    # Validate S05: Direct private IP
    f05 = report.findings[4]
    assert f05.access_status == ACCESS_BROKEN, f"S05 access {f05.access_status}"
    assert f05.severity == SEV_BLOCKING, f"S05 severity {f05.severity}"
    assert any("SSRF Security Violation" in d for d in f05.diagnostics)
    print("✓ [S05] Direct private IP: BROKEN, BLOCKING, SSRF violation caught")

    # Validate S06: Redirect to metadata
    f06 = report.findings[5]
    assert f06.access_status == ACCESS_BROKEN, f"S06 access {f06.access_status}"
    assert f06.severity == SEV_BLOCKING, f"S06 severity {f06.severity}"
    assert any("SSRF Security Violation on redirect" in d for d in f06.diagnostics)
    print("✓ [S06] Redirect to metadata: BROKEN, BLOCKING, per-hop SSRF violation caught")

    # Validate S07: Oversized HTML
    f07 = report.findings[6]
    assert f07.access_status == ACCESS_VALID, f"S07 access {f07.access_status}"
    assert f07.metadata_status == METADATA_MATCH, f"S07 metadata {f07.metadata_status}"
    assert any(f"{MAX_INSPECT_BYTES} bytes" in d for d in f07.diagnostics)
    print(f"✓ [S07] Oversized HTML: VALID, MATCH, capped at {MAX_INSPECT_BYTES} bytes")

    # Validate S08: Binary PDF
    f08 = report.findings[7]
    assert f08.access_status == ACCESS_VALID, f"S08 access {f08.access_status}"
    assert f08.metadata_status == METADATA_UNKNOWN, f"S08 metadata {f08.metadata_status}"
    assert any("non-HTML content-type 'application/pdf'" in d for d in f08.diagnostics)
    print("✓ [S08] Binary PDF: VALID, METADATA_UNKNOWN (honest non-inspection)")

    # Validate S09: DOI mismatch
    f09 = report.findings[8]
    assert f09.access_status == ACCESS_VALID, f"S09 access {f09.access_status}"
    assert f09.metadata_status == METADATA_MISMATCH, f"S09 metadata {f09.metadata_status}"
    assert f09.severity == SEV_BLOCKING, f"S09 severity {f09.severity}"
    print("✓ [S09] Mismatched DOI title: VALID access, MISMATCH metadata, BLOCKING severity")

    print("\n3. Testing JSON Serialization Integrity...")
    json_report = report.to_dict()
    assert json_report["status"] == "BLOCKED"  # Contains BLOCKING findings
    assert len(json_report["findings"]) == 9
    json_str = json.dumps(json_report, indent=2)
    assert len(json_str) > 500
    print("✓ Machine-readable JSON report serialized cleanly.")

    print("\n" + "=" * 70)
    print("DOGFOOD VERIFICATION COMPLETED SUCCESSFULLY (ALL 9 INVARIANTS SATISFIED)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
