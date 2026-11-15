"""Versioned LinkedIn post record, lifecycle states, and canonical content fingerprint.

A post is one JSON document in the private publishing repository. Parsing is
strict: unknown keys, wrong types, and inconsistent lifecycle data are all
rejected with every problem listed, so a hand edited or corrupted file can
never be mistaken for a publishable post.

The JSON Schema in ``howlwriter/schemas/howlwriter.linkedin_post.v1.schema.json``
describes the same structure for other tools. This module is the authority at
run time and is at least as strict as that schema (tests hold the two together).
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

POST_SCHEMA = "howlwriter.linkedin_post/v1"
CONTENT_SCHEMA = "howlwriter.linkedin_post_content/v1"

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TIMESTAMP_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
URL_PATTERN = re.compile(r"^https://[^\s/?#]+[^\s]*$")
MEDIA_PATH_PATTERN = re.compile(r"^media/[A-Za-z0-9._/-]+$")
ARTIFACT_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")

# Resource bounds for stored records. These are storage limits, not LinkedIn
# limits; LinkedIn formatting rules are applied by the content checks.
MAX_TITLE_CHARS = 200
MAX_TEXT_CHARS = 20000
MAX_URLS = 20
MAX_URL_CHARS = 2000
MAX_MEDIA = 1
MAX_ALT_TEXT_CHARS = 4000
MAX_DETAIL_CHARS = 2000
MAX_EXTERNAL_ID_CHARS = 200


class PostValidationError(ValueError):
    """A post document is malformed. ``problems`` lists every defect found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("invalid post: " + "; ".join(self.problems))


class IllegalTransitionError(ValueError):
    """The requested lifecycle change is not permitted."""


class LifecycleState(str, enum.Enum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    ARCHIVED = "ARCHIVED"


S = LifecycleState

#: Every permitted lifecycle change. Anything absent is refused.
#: UNCERTAIN leaves only through human reconciliation, and ARCHIVED is terminal,
#: so an archived record of a published post can never re-enter the queue.
ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    S.DRAFT: frozenset({S.READY_FOR_REVIEW, S.ARCHIVED}),
    S.READY_FOR_REVIEW: frozenset({S.DRAFT, S.APPROVED, S.ARCHIVED}),
    S.APPROVED: frozenset({S.DRAFT, S.SCHEDULED, S.ARCHIVED}),
    S.SCHEDULED: frozenset({S.DRAFT, S.APPROVED, S.PUBLISHING, S.ARCHIVED}),
    S.PUBLISHING: frozenset({S.PUBLISHED, S.FAILED, S.UNCERTAIN}),
    S.PUBLISHED: frozenset({S.ARCHIVED}),
    S.FAILED: frozenset({S.DRAFT, S.SCHEDULED, S.ARCHIVED}),
    S.UNCERTAIN: frozenset({S.PUBLISHED, S.FAILED}),
    S.ARCHIVED: frozenset(),
}

#: States whose content may still be edited (an edit always returns to DRAFT).
EDITABLE_STATES = frozenset({S.DRAFT, S.READY_FOR_REVIEW, S.APPROVED, S.SCHEDULED, S.FAILED})
#: States in which only the schedule may be changed without touching approval.
RESCHEDULABLE_STATES = frozenset({S.DRAFT, S.READY_FOR_REVIEW, S.APPROVED, S.SCHEDULED, S.FAILED})
#: States that require a recorded approval.
APPROVAL_REQUIRED_STATES = frozenset(
    {S.APPROVED, S.SCHEDULED, S.PUBLISHING, S.PUBLISHED, S.FAILED, S.UNCERTAIN}
)


