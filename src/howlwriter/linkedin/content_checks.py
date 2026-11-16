"""Deterministic content checks run before and alongside HowlProof.

Every check here is a fixed rule over bytes and text. None of them uses a
model, and none of them decides whether a statement is true. Each check names
what it does not establish, and a check that did not run is reported as
``NOT_EXECUTED`` or ``ERROR``, never as passed.

These checks cover what HowlProof 0.2.0b1 has no evaluator for (see
``docs/linkedin-publisher/DECISIONS.md`` D13): LinkedIn formatting, broken
Unicode, link consistency, duplicates inside this queue, privacy patterns in
the post text, image container checks, and whether each quantitative
statement is covered by a declared claim.
"""

from __future__ import annotations

import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from howlwriter.linkedin.checks import ERROR, INFO, WARNING, CheckFinding, check_post
from howlwriter.linkedin.config import PublisherConfig
from howlwriter.linkedin.models import LifecycleState, Post
from howlwriter.linkedin.store import QueueStore, StoreError

PASSED = "PASSED"
FAILED = "FAILED"
NOT_EXECUTED = "NOT_EXECUTED"
NOT_APPLICABLE = "NOT_APPLICABLE"
CHECK_ERROR = "ERROR"
CHECK_STATUSES = (PASSED, FAILED, NOT_EXECUTED, NOT_APPLICABLE, CHECK_ERROR)

DETERMINISTIC = "deterministic"

#: Findings from the M1 pre-review checks that describe workflow state, not content.
_STATE_CODES = frozenset({"VERIFICATION_ABSENT", "VERIFICATION_STALE", "APPROVAL_STALE"})


@dataclass(frozen=True)
class CheckRecord:
    """One executed (or explicitly not executed) check and what it found."""

    id: str
    status: str
    summary: str
    limitation: str
    findings: tuple[CheckFinding, ...] = ()
    reason: str = ""
    method: str = DETERMINISTIC

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "status": self.status,
            "summary": self.summary,
            "limitation": self.limitation,
            "reason": self.reason,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _record(check_id: str, findings: list[CheckFinding], passed: str, limitation: str) -> CheckRecord:
    errors = sum(1 for finding in findings if finding.severity == ERROR)
    warnings = sum(1 for finding in findings if finding.severity == WARNING)
    if errors:
        return CheckRecord(
            check_id, FAILED, f"{errors} blocking finding(s), {warnings} warning(s)", limitation, tuple(
                findings,
            )
        )
    summary = passed if not warnings else f"{passed}; {warnings} warning(s) to review"
    return CheckRecord(check_id, PASSED, summary, limitation, tuple(findings))


def not_executed(check_id: str, reason: str) -> CheckRecord:
    return CheckRecord(
        check_id,
        NOT_EXECUTED,
        "the check was not run",
        "nothing about this surface was established",
        reason=reason,
    )


def not_applicable(check_id: str, reason: str) -> CheckRecord:
    return CheckRecord(
        check_id,
        NOT_APPLICABLE,
        "the post has no such surface",
        "absence of a surface says nothing about other surfaces",
        reason=reason,
    )


# Formatting (reuses the M1 checks and the existing HowlWriter LinkedIn linter)


def check_format(post: Post, config: PublisherConfig, store: QueueStore) -> CheckRecord:
    findings = [finding for finding in check_post(post, config, store) if finding.code not in _STATE_CODES]
    return _record(
        "content.format",
        findings,
        "length, formatting, link syntax, media bytes and schedule are consistent",
        "the length limit comes from the HowlWriter linter and was not re-verified against LinkedIn; "
        "it does not judge the quality or truth of the text",
    )


# Unicode

_MOJIBAKE = re.compile(r"Ã[\x80-\xbf©¨ª«¢¤¶¼±³]|â€[™œ\x9d“”˜¦]|â€”|â€“|Â[ \xa0©®°]|ï¿½")
_BIDI_CONTROLS = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
_INVISIBLE = frozenset("​⁠﻿­")


