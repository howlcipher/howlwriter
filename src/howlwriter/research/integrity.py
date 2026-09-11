"""Source and Citation Integrity Verification with SSRF protection and metadata grounding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import re
import socket
from typing import Any
import urllib.parse

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import Source


# Access statuses
ACCESS_VALID = "VALID"
ACCESS_BROKEN = "BROKEN"
ACCESS_REDIRECTED = "REDIRECTED"
ACCESS_TIMEOUT = "TIMEOUT"
ACCESS_UNKNOWN = "UNKNOWN"

# Metadata statuses
METADATA_MATCH = "MATCH"
METADATA_PARTIAL = "PARTIAL"
METADATA_MISMATCH = "MISMATCH"
METADATA_UNKNOWN = "UNKNOWN"

# Severity levels
SEV_BLOCKING = "BLOCKING"
SEV_WARNING = "WARNING"
SEV_INFORMATIONAL = "INFORMATIONAL"
SEV_PASS = "PASS"


class SSRFSecurityError(ValueError):
    """Raised when a URL targets a private, loopback, or cloud-metadata IP address."""


def validate_url_security(url: str) -> None:
    """Validates that a URL uses http(s) and does not target internal or metadata network ranges."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFSecurityError(
            f"Unsupported scheme '{parsed.scheme}': only http and https are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("Missing hostname in URL.")

    # Check for localhost / loopback string names
    if hostname.lower() in ("localhost", "ip6-localhost", "ip6-loopback", "instance-data"):
        raise SSRFSecurityError(f"Targeting localhost or instance-data is prohibited: {hostname}")

    # Resolve IP address and check if it is in private/loopback/link-local/multicast ranges
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or str(ip_obj) == "169.254.169.254"  # AWS/GCP/Azure metadata
            ):
                raise SSRFSecurityError(
                    f"Target IP address {ip_str} for host '{hostname}' is in a prohibited or private range."
                )
    except socket.gaierror as exc:
        raise ConnectionError(f"DNS resolution failed for '{hostname}': {exc}") from exc


def _compute_string_similarity(a: str, b: str) -> float:
    """Token-based Jaccard similarity between two strings."""
    tokens_a = set(re.findall(r"\b\w{3,}\b", a.lower()))
    tokens_b = set(re.findall(r"\b\w{3,}\b", b.lower()))
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union else 0.0


@dataclass
class SourceIntegrityFinding(DataClassSerializationMixin):
    """Integrity evaluation result for a single source."""

    source_id: str
    source_title: str
    url_or_doi: str
    access_status: str  # VALID | BROKEN | REDIRECTED | TIMEOUT | UNKNOWN
    metadata_status: str  # MATCH | PARTIAL | MISMATCH | UNKNOWN
    evidence_support: str  # DIRECT | SUPPORTING | TANGENTIAL | IRRELEVANT | UNVERIFIED
    severity: str  # BLOCKING | WARNING | INFORMATIONAL | PASS
    http_status: int | None = None
    resolved_url: str | None = None
    title_match_ratio: float = 0.0
    retrieved_title: str | None = None
    diagnostics: list[str] = field(default_factory=list)
    verified_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class SourceIntegrityReport(DataClassSerializationMixin):
    """Aggregated verification report for a collection of sources."""

    findings: list[SourceIntegrityFinding] = field(default_factory=list)
    status: str = "PASS"  # PASS | NEEDS_REVIEW | BLOCKED
    verified_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def total_sources(self) -> int:
        return len(self.findings)

    @property
    def blocking_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEV_BLOCKING)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEV_WARNING)

    @property
    def valid_access_count(self) -> int:
        return sum(1 for f in self.findings if f.access_status == ACCESS_VALID)

    @property
    def broken_access_count(self) -> int:
        return sum(1 for f in self.findings if f.access_status in (ACCESS_BROKEN, ACCESS_TIMEOUT))

    def render_text(self) -> str:
        lines: list[str] = ["SOURCE INTEGRITY VERIFICATION REPORT", "===================================="]
        lines.append(f"Status: {self.status}")
        lines.append(f"Total Sources: {self.total_sources} (Valid: {self.valid_access_count}, Broken: {self.broken_access_count}, Blocking: {self.blocking_count})")
        lines.append("")

        for f in self.findings:
            symbol = "✓" if f.severity == SEV_PASS else ("!" if f.severity in (SEV_WARNING, SEV_INFORMATIONAL) else "✗")
            lines.append(f"{symbol} [{f.source_id}] {f.source_title}")
            lines.append(f"   Identifier / URL: {f.url_or_doi}")
            lines.append(f"   Access: {f.access_status} (HTTP {f.http_status or 'N/A'}), Metadata: {f.metadata_status}, Evidence: {f.evidence_support}")
            if f.resolved_url and f.resolved_url != f.url_or_doi:
                lines.append(f"   Redirected to: {f.resolved_url}")
            for d in f.diagnostics:
                lines.append(f"   - {d}")
            lines.append("")

        return "\n".join(lines)


