# Source Integrity, SSRF Defense & Authority Verification

HowlWriter treats source verification and citation integrity as first-class, verifiable boundaries. It enforces a strict separation between **operational source integrity** (reachability, format validity, SSRF defense, DOI registry status) and **semantic claim relevance** (whether evidence substantiates a specific factual assertion).

---

## 1. Core Principles

1. **Orthogonality:** A source may be completely reachable, valid, and registered (operational pass), yet provide zero substantive support for a draft's claims. Conversely, a relevant quotation from an unreachable website remains unverified. The pipeline reports both dimensions independently.
2. **Strict SSRF Defenses:** Automated source verification must never be used as a vector for Server-Side Request Forgery against local infrastructure, intranet services, or cloud instance metadata endpoints.
3. **Bounded Network Retrieval:** Probes must never download unbounded response bodies (ISOs, archives, multi-gigabyte videos) merely to verify reachability or titles.
4. **Honest Verification Semantics:** If a document is a binary PDF, reachability is validated while metadata is honestly reported as uninspected (`METADATA_UNKNOWN`), never claiming title verification when none took place.
5. **Semantic Authority Hierarchy:** Sources are classified by legal, regulatory, scholarly, or industry authority, allowing assignments to require primary-law or standard-level grounding where needed.

---

## 2. SSRF Protection Architecture

The SSRF validator (`howlwriter.research.integrity::validate_url_security`) inspects every candidate URL before any network socket is opened.

### Blocked Ranges & Patterns

| Target Type | Blocked Range / Host | Purpose |
| --- | --- | --- |
| **IPv4 Loopback** | `127.0.0.0/8`, `localhost`, `*.localhost` | Prevents scanning local background services and databases. |
| **IPv6 Loopback** | `::1`, `ip6-localhost`, `ip6-loopback` | Prevents IPv6 localhost attacks. |
| **Private Networks (RFC 1918)** | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | Blocks access to internal corporate subnets and dev clusters. |
| **Cloud Instance Metadata** | `169.254.169.254`, `metadata.google.internal`, `instance-data` | Prevents exfiltration of cloud IAM credentials or instance tokens. |
| **Link-Local & Multicast** | `169.254.0.0/16`, `224.0.0.0/4`, `fe80::/10` | Disallows non-routable link and multicast addresses. |
| **IPv4-Mapped IPv6** | `::ffff:127.0.0.1`, `::ffff:169.254.169.254`, etc. | Closes IPv6 encapsulation bypasses for prohibited IPv4 ranges. |
| **Unspecified & Reserved** | `0.0.0.0`, `::`, `240.0.0.0/4` | Blocks non-routable and reserved network segments. |
| **Non-HTTP Schemes** | `file://`, `ftp://`, `gopher://`, `data://` | Enforces explicit HTTP/HTTPS scheme restrictions. |

### Per-Hop Redirect Validation

Automatic redirect following (`follow_redirects=True`) is disabled. HowlWriter executes an explicit per-hop redirect loop:
1. Every candidate URL is parsed and validated for scheme and prohibited hostnames before connecting.
2. If the server responds with a 3xx status (`301`, `302`, `303`, `307`, `308`), the `Location` header is extracted and resolved via `urllib.parse.urljoin`.
3. The redirect hop count is incremented and bounded (`max_redirects = 5`). Exceeding the limit halts verification with `ACCESS_BROKEN` (`SEV_WARNING`).
4. Redirect cycles are detected via visited-URL tracking; loops halt execution with `ACCESS_BROKEN` (`SEV_BLOCKING`).
5. The redirect target is independently validated through `validate_url_security()` **before** any request is dispatched to that hop. Targets pointing to loopback, private RFC 1918, or metadata IPs are blocked immediately with `SEV_BLOCKING`.
6. Cross-domain transitions are tracked: safe public redirects across different domains are marked `ACCESS_REDIRECTED` with informational or warning diagnostics rather than fatal failures.

### DNS Rebinding & TOCTOU Mitigations