def check_unicode(post: Post) -> CheckRecord:
    findings: list[CheckFinding] = []
    surfaces = [("text", post.text)] + [(f"alt text of {m.path}", m.alt_text) for m in post.media]
    for label, value in surfaces:
        if "�" in value:
            findings.append(
                CheckFinding(
                    "UNICODE_REPLACEMENT",
                    ERROR,
                    f"{label} contains the replacement character U+FFFD",
                )
            )
        match = _MOJIBAKE.search(value)
        if match:
            findings.append(
                CheckFinding(
                    "UNICODE_MOJIBAKE",
                    ERROR,
                    f"{label} contains a wrongly decoded sequence near "
                    f"{value[match.start():match.start() + 12]!r}",
                )
            )
        if any(char in _BIDI_CONTROLS for char in value):
            findings.append(
                CheckFinding(
                    "UNICODE_BIDI_CONTROL",
                    ERROR,
                    f"{label} contains a bidirectional control character that can hide or reorder text",
                )
            )
        if any(char in _INVISIBLE for char in value):
            findings.append(
                CheckFinding("UNICODE_INVISIBLE", WARNING, f"{label} contains an invisible character")
            )
        if any(unicodedata.category(char) in ("Co", "Cn") for char in value):
            findings.append(
                CheckFinding(
                    "UNICODE_UNASSIGNED",
                    WARNING,
                    f"{label} contains a private use or unassigned character that may not render",
                )
            )
        if unicodedata.normalize("NFC", value) != value:
            findings.append(
                CheckFinding(
                    "UNICODE_NOT_NFC",
                    WARNING,
                    f"{label} is not in composed (NFC) form and may render unevenly",
                )
            )
    return _record(
        "content.unicode",
        findings,
        "no broken or hidden characters found",
        "it cannot tell whether a correctly encoded character renders on every LinkedIn client",
    )


# Links

_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?"
_SHORTENER_HOSTS = frozenset(
    {"bit.ly", "t.co", "tinyurl.com", "lnkd.in", "goo.gl", "ow.ly", "buff.ly", "is.gd", "rebrand.ly", "t.ly"}
)
_IP_HOST = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|\[.*\])$")


def urls_in_text(text: str) -> list[str]:
    found: list[str] = []
    for match in _URL_IN_TEXT.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if url not in found:
            found.append(url)
    return found


def check_links(post: Post) -> CheckRecord:
    if not post.urls and not urls_in_text(post.text):
        return not_applicable("content.links", "the post has no links")
    findings: list[CheckFinding] = []
    declared = set(post.urls)
    for url in urls_in_text(post.text):
        if url.lower().startswith("http://"):
            findings.append(CheckFinding("LINK_NOT_HTTPS", ERROR, f"link in the text is not https: {url}"))
        elif url not in declared:
            findings.append(
                CheckFinding(
                    "LINK_UNDECLARED",
                    ERROR,
                    "link appears in the text but is not listed in the post's urls, so it was never "
                    f"checked: {url}",
                )
            )
    if len(declared) != len(post.urls):
        findings.append(CheckFinding("LINK_DUPLICATE", WARNING, "the same link is listed more than once"))
    for url in post.urls:
        host = (urlsplit(url).hostname or "").lower()
        if _IP_HOST.match(host) or host == "localhost":
            findings.append(
                CheckFinding(
                    "LINK_HOST_NOT_PUBLIC_NAME",
                    ERROR,
                    f"link points at an address, not a public name: {url}",
                )
            )
        elif host in _SHORTENER_HOSTS:
            findings.append(
                CheckFinding(
                    "LINK_SHORTENER",
                    WARNING,
                    f"shortened link hides its destination; use the final address: {url}",
                )
            )
        elif "xn--" in host:
            findings.append(
                CheckFinding(
                    "LINK_PUNYCODE", WARNING, f"link host uses punycode and may imitate another name: {url}"
                )
            )
    return _record(
        "content.links",
        findings,
        "links in the text and the declared link list agree",
        "syntax and consistency only; it does not contact any link or read any page",
    )


# Duplicates

_WORD = re.compile(r"[\w']+", re.UNICODE)
NEAR_DUPLICATE_THRESHOLD = 0.8
_SHINGLE = 3
_HISTORY_STATES = frozenset({LifecycleState.PUBLISHED, LifecycleState.UNCERTAIN, LifecycleState.PUBLISHING})


