"""Deterministic pre-review checks for one post.

These are structural and formatting checks only. They say nothing about
whether the post is true: factual verification belongs to HowlProof and
authorization belongs to the approval boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

from howlwriter.linkedin.config import PublisherConfig
from howlwriter.linkedin.models import LifecycleState, Post
from howlwriter.linkedin.scheduler import schedule_problems
from howlwriter.linkedin.store import QueueStore, StoreError
from howlwriter.linting.platforms import check_linkedin_conformance

ERROR = "error"
WARNING = "warning"
INFO = "info"

MAX_MEDIA_BYTES = 8 * 1024 * 1024
_HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class CheckFinding:
    code: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


def has_errors(findings: list[CheckFinding]) -> bool:
    return any(finding.severity == ERROR for finding in findings)


def _file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_post(post: Post, config: PublisherConfig, store: QueueStore) -> list[CheckFinding]:
    """Run every deterministic check. Errors block submission for review."""
    findings: list[CheckFinding] = []

    # LinkedIn length, control characters and unrendered Markdown: the existing platform linter.
    for match in check_linkedin_conformance(post.text):
        findings.append(CheckFinding(match.rule_code, match.severity, match.message))

    for url in post.urls:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            findings.append(
                CheckFinding("URL_INVALID", ERROR, f"not a plain https URL (no credentials allowed): {url}")
            )
        elif url not in post.text:
            findings.append(
                CheckFinding(
                    "URL_NOT_IN_TEXT", WARNING, f"listed link does not appear in the post text: {url}"
                )
            )

    for media in post.media:
        try:
            path = store.media_file(media.path)
        except StoreError as error:
            findings.append(CheckFinding("MEDIA_PATH_UNSAFE", ERROR, str(error)))
            continue
        if not path.is_file():
            findings.append(CheckFinding("MEDIA_MISSING", ERROR, f"media file not found: {media.path}"))
            continue
        if path.stat().st_size > MAX_MEDIA_BYTES:
            findings.append(
                CheckFinding(
                    "MEDIA_TOO_LARGE", ERROR, f"media file exceeds {MAX_MEDIA_BYTES} bytes: {media.path}"
                )
            )
            continue
        if _file_sha256(path) != media.sha256:
            findings.append(
                CheckFinding(
                    "MEDIA_CHANGED",
                    ERROR,
                    f"media bytes no longer match the recorded SHA-256: {media.path}",
                )
            )

    if not post.fingerprint_is_current:
        findings.append(
            CheckFinding(
                "FINGERPRINT_STALE",
                ERROR,
                "stored content fingerprint does not match the content; the file was edited outside the tool",
            )
        )
    for problem in schedule_problems(post, config):
        findings.append(CheckFinding("SCHEDULE_UNSUPPORTED", ERROR, problem))
    if post.approval_ref is not None and not post.approval_is_current:
        findings.append(
            CheckFinding("APPROVAL_STALE", ERROR, "the recorded approval was given for different content")
        )
    if post.verification_ref is not None and not post.verification_is_current:
        findings.append(
            CheckFinding(
                "VERIFICATION_STALE", ERROR, "the verification report was made for different content"
            )
        )
    if (
        post.state in (LifecycleState.DRAFT, LifecycleState.READY_FOR_REVIEW)
        and post.verification_ref is None
    ):
        findings.append(CheckFinding("VERIFICATION_ABSENT", INFO, "no verification report is attached yet"))
    return findings
