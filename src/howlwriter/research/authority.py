"""Semantic source authority classification and context-sensitive research prioritization."""

from __future__ import annotations

import re
import urllib.parse

from howlwriter.domain.source import Source, SourceAuthority, SourceType


# Primary law domains and patterns
_PRIMARY_LAW_DOMAINS = (
    "eur-lex.europa.eu",
    "curia.europa.eu",
    "congress.gov",
    "uscode.house.gov",
    "federalregister.gov",
    "legislation.gov.uk",
    "legifrance.gouv.fr",
)

# Government & regulatory agencies
_GOVERNMENT_DOMAINS = (
    "cisa.gov",
    "ftc.gov",
    "fcc.gov",
    "sec.gov",
    "hhs.gov",
    "justice.gov",
    "enisa.europa.eu",
    "edpb.europa.eu",
    "ico.org.uk",
    "cnil.fr",
)

# Standards bodies
_STANDARD_DOMAINS = (
    "nist.gov",
    "csrc.nist.gov",
    "iso.org",
    "ietf.org",
    "rfc-editor.org",
    "w3.org",
    "standards.ieee.org",
    "oasis-open.org",
)

# Scholarly publishers and repositories
_SCHOLARLY_DOMAINS = (
    "arxiv.org",
    "doi.org",
    "crossref.org",
    "acm.org",
    "ieee.org",
    "sciencedirect.com",
    "springer.com",
    "nature.com",
    "cell.com",
    "ncbi.nlm.nih.gov",
    "semanticscholar.org",
    "jstor.org",
)

# Major primary vendor and CVE technical documentation
_VENDOR_PRIMARY_DOMAINS = (
    "cve.mitre.org",
    "nvd.nist.gov",
    "docs.microsoft.com",
    "learn.microsoft.com",
    "cloud.google.com",
    "docs.aws.amazon.com",
    "developer.apple.com",
    "kubernetes.io/docs",
)

_NEWS_DOMAINS = (
    "reuters.com",
    "bloomberg.com",
    "apnews.com",
    "bbc.com",
    "nytimes.com",
    "wsj.com",
)


def classify_source_authority(source: Source) -> SourceAuthority:
    """Classifies a source's semantic authority using its URL, publisher, type, and title."""
    # 1. URL Domain Inspection
    url = source.url or (f"https://doi.org/{source.doi}" if source.doi else "")
    if url:
        hostname = (urllib.parse.urlparse(url).hostname or "").lower()

        for d in _PRIMARY_LAW_DOMAINS:
            if hostname == d or hostname.endswith(f".{d}"):
                return SourceAuthority.PRIMARY_LAW

        for d in _STANDARD_DOMAINS:
            if hostname == d or hostname.endswith(f".{d}"):
                return SourceAuthority.STANDARD

        for d in _GOVERNMENT_DOMAINS:
            if hostname == d or hostname.endswith(f".{d}"):
                return SourceAuthority.GOVERNMENT

        if hostname.endswith(".gov") or hostname.endswith(".mil"):
            return SourceAuthority.GOVERNMENT

        for d in _SCHOLARLY_DOMAINS:
            if hostname == d or hostname.endswith(f".{d}"):
                return SourceAuthority.SCHOLARLY

        for d in _VENDOR_PRIMARY_DOMAINS:
            if hostname == d or hostname.endswith(f".{d}"):
                return SourceAuthority.VENDOR_PRIMARY

        for d in _NEWS_DOMAINS:
            if hostname == d or hostname.endswith(f".{d}"):
                return SourceAuthority.NEWS

    # 2. Scholarly DOI check
    if source.doi:
        return SourceAuthority.SCHOLARLY

    # 3. Publisher and SourceType Inspection
    pub = (source.publisher or "").lower()
    if any(k in pub for k in ("nist", "national institute of standards", "iso", "ieee standard")):
        return SourceAuthority.STANDARD
    if any(
        k in pub
        for k in (
            "european parliament",
            "european commission",
            "council of the european union",
            "us congress",
        )
    ):
        return SourceAuthority.PRIMARY_LAW
    if any(k in pub for k in ("department of", "ministry of", "agency", "federal trade commission", "cisa")):
        return SourceAuthority.GOVERNMENT

    if source.source_type == SourceType.JOURNAL_ARTICLE:
        return SourceAuthority.SCHOLARLY

    if source.source_type == SourceType.NEWS_ARTICLE:
        return SourceAuthority.NEWS

    if source.source_type == SourceType.REPORT:
        return SourceAuthority.INDUSTRY

    if source.source_type == SourceType.BOOK:
        return SourceAuthority.SECONDARY

    return SourceAuthority.UNKNOWN


# Keywords suggesting required primary legal or regulatory grounding
_LAW_KEYWORDS = re.compile(
    r"\b(gdpr|ccpa|cpra|hipaa|ferpa|dora|nis2|cyber resilience act|"
    r"statute|regulation|directive|fine|penalt|compliance mandate)\b",
    re.IGNORECASE,
)

# Keywords suggesting standards grounding
_STANDARD_KEYWORDS = re.compile(
    r"\b(nist|csf|sp 800-\d+|iso/iec 2700\d|fips|cis controls|zero trust architecture|rfc \d+)\b",
    re.IGNORECASE,
)


def detect_topic_preferred_authorities(text: str) -> list[SourceAuthority]:
    """Detects which source authority tiers are required or preferred for a topic."""
    authorities: list[SourceAuthority] = []

    if _LAW_KEYWORDS.search(text):
        authorities.extend([SourceAuthority.PRIMARY_LAW, SourceAuthority.GOVERNMENT])

    if _STANDARD_KEYWORDS.search(text):
        authorities.append(SourceAuthority.STANDARD)

    # Academic papers always benefit from scholarly sources
    authorities.append(SourceAuthority.SCHOLARLY)

    # De-duplicate while preserving priority order
    seen = set()
    result = []
    for a in authorities:
        if a not in seen:
            seen.add(a)
            result.append(a)
    return result