To mitigate time-of-check to time-of-use (TOCTOU) DNS rebinding attacks between `socket.getaddrinfo()` and the HTTP client:
1. **Multi-Address Resolution Check:** `validate_url_security()` evaluates all address tuples returned by `socket.getaddrinfo()`. If any resolved IP belongs to a prohibited or private range, the URL is rejected immediately.
2. **Post-Connect Socket Peer Verification:** When using real network transports, HowlWriter mounts `SSRFSafeTransport` backed by `SSRFSafeSyncBackend`. Upon socket connection, `sock.getpeername()[0]` is inspected. If the OS-connected peer IP is in a prohibited range, the socket is closed immediately and `SSRFSecurityError` is raised before any TLS negotiation or HTTP data transmission occurs.
3. **Environment Proxy Isolation:** Probes enforce `trust_env=False` on HTTP clients to prevent ambient proxy settings from redirecting traffic away from socket-level verification.

#### Known Limitations
- If a user explicitly configures a custom forward HTTP proxy, TCP connections terminate at the proxy host rather than the target server. Peer validation then verifies the proxy's IP address rather than the remote origin.
- External OS-level or intermediate DNS cache poisoning outside HowlWriter's process boundary cannot be cryptographically prevented without DNSSEC validation in the operating system resolver.

---

## 3. Operational Reachability & Bounded Retrieval

`SourceIntegrityVerifier` executes bounded, non-destructive HTTP probes:
- **HTTP Methods:** Probes initially with `HEAD` (with standard research client headers); falls back to a bounded streaming `GET` if `HEAD` returns 405 Method Not Allowed or 403 Forbidden.
- **Bounded Inspection (`MAX_INSPECT_BYTES`):** HTML body streaming is strictly capped at `1 MiB` (`1024 * 1024` bytes). The stream terminates as soon as the closing `</title>` tag is encountered or the inspection limit is reached, protecting against memory exhaustion or decompression bombs.
- **Content-Type Awareness:**
  - `text/html` / `application/xhtml+xml`: Inspected within bounded streaming limits for `<title>` tags and metadata.
  - `application/pdf`, `application/octet-stream`, `image/*`, `video/*`, `audio/*`, archive formats: Bodies are **not** downloaded. Reachability (HTTP 200) is confirmed, and metadata status is honestly reported as `METADATA_UNKNOWN`.
- **Granular Timeouts:** Uses structured `httpx.Timeout` with distinct connect (max 5.0s), read (configured timeout), write (5.0s), and pool (5.0s) bounds, producing typed diagnostics for connection vs. read timeouts.
- **Status Codes:**
  - `200 OK`: Valid and reachable (`ACCESS_VALID`).
  - `301 / 302 / 303 / 307 / 308`: Redirected, tracked per hop.
  - `404 Not Found / 410 Gone`: Dead source link (`ACCESS_BROKEN`, `SEV_BLOCKING`).
  - `429 Too Many Requests`: Upstream rate limit (`ACCESS_UNKNOWN`, `SEV_WARNING`).
  - `5xx Server Errors`: Remote service outage (`ACCESS_UNKNOWN` or `ACCESS_BROKEN`, `SEV_WARNING`).
- **Identifier Completeness:** Sources lacking both a URL and a DOI/identifier are flagged as unlocatable (`ACCESS_UNKNOWN`, `METADATA_UNKNOWN`, `SEV_WARNING`).

---

## 4. Crossref DOI Verification & Hybrid Title Matching

When a source specifies a DOI (Digital Object Identifier), HowlWriter queries the official Crossref REST API (`https://api.crossref.org/works/{doi}`):
1. **Identifier Normalization:** Supports standard `10.xxxx/...` formats, URL prefixes (`https://doi.org/`, `http://doi.org/`, `https://dx.doi.org/`), `doi:` / `DOI:` prefixes, and cleans trailing punctuation.
2. **Registrar Status Discrimination:**
   - `HTTP 200`: Registered DOI. Work metadata is parsed.
   - `HTTP 404`: Unregistered DOI. Marked `ACCESS_BROKEN`, `METADATA_MISMATCH`, and `SEV_BLOCKING` (likely fabricated citation).
   - `HTTP 429`: Registrar rate limit. Marked `ACCESS_UNKNOWN`, `SEV_WARNING` (temporary capacity constraint, not fabrication).
   - `HTTP 5xx`: Registrar outage. Marked `ACCESS_UNKNOWN`, `SEV_WARNING`.
   - Missing Title in Record: If the registrar returns a 200 with an empty title array, marked `ACCESS_VALID`, `METADATA_UNKNOWN`, `SEV_WARNING`.