def require_transition(current: LifecycleState, target: LifecycleState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise IllegalTransitionError(f"cannot move a post from {current.value} to {target.value}")


class AttemptOutcome(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


def format_utc(moment: datetime) -> str:
    """Render an aware datetime as a UTC timestamp with second precision."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.match(value):
        raise ValueError(f"not a UTC timestamp (YYYY-MM-DDTHH:MM:SSZ): {value!r}")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_local_date(value: str) -> date:
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        raise ValueError(f"not a date (YYYY-MM-DD): {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"not a real calendar date: {value!r}") from None


def is_valid_timezone(name: Any) -> bool:
    if not isinstance(name, str) or not name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


@dataclass(frozen=True)
class MediaRef:
    """A local media file, pinned by the SHA-256 of its bytes."""

    path: str
    sha256: str
    alt_text: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "alt_text": self.alt_text}


@dataclass(frozen=True)
class ArtifactRef:
    """A pointer to a separate artifact (verification report or approval record).

    The post never embeds the artifact. It records where the artifact is, the
    hash of its bytes, and the content fingerprint the artifact was made for,
    so a later content change makes the reference visibly stale.
    """

    path: str
    sha256: str
    content_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "content_fingerprint": self.content_fingerprint}


@dataclass(frozen=True)
class PublishAttempt:
    attempt_id: str
    started_at: str
    content_fingerprint: str
    outcome: AttemptOutcome = AttemptOutcome.PENDING
    finished_at: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "started_at": self.started_at,
            "content_fingerprint": self.content_fingerprint,
            "outcome": self.outcome.value,
            "finished_at": self.finished_at,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class HistoryEvent:
    """One audited change. The list is append only."""

    at: str
    actor: str
    action: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at, "actor": self.actor, "action": self.action, "detail": self.detail}


def content_fingerprint(
    text: str, urls: list[str] | tuple[str, ...], media: list[MediaRef] | tuple[MediaRef, ...]
) -> str:
    """Fingerprint of everything that would be published.

    Covers the exact text, the referenced links in order, and each media file's
    path, byte hash and alt text. It deliberately excludes the title (internal
    label, never sent to LinkedIn) and the schedule, so a scheduling change does
    not invalidate verification or approval while any content change does.
    """
    payload = {
        "schema": CONTENT_SCHEMA,
        "text": text,
        "urls": list(urls),
        "media": [item.to_dict() for item in media],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Post:
    id: str
    title: str
    text: str
    created_at: str
    updated_at: str
    timezone: str
    state: LifecycleState = LifecycleState.DRAFT
    revision: int = 0
    urls: tuple[str, ...] = ()
    media: tuple[MediaRef, ...] = ()
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    content_fingerprint: str = ""
    verification_ref: ArtifactRef | None = None
    approval_ref: ArtifactRef | None = None
    attempts: tuple[PublishAttempt, ...] = ()
    linkedin_post_id: str | None = None
    history: tuple[HistoryEvent, ...] = field(default_factory=tuple)

    def computed_fingerprint(self) -> str:
        return content_fingerprint(self.text, self.urls, self.media)

    @property
    def fingerprint_is_current(self) -> bool:
        """False when the stored fingerprint no longer matches the content (a hand edit)."""
        return self.content_fingerprint == self.computed_fingerprint()

    @property
    def approval_is_current(self) -> bool:
        """True only when an approval is recorded for exactly the present content."""
        return (
            self.approval_ref is not None
            and self.approval_ref.content_fingerprint == self.computed_fingerprint()
        )

    @property
    def verification_is_current(self) -> bool:
        return (
            self.verification_ref is not None
            and self.verification_ref.content_fingerprint == self.computed_fingerprint()
        )

    @property
    def last_attempt(self) -> PublishAttempt | None:
        return self.attempts[-1] if self.attempts else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": POST_SCHEMA,
            "id": self.id,
            "revision": self.revision,
            "title": self.title,
            "text": self.text,
            "urls": list(self.urls),
            "media": [item.to_dict() for item in self.media],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "scheduled_date": self.scheduled_date,
            "scheduled_time": self.scheduled_time,
            "timezone": self.timezone,
            "state": self.state.value,
            "content_fingerprint": self.content_fingerprint,
            "verification_ref": self.verification_ref.to_dict() if self.verification_ref else None,
            "approval_ref": self.approval_ref.to_dict() if self.approval_ref else None,
            "attempts": [item.to_dict() for item in self.attempts],
            "linkedin_post_id": self.linkedin_post_id,
            "history": [item.to_dict() for item in self.history],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, data: Any) -> "Post":
        """Strictly parse a post document, raising PostValidationError with every problem."""
        return _PostParser(data).parse()


_POST_KEYS = frozenset(
    {
        "schema",
        "id",
        "revision",
        "title",
        "text",
        "urls",
        "media",
        "created_at",
        "updated_at",
        "scheduled_date",
        "scheduled_time",
        "timezone",
        "state",
        "content_fingerprint",
        "verification_ref",
        "approval_ref",
        "attempts",
        "linkedin_post_id",
        "history",
    }
)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _has_unpaired_surrogate(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


class _PostParser:
    """Collects every structural and lifecycle defect instead of stopping at the first."""

    def __init__(self, data: Any) -> None:
        self.data = data
        self.problems: list[str] = []

    def parse(self) -> Post:
        data = self.data
        if not isinstance(data, dict):
            raise PostValidationError(["post document must be a JSON object"])
        missing = sorted(_POST_KEYS - set(data))
        unknown = sorted(str(key) for key in set(data) - _POST_KEYS)
        if missing:
            self.problems.append(f"missing field(s): {', '.join(missing)}")
        if unknown:
            self.problems.append(f"unknown field(s): {', '.join(unknown)}")
        if missing:
            raise PostValidationError(self.problems)

        if data["schema"] != POST_SCHEMA:
            self.problems.append(f"schema must be {POST_SCHEMA!r}, got {data['schema']!r}")
        self._pattern("id", data["id"], ID_PATTERN)
        if not _is_int(data["revision"]) or data["revision"] < 0:
            self.problems.append("revision must be a non-negative integer")
        self._text("title", data["title"], MAX_TITLE_CHARS, single_line=True)
        self._text("text", data["text"], MAX_TEXT_CHARS)
        urls = self._urls(data["urls"])
        media = self._media(data["media"])
        self._timestamp("created_at", data["created_at"])
        self._timestamp("updated_at", data["updated_at"])
        self._date("scheduled_date", data["scheduled_date"])
        if data["scheduled_time"] is not None:
            self._pattern("scheduled_time", data["scheduled_time"], TIME_PATTERN)
        if not is_valid_timezone(data["timezone"]):
            self.problems.append(f"timezone is not a known IANA zone: {data['timezone']!r}")
        state = self._state(data["state"])
        self._pattern("content_fingerprint", data["content_fingerprint"], FINGERPRINT_PATTERN)
        verification_ref = self._artifact_ref("verification_ref", data["verification_ref"])
        approval_ref = self._artifact_ref("approval_ref", data["approval_ref"])
        attempts = self._attempts(data["attempts"])
        linkedin_post_id = data["linkedin_post_id"]
        if linkedin_post_id is not None:
            self._text("linkedin_post_id", linkedin_post_id, MAX_EXTERNAL_ID_CHARS, single_line=True)
        history = self._history(data["history"])

        if self.problems:
            raise PostValidationError(self.problems)

        post = Post(
            id=data["id"],
            revision=data["revision"],
            title=data["title"],
            text=data["text"],
            urls=urls,
            media=media,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            scheduled_date=data["scheduled_date"],
            scheduled_time=data["scheduled_time"],
            timezone=data["timezone"],
            state=state,  # type: ignore[arg-type]
            content_fingerprint=data["content_fingerprint"],
            verification_ref=verification_ref,
            approval_ref=approval_ref,
            attempts=attempts,
            linkedin_post_id=linkedin_post_id,
            history=history,
        )
        lifecycle = lifecycle_problems(post)
        if lifecycle:
            raise PostValidationError(lifecycle)
        return post

    def _pattern(self, name: str, value: Any, pattern: re.Pattern[str]) -> bool:
        if not isinstance(value, str) or not pattern.match(value):
            self.problems.append(f"{name} has an invalid value: {value!r}")
            return False
        return True

    def _text(self, name: str, value: Any, limit: int, *, single_line: bool = False) -> None:
        if not isinstance(value, str) or not value.strip():
            self.problems.append(f"{name} must be a non-empty string")
            return
        if len(value) > limit:
            self.problems.append(f"{name} is longer than {limit} characters")
        if single_line and ("\n" in value or "\r" in value):
            self.problems.append(f"{name} must be a single line")
        if _has_unpaired_surrogate(value):
            self.problems.append(f"{name} contains broken Unicode (an unpaired surrogate)")

    def _timestamp(self, name: str, value: Any) -> None:
        try:
            parse_utc(value)
        except ValueError:
            self.problems.append(f"{name} must be a UTC timestamp (YYYY-MM-DDTHH:MM:SSZ): {value!r}")

    def _date(self, name: str, value: Any) -> None:
        if value is None:
            return
        try:
            parse_local_date(value)
        except ValueError:
            self.problems.append(f"{name} must be a real calendar date (YYYY-MM-DD): {value!r}")

    def _state(self, value: Any) -> LifecycleState | None:
        try:
            return LifecycleState(value)
        except ValueError:
            self.problems.append(f"state is not a known lifecycle state: {value!r}")
            return None

    def _urls(self, value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            self.problems.append("urls must be a list")
            return ()
        if len(value) > MAX_URLS:
            self.problems.append(f"urls has more than {MAX_URLS} entries")
        for item in value:
            if not isinstance(item, str) or not URL_PATTERN.match(item) or len(item) > MAX_URL_CHARS:
                self.problems.append(f"urls entry is not an https URL: {item!r}")
        if len({item for item in value if isinstance(item, str)}) != len(value):
            self.problems.append("urls entries must be unique strings")
        return tuple(item for item in value if isinstance(item, str))

    def _media(self, value: Any) -> tuple[MediaRef, ...]:
        if not isinstance(value, list):
            self.problems.append("media must be a list")
            return ()
        if len(value) > MAX_MEDIA:
            self.problems.append(f"media has more than {MAX_MEDIA} entry (one image per post is supported)")
        result: list[MediaRef] = []
        for index, item in enumerate(value):
            label = f"media[{index}]"
            if not isinstance(item, dict) or set(item) != {"path", "sha256", "alt_text"}:
                self.problems.append(f"{label} must have exactly path, sha256 and alt_text")
                continue
            ok = self._pattern(f"{label}.path", item["path"], MEDIA_PATH_PATTERN)
            if ok and ".." in item["path"]:
                self.problems.append(f"{label}.path must not contain '..'")
                ok = False
            ok = self._pattern(f"{label}.sha256", item["sha256"], SHA256_PATTERN) and ok
            before = len(self.problems)
            self._text(f"{label}.alt_text", item["alt_text"], MAX_ALT_TEXT_CHARS)
            if ok and len(self.problems) == before:
                result.append(MediaRef(path=item["path"], sha256=item["sha256"], alt_text=item["alt_text"]))
        return tuple(result)

    def _artifact_ref(self, name: str, value: Any) -> ArtifactRef | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"path", "sha256", "content_fingerprint"}:
            self.problems.append(f"{name} must be null or have exactly path, sha256 and content_fingerprint")
            return None
        ok = self._pattern(f"{name}.path", value["path"], ARTIFACT_PATH_PATTERN)
        if ok and (".." in value["path"] or value["path"].startswith("/")):
            self.problems.append(f"{name}.path must stay inside the repository")
            ok = False
        ok = self._pattern(f"{name}.sha256", value["sha256"], SHA256_PATTERN) and ok
        ok = (
            self._pattern(f"{name}.content_fingerprint", value["content_fingerprint"], FINGERPRINT_PATTERN)
            and ok
        )
        if not ok:
            return None
        return ArtifactRef(
            path=value["path"], sha256=value["sha256"], content_fingerprint=value["content_fingerprint"]
        )

    def _attempts(self, value: Any) -> tuple[PublishAttempt, ...]:
        if not isinstance(value, list):
            self.problems.append("attempts must be a list")
            return ()
        keys = {"attempt_id", "started_at", "content_fingerprint", "outcome", "finished_at", "detail"}
        result: list[PublishAttempt] = []
        for index, item in enumerate(value):
            label = f"attempts[{index}]"
            if not isinstance(item, dict) or set(item) != keys:
                self.problems.append(f"{label} must have exactly: {', '.join(sorted(keys))}")
                continue
            before = len(self.problems)
            self._pattern(f"{label}.attempt_id", item["attempt_id"], ID_PATTERN)
            self._timestamp(f"{label}.started_at", item["started_at"])
            self._pattern(f"{label}.content_fingerprint", item["content_fingerprint"], FINGERPRINT_PATTERN)
            if item["finished_at"] is not None:
                self._timestamp(f"{label}.finished_at", item["finished_at"])
            if not isinstance(item["detail"], str) or len(item["detail"]) > MAX_DETAIL_CHARS:
                self.problems.append(
                    f"{label}.detail must be a string of at most {MAX_DETAIL_CHARS} characters"
                )
            try:
                outcome = AttemptOutcome(item["outcome"])
            except ValueError:
                self.problems.append(f"{label}.outcome is not a known outcome: {item['outcome']!r}")
                continue
            if (outcome is AttemptOutcome.PENDING) != (item["finished_at"] is None):
                self.problems.append(f"{label} must have finished_at exactly when its outcome is not PENDING")
            if len(self.problems) == before:
                result.append(
                    PublishAttempt(
                        attempt_id=item["attempt_id"],
                        started_at=item["started_at"],
                        content_fingerprint=item["content_fingerprint"],
                        outcome=outcome,
                        finished_at=item["finished_at"],
                        detail=item["detail"],
                    )
                )
        return tuple(result)

    def _history(self, value: Any) -> tuple[HistoryEvent, ...]:
        if not isinstance(value, list):
            self.problems.append("history must be a list")
            return ()
        result: list[HistoryEvent] = []
        for index, item in enumerate(value):
            label = f"history[{index}]"
            if not isinstance(item, dict) or set(item) != {"at", "actor", "action", "detail"}:
                self.problems.append(f"{label} must have exactly at, actor, action and detail")
                continue
            before = len(self.problems)
            self._timestamp(f"{label}.at", item["at"])
            for key in ("actor", "action"):
                if (
                    not isinstance(item[key], str)
                    or not item[key].strip()
                    or len(item[key]) > MAX_TITLE_CHARS
                ):
                    self.problems.append(f"{label}.{key} must be a short non-empty string")
            if not isinstance(item["detail"], str) or len(item["detail"]) > MAX_DETAIL_CHARS:
                self.problems.append(
                    f"{label}.detail must be a string of at most {MAX_DETAIL_CHARS} characters"
                )
            if len(self.problems) == before:
                result.append(
                    HistoryEvent(
                        at=item["at"], actor=item["actor"], action=item["action"], detail=item["detail"]
                    )
                )
        return tuple(result)


def lifecycle_problems(post: Post) -> list[str]:
    """Cross-field rules that keep the lifecycle state consistent with the rest of the record."""
    problems: list[str] = []
    state = post.state
    last = post.last_attempt
    if parse_utc(post.updated_at) < parse_utc(post.created_at):
        problems.append("updated_at is earlier than created_at")
    if state in APPROVAL_REQUIRED_STATES and post.approval_ref is None:
        problems.append(f"state {state.value} requires an approval reference")
    if state in (S.SCHEDULED, S.PUBLISHING) and post.scheduled_date is None:
        problems.append(f"state {state.value} requires a scheduled date")
    if state is S.PUBLISHED and post.linkedin_post_id is None:
        problems.append("state PUBLISHED requires the LinkedIn post ID")
    if post.linkedin_post_id is not None and state not in (S.PUBLISHED, S.ARCHIVED):
        problems.append(f"a LinkedIn post ID is recorded but the state is {state.value}")
    pending = [attempt for attempt in post.attempts if attempt.outcome is AttemptOutcome.PENDING]
    if pending and (state is not S.PUBLISHING or last is None or last.outcome is not AttemptOutcome.PENDING):
        problems.append("a PENDING attempt is only valid as the last attempt of a PUBLISHING post")
    if len(pending) > 1:
        problems.append("more than one PENDING attempt")
    if state is S.PUBLISHING and (last is None or last.outcome is not AttemptOutcome.PENDING):
        problems.append("state PUBLISHING requires a PENDING last attempt (the persisted intent)")
    if state is S.UNCERTAIN and (last is None or last.outcome is not AttemptOutcome.AMBIGUOUS):
        problems.append("state UNCERTAIN requires an AMBIGUOUS last attempt")
    if state is S.PUBLISHED and not any(a.outcome is AttemptOutcome.SUCCESS for a in post.attempts):
        problems.append("state PUBLISHED requires a successful attempt")
    if len({attempt.attempt_id for attempt in post.attempts}) != len(post.attempts):
        problems.append("attempt IDs must be unique")
    return problems