def _normalized(text: str) -> str:
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def _shingles(normalized: str) -> frozenset[tuple[str, ...]]:
    words = normalized.split()
    if len(words) < _SHINGLE:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(tuple(words[i:i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1))


def similarity(left: str, right: str) -> float:
    a, b = _shingles(_normalized(left)), _shingles(_normalized(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def check_duplicates(post: Post, others: Iterable[Post]) -> CheckRecord:
    findings: list[CheckFinding] = []
    mine = _normalized(post.text)
    compared = 0
    for other in others:
        if other.id == post.id:
            continue
        was_sent = other.state in _HISTORY_STATES or other.linkedin_post_id is not None
        if other.state is LifecycleState.ARCHIVED and not was_sent:
            continue
        compared += 1
        where = "already published" if was_sent else f"in the queue ({other.state.value})"
        if mine and _normalized(other.text) == mine:
            findings.append(
                CheckFinding("DUPLICATE_EXACT", ERROR, f"same text as post {other.id}, which is {where}")
            )
            continue
        score = similarity(post.text, other.text)
        if score >= NEAR_DUPLICATE_THRESHOLD:
            findings.append(
                CheckFinding(
                    "DUPLICATE_NEAR",
                    WARNING,
                    f"{score:.0%} of three word sequences are shared with post {other.id}, which is {where}",
                )
            )
    return _record(
        "content.duplicates",
        findings,
        f"no duplicate among {compared} other post(s) in this repository",
        "compares only against posts stored in this repository; it cannot see posts made on LinkedIn by hand "
        "or reworded text that says the same thing",
    )


# Privacy

_PRIVATE_IPV4 = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|127\.\d{1,3}|169\.254)"
    r"\.\d{1,3}\.\d{1,3}(?!\d|\.\d)"
)
_INTERNAL_HOST = re.compile(
    r"(?<![\w.-])(?:localhost|[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*"
    r"\.(?:local|internal|intranet|corp|lan|home\.arpa))"
    r"(?![\w-])",
    re.IGNORECASE,
)
_PRIVATE_PATH = re.compile(
    r"(?<![\w.])(?:/home/[^\s/]+|/Users/[^\s/]+|/root\b|/run/media/[^\s/]+|/mnt/[^\s/]+|/var/lib/[^\s/]+"
    r"|[A-Za-z]:\\Users\\[^\s\\]+|~/[^\s]+)"
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w.])\+?\d{1,3}[ .-]?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
_CONFIDENTIAL = re.compile(
    r"\b(?:confidential|internal[ -]only|internal use only|do not (?:distribute|share|forward)|proprietary"
    r"|under nda|not for (?:public )?(?:release|distribution)|embargoed)\b",
    re.IGNORECASE,
)

_PRIVACY_RULES: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    ("PRIVACY_PRIVATE_ADDRESS", _PRIVATE_IPV4, ERROR, "private or loopback network address"),
    ("PRIVACY_INTERNAL_HOSTNAME", _INTERNAL_HOST, ERROR, "internal hostname"),
    ("PRIVACY_PRIVATE_PATH", _PRIVATE_PATH, ERROR, "local file system path"),
    ("PRIVACY_CONFIDENTIAL_MARKER", _CONFIDENTIAL, ERROR, "confidentiality marker"),
    ("PRIVACY_EMAIL_ADDRESS", _EMAIL, WARNING, "email address"),
    ("PRIVACY_PHONE_NUMBER", _PHONE, WARNING, "phone number"),
)


def check_privacy(post: Post) -> CheckRecord:
    findings: list[CheckFinding] = []
    surfaces = [("text", post.text)] + [(f"alt text of {m.path}", m.alt_text) for m in post.media]
    for label, value in surfaces:
        for code, pattern, severity, name in _PRIVACY_RULES:
            seen: list[str] = []
            # A path inside a public web address is not a local path; links have their own check.
            scanned = _URL_IN_TEXT.sub(" ", value) if code == "PRIVACY_PRIVATE_PATH" else value
            for match in pattern.finditer(scanned):
                if match.group(0) not in seen:
                    seen.append(match.group(0))
            if seen:
                shown = ", ".join(repr(item[:60]) for item in seen[:3])
                findings.append(CheckFinding(code, severity, f"{name} in the {label}: {shown}"))
    return _record(
        "privacy.patterns",
        findings,
        "no private address, internal hostname, local path or confidentiality marker found",
        "fixed patterns over the post text and alt text; it cannot recognise confidential material that "
        "carries no marker, names of people or customers, or anything visible inside an image. "
        "Credential formats are checked separately by HowlProof secrets.scan",
    )


