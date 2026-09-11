# Source Integrity, SSRF Defense & Authority Verification

HowlWriter treats source verification and citation integrity as first-class, verifiable boundaries. It enforces a strict separation between **operational source integrity** (reachability, format validity, SSRF defense, DOI registry status) and **semantic claim relevance** (whether evidence substantiates a specific factual assertion).

---

## 1. Core Principles

1. **Orthogonality:** A source may be completely reachable, valid, and registered (operational pass), yet provide zero substantive support for a draft's claims. Conversely, a relevant quotation from an unreachable website remains unverified. The pipeline reports both dimensions independently.
2. **Strict SSRF Defenses:** Automated source verification must never be used as a vector for Server-Side Request Forgery against local infrastructure, intranet services, or cloud instance metadata endpoints.
3. **Semantic Authority Hierarchy:** Sources are classified by legal, regulatory, scholarly, or industry authority, allowing assignments to require primary-law or standard-level grounding where needed.

---

## 2. SSRF Protection Architecture

The SSRF validator (`howlwriter.research.integrity::validate_url_security`) inspects every candidate URL before any network socket is opened.

### Blocked Ranges & Patterns

| Target Type | Blocked Range / Host | Purpose |
| --- | --- | --- |
| **IPv4 Loopback** | `127.0.0.0/8`, `localhost` | Prevents scanning local background services and databases. |
| **IPv6 Loopback** | `::1` | Prevents IPv6 localhost attacks. |
| **Private Networks (RFC 1918)** | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | Blocks access to internal corporate subnets and dev clusters. |
| **Cloud Instance Metadata** | `169.254.169.254`, `metadata.google.internal` | Prevents exfiltration of cloud IAM credentials or instance tokens. |
| **Link-Local & Multicast** | `169.254.0.0/16`, `224.0.0.0/4`, `fe80::/10` | Disallows non-routable link and multicast addresses. |
| **Non-HTTP Schemes** | `file://`, `ftp://`, `gopher://`, `data://` | Enforces explicit HTTP/HTTPS scheme restrictions. |

### DNS Resolution Verification

`validate_url_security()` performs upfront DNS resolution using `socket.getaddrinfo()` to verify that hostnames do not resolve to private or loopback IPs (guarding against DNS rebinding attacks).

---

## 3. Operational Reachability & Integrity Verification

`SourceIntegrityVerifier` executes non-destructive HTTP probes to confirm availability:
- **HTTP Methods:** Probes initially with `HEAD` (with standard browser user-agent headers); falls back to a ranged or minimal `GET` if `HEAD` returns 405 Method Not Allowed.
- **Status Codes:**
  - `200 OK`: Valid and reachable (`IntegrityStatus.VALID`).
  - `301 / 302 / 307 / 308`: Redirected. The target URL is re-validated through SSRF checks before following.
  - `404 Not Found / 410 Gone`: Dead source link (`IntegrityStatus.NOT_FOUND`).
  - `5xx Server Errors / Connection Timeouts`: Marked as unreachable or errored.
- **Identifier Completeness:** Sources lacking both a URL and a DOI/identifier are flagged as unlocatable (`IntegrityStatus.MISSING_IDENTIFIER`).

---

## 4. Crossref DOI Verification

When a source specifies a DOI (Digital Object Identifier), HowlWriter queries the official Crossref REST API (`https://api.crossref.org/works/{doi}`):
1. **Identifier Normalization:** Strips prefixes such as `https://doi.org/` or `doi:`.
2. **Registry Existence Check:** Verifies that the DOI is officially registered with Crossref.
3. **Metadata Title Similarity:** Computes normalized Levenshtein similarity between the user's cited title and the registered Crossref metadata title.
   - Exact or close matches (> 0.70 similarity): Verified.
   - Significant discrepancies: Flagged with a `DOI_METADATA_MISMATCH` warning to prevent hallucinated citations or DOI misappropriation.

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
# [S002] (STANDARD) NIST CSF 2.0 -> REDIRECTED (HTTP 301 -> csrc.nist.gov)
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