class SourceIntegrityVerifier:
    """Validates operational reachability, identifier grounding, and metadata authenticity."""

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        max_redirects: int = 5,
        mock_transport: Any | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.mock_transport = mock_transport

    def verify_source(self, source: Source) -> SourceIntegrityFinding:
        """Verifies a single source across network access and metadata dimensions."""
        url_or_doi = source.doi or source.url or ""
        evidence_support = getattr(source, "relevance", "UNVERIFIED")

        # If no URL or DOI, unverified
        if not url_or_doi:
            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi="<missing>",
                access_status=ACCESS_UNKNOWN,
                metadata_status=METADATA_UNKNOWN,
                evidence_support=evidence_support,
                severity=SEV_WARNING,
                diagnostics=["Source lacks both URL and DOI identifier."],
            )

        # DOI verification path
        if source.doi:
            return self._verify_doi(source)

        # General URL verification path
        return self._verify_url(source)

    def verify_all(self, sources: list[Source]) -> SourceIntegrityReport:
        """Verifies a list of sources and produces an aggregate report."""
        findings = [self.verify_source(s) for s in sources]
        status = "PASS"
        if any(f.severity == SEV_BLOCKING for f in findings):
            status = "BLOCKED"
        elif any(f.severity == SEV_WARNING for f in findings):
            status = "NEEDS_REVIEW"

        return SourceIntegrityReport(findings=findings, status=status)

    def _verify_doi(self, source: Source) -> SourceIntegrityFinding:
        """Verifies DOI against official Crossref registrar."""
        doi = source.doi.strip()  # type: ignore[union-attr]
        clean_doi = doi.lower()
        if clean_doi.startswith("https://doi.org/"):
            clean_doi = clean_doi.replace("https://doi.org/", "")
        elif clean_doi.startswith("http://doi.org/"):
            clean_doi = clean_doi.replace("http://doi.org/", "")

        api_url = f"https://api.crossref.org/works/{clean_doi}"
        headers = {
            "User-Agent": "HowlWriter-SourceIntegrity/1.0 (mailto:integrity@howlwriter.dev)"
        }

        try:
            import httpx

            client_kwargs: dict[str, Any] = {
                "timeout": self.timeout_seconds,
                "follow_redirects": True,
                "headers": headers,
            }
            if self.mock_transport:
                client_kwargs["transport"] = self.mock_transport

            with httpx.Client(**client_kwargs) as client:
                resp = client.get(api_url)

            if resp.status_code == 404:
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=doi,
                    access_status=ACCESS_BROKEN,
                    metadata_status=METADATA_MISMATCH,
                    evidence_support=source.relevance,
                    severity=SEV_BLOCKING,
                    http_status=404,
                    diagnostics=[f"DOI '{doi}' not found in Crossref registry (HTTP 404). Likely fabricated or invalid."],
                )

            if resp.status_code != 200:
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=doi,
                    access_status=ACCESS_BROKEN,
                    metadata_status=METADATA_UNKNOWN,
                    evidence_support=source.relevance,
                    severity=SEV_WARNING,
                    http_status=resp.status_code,
                    diagnostics=[f"Registrar returned non-200 status {resp.status_code}."],
                )

            data = resp.json()
            work = data.get("message", {})
            titles = work.get("title", [])
            retrieved_title = titles[0] if titles else ""

            sim = _compute_string_similarity(source.title, retrieved_title)
            meta_status = METADATA_MATCH if sim >= 0.45 else (METADATA_PARTIAL if sim >= 0.25 else METADATA_MISMATCH)
            severity = SEV_PASS if meta_status == METADATA_MATCH else (SEV_WARNING if meta_status == METADATA_PARTIAL else SEV_BLOCKING)

            diags = [f"DOI resolved successfully in Crossref. Title similarity: {sim:.2f}"]
            if meta_status == METADATA_MISMATCH:
                diags.append(f"Metadata title mismatch: expected '{source.title}', registrar returned '{retrieved_title}'.")

            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=doi,
                access_status=ACCESS_VALID,
                metadata_status=meta_status,
                evidence_support=source.relevance,
                severity=severity,
                http_status=200,
                resolved_url=api_url,
                title_match_ratio=sim,
                retrieved_title=retrieved_title,
                diagnostics=diags,
            )
        except Exception as exc:
            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=doi,
                access_status=ACCESS_TIMEOUT if "timeout" in str(exc).lower() else ACCESS_BROKEN,
                metadata_status=METADATA_UNKNOWN,
                evidence_support=source.relevance,
                severity=SEV_WARNING,
                diagnostics=[f"DOI lookup failed: {exc}"],
            )

    def _verify_url(self, source: Source) -> SourceIntegrityFinding:
        """Verifies standard web URL with SSRF protection."""
        url = source.url.strip()  # type: ignore[union-attr]

        # 1. SSRF check
        try:
            validate_url_security(url)
        except SSRFSecurityError as ssrf_err:
            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=url,
                access_status=ACCESS_BROKEN,
                metadata_status=METADATA_MISMATCH,
                evidence_support=source.relevance,
                severity=SEV_BLOCKING,
                diagnostics=[f"SSRF Security Violation: {ssrf_err}"],
            )
        except Exception as net_err:
            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=url,
                access_status=ACCESS_BROKEN,
                metadata_status=METADATA_UNKNOWN,
                evidence_support=source.relevance,
                severity=SEV_WARNING,
                diagnostics=[f"DNS/Network resolution failed: {net_err}"],
            )

        # 2. HTTP Request
        headers = {
            "User-Agent": "HowlWriter-SourceIntegrity/1.0 (academic research client)"
        }

        try:
            import httpx

            client_kwargs: dict[str, Any] = {
                "timeout": self.timeout_seconds,
                "follow_redirects": True,
                "max_redirects": self.max_redirects,
                "headers": headers,
            }
            if self.mock_transport:
                client_kwargs["transport"] = self.mock_transport

            with httpx.Client(**client_kwargs) as client:
                # First attempt HEAD for speed and bounded data transfer
                try:
                    resp = client.head(url)
                    if resp.status_code in (405, 403):
                        # Some servers reject HEAD, try GET with stream limit
                        resp = client.get(url)
                except Exception:
                    resp = client.get(url)

            final_url = str(resp.url)
            redirected = final_url != url

            if resp.status_code >= 400:
                is_404 = resp.status_code == 404
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=url,
                    access_status=ACCESS_BROKEN,
                    metadata_status=METADATA_UNKNOWN,
                    evidence_support=source.relevance,
                    severity=SEV_BLOCKING if is_404 else SEV_WARNING,
                    http_status=resp.status_code,
                    resolved_url=final_url,
                    diagnostics=[f"URL returned HTTP status {resp.status_code}."],
                )

            # Check for suspicious redirects (e.g. redirected to completely different domain or search parked page)
            orig_host = urllib.parse.urlparse(url).hostname or ""
            dest_host = urllib.parse.urlparse(final_url).hostname or ""
            domain_changed = not (dest_host == orig_host or dest_host.endswith(f".{orig_host}"))

            access_status = ACCESS_REDIRECTED if redirected else ACCESS_VALID
            severity = SEV_WARNING if (redirected and domain_changed) else SEV_PASS

            diags = [f"URL resolved successfully (HTTP {resp.status_code})."]
            if redirected:
                diags.append(f"Redirected to {final_url} (domain changed: {domain_changed}).")

            # Extract title if HTML response is present
            retrieved_title = None
            sim = 0.5  # default neutral
            content_type = resp.headers.get("content-type", "")
            if "html" in content_type and resp.text:
                title_match = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.IGNORECASE)
                if title_match:
                    retrieved_title = title_match.group(1).strip()
                    sim = _compute_string_similarity(source.title, retrieved_title)
                    diags.append(f"Retrieved page title: '{retrieved_title[:60]}' (similarity: {sim:.2f})")

            meta_status = METADATA_MATCH if sim >= 0.35 else (METADATA_PARTIAL if sim >= 0.15 else METADATA_MISMATCH)

            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=url,
                access_status=access_status,
                metadata_status=meta_status,
                evidence_support=source.relevance,
                severity=severity,
                http_status=resp.status_code,
                resolved_url=final_url,
                title_match_ratio=sim,
                retrieved_title=retrieved_title,
                diagnostics=diags,
            )

        except Exception as exc:
            is_timeout = "timeout" in str(exc).lower()
            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=url,
                access_status=ACCESS_TIMEOUT if is_timeout else ACCESS_BROKEN,
                metadata_status=METADATA_UNKNOWN,
                evidence_support=source.relevance,
                severity=SEV_WARNING,
                diagnostics=[f"HTTP request failed: {exc}"],
            )
