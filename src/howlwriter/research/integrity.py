"""Source and Citation Integrity Verification with SSRF protection, DNS rebinding mitigation,
bounded network retrieval, and hybrid metadata grounding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import difflib
import html
import ipaddress
import re
import socket
from typing import Any
import unicodedata
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

# Inspection and resource bounds
MAX_INSPECT_BYTES: int = 1024 * 1024  # 1 MiB default body inspection limit
DEFAULT_MAX_REDIRECTS: int = 5
DEFAULT_TIMEOUT_SECONDS: float = 8.0

# Localhost and cloud metadata aliases
PROHIBITED_HOSTNAMES: frozenset[str] = frozenset({
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
    "instance-data",
    "metadata.google.internal",
})


class SSRFSecurityError(ValueError):
    """Raised when a URL targets a private, loopback, or cloud-metadata IP address."""


def is_prohibited_ip(ip_val: ipaddress.IPv4Address | ipaddress.IPv6Address | str) -> bool:
    """Checks whether an IP address belongs to private, loopback, link-local, multicast,
    cloud-metadata, reserved, or unspecified address spaces, including IPv4-mapped IPv6.
    """
    if isinstance(ip_val, str):
        try:
            ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(ip_val)
        except ValueError:
            return True
    else:
        ip_obj = ip_val

    # Unpack IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1 -> 127.0.0.1)
    effective_ip = getattr(ip_obj, "ipv4_mapped", None) or ip_obj

    return (
        effective_ip.is_loopback
        or effective_ip.is_private
        or effective_ip.is_link_local
        or effective_ip.is_multicast
        or effective_ip.is_reserved
        or effective_ip.is_unspecified
        or str(effective_ip) == "169.254.169.254"
    )


def validate_url_security(url: str) -> None:
    """Validates that a URL uses http(s) and does not target internal, loopback, or metadata ranges."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFSecurityError(
            f"Unsupported scheme '{parsed.scheme}': only http and https are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("Missing hostname in URL.")

    # Check for localhost / loopback / metadata string names
    lowered_host = hostname.lower()
    if lowered_host in PROHIBITED_HOSTNAMES or lowered_host.endswith(".localhost"):
        raise SSRFSecurityError(f"Targeting localhost or cloud metadata is prohibited: {hostname}")

    # Resolve IP address and check if ANY returned IP is in prohibited ranges
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        if not addr_info:
            raise ConnectionError(f"DNS resolution returned no addresses for '{hostname}'")
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if is_prohibited_ip(ip_str):
                raise SSRFSecurityError(
                    f"Target IP address {ip_str} for host '{hostname}' is in a prohibited or private range."
                )
    except socket.gaierror as exc:
        raise ConnectionError(f"DNS resolution failed for '{hostname}': {exc}") from exc