# Images

MIN_IMAGE_EDGE = 200
MAX_IMAGE_PIXELS = 40_000_000
_SOF_MARKERS = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
_EMPTY_ALT_WORDS = frozenset({"image", "picture", "photo", "screenshot", "chart", "graph"})
_FORMAT_SUFFIXES = {"png": (".png",), "jpeg": (".jpg", ".jpeg"), "gif": (".gif",)}


def image_info(data: bytes) -> tuple[str, int, int] | None:
    """Return (format, width, height) read from the container header, or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "gif", width, height
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 <= len(data):
            if data[offset] != 0xFF:
                return None
            marker = data[offset + 1]
            if marker == 0xFF:
                offset += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                offset += 2
                continue
            if marker in (0xD9, 0xDA):
                return None
            (length,) = struct.unpack(">H", data[offset + 2:offset + 4])
            if length < 2:
                return None
            if marker in _SOF_MARKERS:
                height, width = struct.unpack(">HH", data[offset + 5:offset + 9])
                return "jpeg", width, height
            offset += 2 + length
    return None


def check_images(post: Post, store: QueueStore) -> tuple[CheckRecord, list[dict[str, Any]]]:
    """Check each image container. Returns the record and the observed media facts."""
    if not post.media:
        return not_applicable("media.images", "the post has no image"), []
    findings: list[CheckFinding] = []
    observed: list[dict[str, Any]] = []
    for media in post.media:
        entry: dict[str, Any] = {"path": media.path, "sha256": media.sha256}
        observed.append(entry)
        try:
            data = store.media_file(media.path).read_bytes()
        except (OSError, StoreError) as error:
            findings.append(
                CheckFinding(
                    "MEDIA_UNREADABLE",
                    ERROR,
                    f"{media.path} could not be read ({type(error).__name__})",
                )
            )
            continue
        entry["bytes"] = len(data)
        info = image_info(data)
        if info is None:
            findings.append(
                CheckFinding(
                    "MEDIA_FORMAT_UNSUPPORTED",
                    ERROR,
                    f"{media.path} is not a readable PNG, JPEG or GIF image",
                )
            )
            continue
        kind, width, height = info
        entry.update(format=kind, width=width, height=height)
        if not media.path.lower().endswith(_FORMAT_SUFFIXES[kind]):
            findings.append(
                CheckFinding(
                    "MEDIA_EXTENSION_MISMATCH",
                    ERROR,
                    f"{media.path} holds {kind.upper()} data under another extension",
                )
            )
        if width == 0 or height == 0 or width * height > MAX_IMAGE_PIXELS:
            findings.append(
                CheckFinding(
                    "MEDIA_DIMENSIONS_INVALID",
                    ERROR,
                    f"{media.path} reports {width}x{height} pixels",
                )
            )
        elif min(width, height) < MIN_IMAGE_EDGE:
            findings.append(
                CheckFinding(
                    "MEDIA_SMALL",
                    WARNING,
                    f"{media.path} is only {width}x{height} pixels and may look blurred",
                )
            )
        alt = media.alt_text.strip()
        if not alt:
            findings.append(CheckFinding("ALT_TEXT_MISSING", ERROR, f"{media.path} has no alt text"))
        elif alt.lower() in _EMPTY_ALT_WORDS or alt.lower() == Path(media.path).name.lower():
            findings.append(
                CheckFinding(
                    "ALT_TEXT_UNINFORMATIVE",
                    WARNING,
                    f"alt text of {media.path} does not describe the image",
                )
            )
        findings.append(
            CheckFinding(
                "IMAGE_CONTENT_UNVERIFIED",
                WARNING,
                f"what {media.path} shows was not examined; a person must confirm any chart, screenshot or "
                "figure in it is accurate and safe to publish",
            )
        )
    record = _record(
        "media.images",
        findings,
        "image container, size, extension and alt text are consistent",
        "container header and alt text presence only. No visual verification capability exists here: the "
        "picture itself, its source and any numbers or text inside it were not checked. Minimum sizes are "
        "a readability heuristic, not a verified LinkedIn rule",
    )
    return record, observed


# Quantitative statements and declared claims

_NUMBER = re.compile(
    r"(?P<currency>[$€£])?(?P<number>\d[\d,]*(?:\.\d+)?)\s?"
    r"(?P<unit>%|percent\b|x\b|k\b|m\b|bn\b|million\b|billion\b|thousand\b|ms\b|seconds?\b|minutes?\b"
    r"|hours?\b"
    r"|days?\b|weeks?\b|months?\b|years?\b|gb\b|mb\b|tb\b)?",
    re.IGNORECASE,
)
_LIST_MARKER = re.compile(r"^\s*\d{1,2}[.)]\s", re.MULTILINE)


def quantitative_statements(text: str) -> list[dict[str, Any]]:
    """Numbers in the post text, with URLs and list markers removed first."""
    stripped = _URL_IN_TEXT.sub(" ", text)
    stripped = _LIST_MARKER.sub(" ", stripped)
    found: list[dict[str, Any]] = []
    for match in _NUMBER.finditer(stripped):
        before = stripped[match.start() - 1] if match.start() > 0 else " "
        if before.isalnum() or before in "#@_":
            continue
        number = match.group("number").replace(",", "").rstrip(".")
        measured = bool(match.group("currency") or match.group("unit"))
        token = match.group(0).strip()
        if not any(item["token"] == token for item in found):
            found.append({"token": token, "number": number, "measured": measured})
    return found


def _claim_numbers(claim_texts: Iterable[str]) -> set[str]:
    numbers: set[str] = set()
    for text in claim_texts:
        for match in _NUMBER.finditer(text):
            numbers.add(match.group("number").replace(",", "").rstrip("."))
    return numbers


def check_claim_coverage(post: Post, claim_texts: list[str] | None) -> CheckRecord:
    """Every quantitative statement in the post must appear in a declared claim.

    ``claim_texts`` is None when the post has no claim bundle. This check only
    establishes that a claim was declared for each number. Whether the claim is
    supported is decided by HowlProof ``research.claims``, not here.
    """
    statements = quantitative_statements(post.text)
    limitation = (
        "finds numbers only. Statements without a number (comparisons, causes, quotations, superlatives) "
        "are not detected here; no model reads the post. A covered number means a claim was declared for "
        "it, not that the claim is supported"
    )
    if not statements:
        return CheckRecord(
            "claims.coverage", PASSED, "the post text contains no numbers", limitation
        )
    covered = _claim_numbers(claim_texts or [])
    findings: list[CheckFinding] = []
    for item in statements:
        if item["number"] in covered:
            continue
        if item["measured"]:
            findings.append(
                CheckFinding(
                    "CLAIM_UNDECLARED_METRIC",
                    ERROR,
                    f"the post states {item['token']!r} but no declared claim covers it; add a claim with "
                    "evidence or remove the figure",
                )
            )
        else:
            findings.append(
                CheckFinding(
                    "CLAIM_UNDECLARED_NUMBER",
                    WARNING,
                    f"the number {item['token']!r} is not covered by a declared claim; confirm it is not a "
                    "factual statement",
                )
            )
    return _record(
        "claims.coverage",
        findings,
        f"all {len(statements)} quantitative statement(s) are covered by a declared claim",
        limitation,
    )


def run_guarded(check_id: str, run: Callable[[], CheckRecord]) -> CheckRecord:
    """A check that raises is reported as ERROR, which blocks; it is never a silent pass."""
    try:
        return run()
    except Exception as error:  # noqa: BLE001 - a check fault must block, not crash or pass
        return CheckRecord(
            check_id,
            CHECK_ERROR,
            "the check raised before reaching a conclusion",
            "a check fault is not evidence for or against the post",
            reason=type(error).__name__,
        )


__all__ = [
    "CHECK_ERROR",
    "CHECK_STATUSES",
    "CheckRecord",
    "DETERMINISTIC",
    "FAILED",
    "INFO",
    "NOT_APPLICABLE",
    "NOT_EXECUTED",
    "PASSED",
    "check_claim_coverage",
    "check_duplicates",
    "check_format",
    "check_images",
    "check_links",
    "check_privacy",
    "check_unicode",
    "image_info",
    "not_applicable",
    "not_executed",
    "quantitative_statements",
    "run_guarded",
    "similarity",
    "urls_in_text",
]