3. **Hybrid Normalized Title Similarity:**
   Title matching uses a multi-stage hybrid metric rather than pure Levenshtein or unnormalized tokens:
   - **Normalization:** Unescapes HTML entities, applies Unicode NFKC normalization, removes common journal/platform noise suffixes (` | Nature`, ` - ScienceDirect`, ` - SpringerLink`, ` | IEEE Xplore`, ` - arXiv`, etc.), removes punctuation, case-folds, and collapses whitespace.
   - **Hybrid Metric:** Computes the maximum of `difflib.SequenceMatcher.ratio()`, token Jaccard similarity, containment heuristic for subtitles, and main-title ratio before colons/dashes.
   - **Calibrated Thresholds:**
     - High match (`>= 0.65` or strong subtitle containment): `METADATA_MATCH` (`SEV_PASS`).
     - Partial match (`>= 0.35`): `METADATA_PARTIAL` (`SEV_WARNING`).
     - Severe mismatch (`< 0.35`): `METADATA_MISMATCH` (`SEV_BLOCKING`).

---

## 5. Source Authority Model

HowlWriter classifies sources according to an explicit semantic authority hierarchy (`SourceAuthority`):

```python
class SourceAuthority(str, enum.Enum):
    PRIMARY_LAW = "PRIMARY_LAW"          # Statutes, treaties, EU regulations (EUR-Lex, Congress.gov)
    GOVERNMENT = "GOVERNMENT"            # Regulatory agencies, official advisories (FTC, CISA, ENISA)
    STANDARD = "STANDARD"                # Standards organizations (NIST, ISO, IEEE, RFC)
    SCHOLARLY = "SCHOLARLY"              # Peer-reviewed journals, arXiv preprints, academic books
    VENDOR_PRIMARY = "VENDOR_PRIMARY"    # Official vendor documentation, CVE entries, advisories
    INDUSTRY = "INDUSTRY"                # Industry whitepapers, trade publications
    NEWS = "NEWS"                        # Reputable news outlets
    SECONDARY = "SECONDARY"              # Commentaries, tertiary analysis, industry blogs
    COMMUNITY = "COMMUNITY"              # Unverified blogs, forums, user discussions
    UNKNOWN = "UNKNOWN"
```

### Context-Sensitive Topic Prioritization

Assignments often demand distinct tiers of authority depending on subject matter:
- **Legal & Regulatory Topics:** Prioritizes `PRIMARY_LAW` and `GOVERNMENT` (e.g., GDPR, HIPAA).
- **Security & Compliance Topics:** Prioritizes `STANDARD` and `GOVERNMENT` (e.g., NIST CSF, CISA BOD).
- **Academic & Scientific Topics:** Prioritizes `SCHOLARLY` (peer-reviewed articles).
- **Software & Cloud Topics:** Accepts `VENDOR_PRIMARY` (official developer documentation).

The classifier detects topic requirements via `detect_topic_preferred_authorities()` and flags when an assignment lacks appropriate primary grounding.

---

## 6. CLI & Academic Pipeline Integration

### CLI Command: `howlwriter sources verify`

```bash
# Verify a standalone sources JSON file
howlwriter sources verify sources.json

# Sample Output:
# [S001] (PRIMARY_LAW) EU GDPR 2016/679 -> VALID (HTTP 200)
# [S002] (STANDARD) NIST CSF 2.0 -> REDIRECTED (HTTP 200 -> csrc.nist.gov)
# [S003] (SCHOLARLY) 10.1016/j.clsr.2020.105454 -> VALID (DOI Crossref Verified)
# Status: READY (0 blocking errors, 0 warnings)
```

### Integration in `howlwriter paper`

When running academic papers, passing `--verify-sources` automatically gates the pipeline:

```bash
howlwriter paper assignment.yaml --verify-sources --format md docx pdf
```

If unreachable sources or SSRF violations are detected:
- The run record documents the exact findings.
- The pipeline status is marked as `BLOCKED`.
- Local artifacts are generated with warning metadata, while automated cloud publication is denied by the human authority boundary.