try:
    import httpcore
    import httpx

    class SSRFSafeSyncBackend(httpcore.SyncBackend):
        """Sync backend that inspects the connected TCP socket peer IP before TLS or data transfer."""

        def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any | None = None,
        ) -> Any:
            stream = super().connect_tcp(
                host, port, timeout=timeout, local_address=local_address, socket_options=socket_options
            )
            try:
                sock = getattr(stream, "_sock", None)
                if sock is not None:
                    peer_ip = sock.getpeername()[0]
                    if is_prohibited_ip(peer_ip):
                        stream.close()
                        raise SSRFSecurityError(
                            f"Post-connect peer IP {peer_ip} for '{host}' is in a prohibited range."
                        )
            except Exception:
                stream.close()
                raise
            return stream

    class SSRFSafeTransport(httpx.HTTPTransport):
        """Transport enforcing socket-level SSRF defenses against DNS rebinding."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._pool = httpcore.ConnectionPool(
                network_backend=SSRFSafeSyncBackend(),
                retries=0,
            )

except ImportError:  # pragma: no cover
    SSRFSafeSyncBackend = None  # type: ignore[misc,assignment]
    SSRFSafeTransport = None  # type: ignore[misc,assignment]


def _normalize_title(title: str) -> str:
    """Normalizes document or metadata title for robust comparison."""
    if not title:
        return ""
    # Decode HTML entities (e.g. &amp;, &quot;, &#39;)
    t = html.unescape(title)
    # Unicode NFKC normalization
    t = unicodedata.normalize("NFKC", t)
    # Strip HTML tags if present
    t = re.sub(r"<[^>]+>", " ", t)
    # Strip common journal / platform noise suffixes
    t = re.sub(
        r"\s*[-|–—:]\s*(Nature|ScienceDirect|SpringerLink|IEEE Xplore|arXiv|PMC|PubMed|"
        r"Wiley Online Library|ACM Digital Library|Science\.org|NIST CSRC|NIST Publications).*$",
        "",
        t,
        flags=re.IGNORECASE,
    )
    # Normalize punctuation to spaces
    t = re.sub(r"[^\w\s]", " ", t)
    # Case fold and collapse whitespace
    return re.sub(r"\s+", " ", t).strip().casefold()


def _compute_string_similarity(a: str, b: str) -> float:
    """Hybrid normalized similarity between two titles combining difflib sequence matching,
    token Jaccard, and subtitle/containment heuristics.
    """
    norm_a = _normalize_title(a)
    norm_b = _normalize_title(b)

    if not norm_a and not norm_b:
        return 1.0
    if not norm_a or not norm_b:
        return 0.0

    # 1. difflib SequenceMatcher ratio
    seq_ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()

    # 2. Token Jaccard similarity (words >= 2 characters)
    tokens_a = set(re.findall(r"\b\w{2,}\b", norm_a))
    tokens_b = set(re.findall(r"\b\w{2,}\b", norm_b))
    union = len(tokens_a | tokens_b)
    jaccard = (len(tokens_a & tokens_b) / union) if union else 0.0

    # 3. Subtitle / containment heuristic
    shorter, longer = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    containment = 0.0
    if len(shorter) >= 6 and shorter in longer:
        containment = len(shorter) / len(longer)

    # 4. Main title ratio before subtitle delimiters
    main_a = _normalize_title(re.split(r"[:–—]| - ", a)[0])
    main_b = _normalize_title(re.split(r"[:–—]| - ", b)[0])
    main_ratio = 0.0
    if main_a and main_b and (main_a != norm_a or main_b != norm_b):
        main_ratio = difflib.SequenceMatcher(None, main_a, main_b).ratio()

    combined = max(seq_ratio, jaccard, containment, main_ratio * 0.95)
    return round(combined, 4)


def normalize_doi(raw_doi: str) -> str:
    """Normalizes various DOI formats into standard '10.xxxx/...' form."""
    cleaned = raw_doi.strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    if cleaned.lower().startswith("doi:"):
        cleaned = cleaned[4:].strip()
    return cleaned.rstrip(".,;)")


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
        summary_str = (
            f"Total Sources: {self.total_sources} "
            f"(Valid: {self.valid_access_count}, Broken: {self.broken_access_count}, "
            f"Blocking: {self.blocking_count})"
        )
        lines.append(summary_str)
        lines.append("")

        for f in self.findings:
            if f.severity == SEV_PASS:
                symbol = "✓"
            elif f.severity in (SEV_WARNING, SEV_INFORMATIONAL):
                symbol = "!"
            else:
                symbol = "✗"
            lines.append(f"{symbol} [{f.source_id}] {f.source_title}")
            lines.append(f"   Identifier / URL: {f.url_or_doi}")
            lines.append(
                f"   Access: {f.access_status} (HTTP {f.http_status or 'N/A'}), "
                f"Metadata: {f.metadata_status}, Evidence: {f.evidence_support}"
            )
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
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_inspect_bytes: int = MAX_INSPECT_BYTES,
        mock_transport: Any | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.max_inspect_bytes = max_inspect_bytes
        self.mock_transport = mock_transport

    def _build_client(self) -> httpx.Client:
        import httpx

        timeout = httpx.Timeout(
            min(self.timeout_seconds, 5.0),
            connect=min(self.timeout_seconds, 5.0),
            read=self.timeout_seconds,
            write=min(self.timeout_seconds, 5.0),
            pool=min(self.timeout_seconds, 5.0),
        )
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": False,
            "trust_env": False,
        }
        if self.mock_transport is not None:
            client_kwargs["transport"] = self.mock_transport
        elif SSRFSafeTransport is not None:
            client_kwargs["transport"] = SSRFSafeTransport()

        return httpx.Client(**client_kwargs)

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
        clean_doi = normalize_doi(doi)

        api_url = f"https://api.crossref.org/works/{clean_doi}"
        headers = {
            "User-Agent": "HowlWriter-SourceIntegrity/1.0 (mailto:integrity@howlwriter.dev)"
        }
        evidence_support = getattr(source, "relevance", "UNVERIFIED")

        try:
            with self._build_client() as client:
                client.headers.update(headers)
                current_url = api_url
                redirect_count = 0
                visited = {current_url}

                # Safe per-hop redirect resolution for Crossref endpoint
                while True:
                    validate_url_security(current_url)
                    resp = client.get(current_url)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("Location")
                        if not loc:
                            break
                        next_url = urllib.parse.urljoin(current_url, loc)
                        redirect_count += 1
                        if redirect_count > self.max_redirects:
                            return SourceIntegrityFinding(
                                source_id=source.id,
                                source_title=source.title,
                                url_or_doi=doi,
                                access_status=ACCESS_BROKEN,
                                metadata_status=METADATA_UNKNOWN,
                                evidence_support=evidence_support,
                                severity=SEV_WARNING,
                                diagnostics=[
                                    f"DOI lookup exceeded max redirects ({self.max_redirects})."
                                ],
                            )
                        if next_url in visited:
                            return SourceIntegrityFinding(
                                source_id=source.id,
                                source_title=source.title,
                                url_or_doi=doi,
                                access_status=ACCESS_BROKEN,
                                metadata_status=METADATA_UNKNOWN,
                                evidence_support=evidence_support,
                                severity=SEV_BLOCKING,
                                diagnostics=[f"DOI lookup encountered redirect loop: {next_url}"],
                            )
                        visited.add(next_url)
                        validate_url_security(next_url)
                        current_url = next_url
                        continue
                    break

            if resp.status_code == 404:
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=doi,
                    access_status=ACCESS_BROKEN,
                    metadata_status=METADATA_MISMATCH,
                    evidence_support=evidence_support,
                    severity=SEV_BLOCKING,
                    http_status=404,
                    diagnostics=[
                        f"DOI '{doi}' not found in Crossref registry (HTTP 404). "
                        "Likely invalid or fabricated."
                    ],
                )

            if resp.status_code == 429:
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=doi,
                    access_status=ACCESS_UNKNOWN,
                    metadata_status=METADATA_UNKNOWN,
                    evidence_support=evidence_support,
                    severity=SEV_WARNING,
                    http_status=429,
                    diagnostics=["Crossref registrar rate-limited request (HTTP 429)."],
                )

            if resp.status_code >= 500:
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=doi,
                    access_status=ACCESS_UNKNOWN,
                    metadata_status=METADATA_UNKNOWN,
                    evidence_support=evidence_support,
                    severity=SEV_WARNING,
                    http_status=resp.status_code,
                    diagnostics=[f"Crossref registrar service unavailable (HTTP {resp.status_code})."],
                )

            if resp.status_code != 200:
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=doi,
                    access_status=ACCESS_BROKEN,
                    metadata_status=METADATA_UNKNOWN,
                    evidence_support=evidence_support,
                    severity=SEV_WARNING,
                    http_status=resp.status_code,
                    diagnostics=[f"Crossref registrar returned non-200 status {resp.status_code}."],
                )

            data = resp.json()
            work = data.get("message", {})
            titles = work.get("title", [])
            retrieved_title = titles[0] if titles else ""

            if not retrieved_title:
                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=doi,
                    access_status=ACCESS_VALID,
                    metadata_status=METADATA_UNKNOWN,
                    evidence_support=evidence_support,
                    severity=SEV_WARNING,
                    http_status=200,
                    resolved_url=current_url,
                    retrieved_title="",
                    diagnostics=["DOI resolved in Crossref, but metadata contains no title."],
                )

            sim = _compute_string_similarity(source.title, retrieved_title)
            meta_status = (
                METADATA_MATCH
                if sim >= 0.65
                else (METADATA_PARTIAL if sim >= 0.35 else METADATA_MISMATCH)
            )
            severity = (
                SEV_PASS
                if meta_status == METADATA_MATCH
                else (SEV_WARNING if meta_status == METADATA_PARTIAL else SEV_BLOCKING)
            )

            diags = [f"DOI resolved successfully in Crossref. Title similarity: {sim:.2f}"]
            if meta_status == METADATA_MISMATCH:
                diags.append(
                    f"Metadata title mismatch: expected '{source.title}', "
                    f"registrar returned '{retrieved_title}'."
                )

            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=doi,
                access_status=ACCESS_VALID,
                metadata_status=meta_status,
                evidence_support=evidence_support,
                severity=severity,
                http_status=200,
                resolved_url=current_url,
                title_match_ratio=sim,
                retrieved_title=retrieved_title,
                diagnostics=diags,
            )
        except Exception as exc:
            is_timeout = "timeout" in str(exc).lower()
            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=doi,
                access_status=ACCESS_TIMEOUT if is_timeout else ACCESS_BROKEN,
                metadata_status=METADATA_UNKNOWN,
                evidence_support=evidence_support,
                severity=SEV_WARNING,
                diagnostics=[f"DOI lookup failed: {exc}"],
            )

    def _verify_url(self, source: Source) -> SourceIntegrityFinding:
        """Verifies standard web URL with per-hop SSRF protection, bounded streaming,
        and metadata inspection.
        """
        url = source.url.strip()  # type: ignore[union-attr]
        evidence_support = getattr(source, "relevance", "UNVERIFIED")

        # 1. Initial SSRF check on input URL
        try:
            validate_url_security(url)
        except SSRFSecurityError as ssrf_err:
            return SourceIntegrityFinding(
                source_id=source.id,
                source_title=source.title,
                url_or_doi=url,
                access_status=ACCESS_BROKEN,
                metadata_status=METADATA_MISMATCH,
                evidence_support=evidence_support,
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
                evidence_support=evidence_support,
                severity=SEV_WARNING,
                diagnostics=[f"DNS/Network resolution failed: {net_err}"],
            )

        headers = {
            "User-Agent": "HowlWriter-SourceIntegrity/1.0 (academic research client)"
        }

        try:
            current_url = url
            redirect_history = [current_url]
            visited_urls = {current_url}
            redirect_count = 0
            orig_host = (urllib.parse.urlparse(url).hostname or "").lower()

            with self._build_client() as client:
                client.headers.update(headers)

                while True:
                    # Issue request with follow_redirects=False; probe with HEAD first
                    used_head = True
                    try:
                        resp = client.head(current_url)
                        if resp.status_code in (403, 405):
                            used_head = False
                            resp = client.get(current_url)
                    except Exception:
                        used_head = False
                        resp = client.get(current_url)

                    # Check for 3xx redirect status
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location")
                        if not location:
                            return SourceIntegrityFinding(
                                source_id=source.id,
                                source_title=source.title,
                                url_or_doi=url,
                                access_status=ACCESS_BROKEN,
                                metadata_status=METADATA_UNKNOWN,
                                evidence_support=evidence_support,
                                severity=SEV_WARNING,
                                http_status=resp.status_code,
                                resolved_url=current_url,
                                diagnostics=[
                                    f"Redirect HTTP {resp.status_code} missing Location header."
                                ],
                            )

                        next_url = urllib.parse.urljoin(current_url, location)
                        redirect_count += 1
                        if redirect_count > self.max_redirects:
                            return SourceIntegrityFinding(
                                source_id=source.id,
                                source_title=source.title,
                                url_or_doi=url,
                                access_status=ACCESS_BROKEN,
                                metadata_status=METADATA_UNKNOWN,
                                evidence_support=evidence_support,
                                severity=SEV_WARNING,
                                http_status=resp.status_code,
                                resolved_url=current_url,
                                diagnostics=[
                                    f"Exceeded maximum redirect limit ({self.max_redirects})."
                                ],
                            )

                        if next_url in visited_urls:
                            return SourceIntegrityFinding(
                                source_id=source.id,
                                source_title=source.title,
                                url_or_doi=url,
                                access_status=ACCESS_BROKEN,
                                metadata_status=METADATA_MISMATCH,
                                evidence_support=evidence_support,
                                severity=SEV_BLOCKING,
                                http_status=resp.status_code,
                                resolved_url=next_url,
                                diagnostics=[f"Redirect loop detected targeting '{next_url}'."],
                            )

                        # Validate redirect target SSRF before sending request to that hop
                        try:
                            validate_url_security(next_url)
                        except SSRFSecurityError as ssrf_err:
                            return SourceIntegrityFinding(
                                source_id=source.id,
                                source_title=source.title,
                                url_or_doi=url,
                                access_status=ACCESS_BROKEN,
                                metadata_status=METADATA_MISMATCH,
                                evidence_support=evidence_support,
                                severity=SEV_BLOCKING,
                                resolved_url=current_url,
                                diagnostics=[
                                    f"SSRF Security Violation on redirect to '{next_url}': {ssrf_err}"
                                ],
                            )

                        visited_urls.add(next_url)
                        redirect_history.append(next_url)
                        current_url = next_url
                        continue

                    # Terminal response reached
                    break

                final_url = current_url
                redirected = final_url != url

                if resp.status_code >= 400:
                    is_404 = resp.status_code == 404
                    return SourceIntegrityFinding(
                        source_id=source.id,
                        source_title=source.title,
                        url_or_doi=url,
                        access_status=ACCESS_BROKEN,
                        metadata_status=METADATA_UNKNOWN,
                        evidence_support=evidence_support,
                        severity=SEV_BLOCKING if is_404 else SEV_WARNING,
                        http_status=resp.status_code,
                        resolved_url=final_url,
                        diagnostics=[f"URL returned HTTP status {resp.status_code}."],
                    )

                # Check domain change on redirects
                dest_host = (urllib.parse.urlparse(final_url).hostname or "").lower()
                domain_changed = not (dest_host == orig_host or dest_host.endswith(f".{orig_host}"))

                access_status = ACCESS_REDIRECTED if redirected else ACCESS_VALID
                severity = SEV_WARNING if (redirected and domain_changed) else SEV_PASS

                diags = [f"URL resolved successfully (HTTP {resp.status_code})."]
                if redirected:
                    hops = len(redirect_history) - 1
                    diags.append(
                        f"Redirected through {hops} hop(s) to {final_url} "
                        f"(domain changed: {domain_changed})."
                    )

                # Bounded retrieval & content-type handling
                content_type = (resp.headers.get("content-type") or "").lower()
                retrieved_title = None
                sim = 0.5

                is_html = "html" in content_type or "xhtml" in content_type
                is_binary = any(
                    b in content_type
                    for b in ("pdf", "octet-stream", "image/", "video/", "audio/", "zip", "tar", "gzip")
                )

                if is_binary or not is_html:
                    meta_status = METADATA_UNKNOWN
                    diags.append(
                        f"Reachable (HTTP {resp.status_code}), non-HTML content-type '{content_type}'; "
                        "body metadata not inspected."
                    )
                else:
                    html_text = ""
                    if used_head:
                        try:
                            with client.stream("GET", final_url) as stream_resp:
                                chunks: list[bytes] = []
                                total_bytes = 0
                                for chunk in stream_resp.iter_bytes():
                                    chunks.append(chunk)
                                    total_bytes += len(chunk)
                                    if total_bytes >= self.max_inspect_bytes:
                                        diags.append(
                                            f"Response exceeded inspection limit "
                                            f"({self.max_inspect_bytes} bytes); stream terminated early."
                                        )
                                        break
                                    if b"</title>" in b"".join(chunks).lower():
                                        break
                                encoding = stream_resp.encoding or "utf-8"
                                html_text = b"".join(chunks)[: self.max_inspect_bytes].decode(
                                    encoding, errors="replace"
                                )
                        except Exception as stream_err:
                            diags.append(f"Bounded stream inspection failed: {stream_err}")
                    else:
                        html_text = resp.text[: self.max_inspect_bytes]
                        if len(resp.content) > self.max_inspect_bytes:
                            diags.append(
                                f"Response exceeded inspection limit "
                                f"({self.max_inspect_bytes} bytes); truncated."
                            )

                    if html_text:
                        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html_text, re.IGNORECASE)
                        if title_match:
                            retrieved_title = title_match.group(1).strip()
                            sim = _compute_string_similarity(source.title, retrieved_title)
                            diags.append(
                                f"Retrieved page title: '{retrieved_title[:60]}' (similarity: {sim:.2f})"
                            )

                    if retrieved_title:
                        meta_status = (
                            METADATA_MATCH
                            if sim >= 0.65
                            else (METADATA_PARTIAL if sim >= 0.35 else METADATA_MISMATCH)
                        )
                    else:
                        meta_status = METADATA_UNKNOWN

                return SourceIntegrityFinding(
                    source_id=source.id,
                    source_title=source.title,
                    url_or_doi=url,
                    access_status=access_status,
                    metadata_status=meta_status,
                    evidence_support=evidence_support,
                    severity=severity,
                    http_status=resp.status_code,
                    resolved_url=final_url,
                    title_match_ratio=sim if retrieved_title else 0.0,
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
                evidence_support=evidence_support,
                severity=SEV_WARNING,
                diagnostics=[f"HTTP request failed: {exc}"],
            )
