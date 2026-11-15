"""File persistence for the private publishing repository.

Layout under the repository root:

    publisher.yaml               configuration (human edited, validated)
    posts/<id>.json              one post per file
    media/...                    local media referenced by posts
    state/control.json           global pause switch and its audit trail
    ledger/<year>/<date>.json    daily publication ledger (one file per local day)

Every write is atomic (temporary file, fsync, rename) and guarded twice: an
exclusive advisory lock serializes writers on one machine, and each record
carries a revision that must match on write (compare and swap), so a stale
reader can never overwrite a newer change. New records are created with
exclusive creation, so two writers can never both believe they created the
same post or claimed the same day.
"""

from __future__ import annotations

import contextlib
import enum
import json
import os
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from howlwriter.linkedin.config import CONFIG_FILENAME, PublisherConfig, load_config, render_default_config
from howlwriter.linkedin.models import (
    FINGERPRINT_PATTERN,
    ID_PATTERN,
    HistoryEvent,
    Post,
    PostValidationError,
    parse_local_date,
    parse_utc,
)
from howlwriter.publishing.base import RevisionConflictError

CONTROL_SCHEMA = "howlwriter.linkedin_control/v1"
LEDGER_SCHEMA = "howlwriter.linkedin_ledger_day/v1"
LOCK_FILENAME = ".publisher.lock"
GITIGNORE_LINES = (LOCK_FILENAME, "*.tmp")


class StoreError(RuntimeError):
    """The repository could not be read or written safely."""


class PostNotFoundError(StoreError):
    pass


class PostExistsError(StoreError):
    pass


class LedgerCorruptError(StoreError):
    """A ledger or control file is unreadable. Publishing must stop until a human repairs it."""


class DayAlreadyClaimedError(StoreError):
    """The daily publication limit for this local day is already used."""


@dataclass(frozen=True)
class InvalidPostFile:
    path: str
    problems: tuple[str, ...]


@dataclass(frozen=True)
class QueueSnapshot:
    posts: tuple[Post, ...]
    invalid: tuple[InvalidPostFile, ...] = ()

    def by_id(self, post_id: str) -> Post | None:
        return next((post for post in self.posts if post.id == post_id), None)


@dataclass(frozen=True)
class ControlState:
    paused: bool = False
    revision: int = 0
    history: tuple[HistoryEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTROL_SCHEMA,
            "paused": self.paused,
            "revision": self.revision,
            "history": [event.to_dict() for event in self.history],
        }


class LedgerEntryState(str, enum.Enum):
    INTENT = "INTENT"
    PUBLISHED = "PUBLISHED"
    UNCERTAIN = "UNCERTAIN"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class LedgerEntry:
    post_id: str
    attempt_id: str
    content_fingerprint: str
    state: LedgerEntryState
    claimed_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "attempt_id": self.attempt_id,
            "content_fingerprint": self.content_fingerprint,
            "state": self.state.value,
            "claimed_at": self.claimed_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class LedgerDay:
    """Everything that used, or tried to use, one local calendar day."""

    day: str
    revision: int = 0
    entries: tuple[LedgerEntry, ...] = field(default_factory=tuple)

    @property
    def occupying(self) -> tuple[LedgerEntry, ...]:
        """Entries that count against the daily limit. Only a definite non-publication releases a day."""
        return tuple(entry for entry in self.entries if entry.state is not LedgerEntryState.RELEASED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA,
            "date": self.day,
            "revision": self.revision,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _dump(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _parse_history(raw: Any) -> tuple[HistoryEvent, ...]:
    if not isinstance(raw, list):
        raise ValueError("history must be a list")
    events = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"at", "actor", "action", "detail"}:
            raise ValueError("history entries must have exactly at, actor, action and detail")
        if not all(isinstance(item[key], str) for key in item):
            raise ValueError("history entry values must be strings")
        parse_utc(item["at"])
        events.append(HistoryEvent(**item))
    return tuple(events)


def _parse_control(raw: Any) -> ControlState:
    if not isinstance(raw, dict) or set(raw) != {"schema", "paused", "revision", "history"}:
        raise ValueError("control file must have exactly schema, paused, revision and history")
    if raw["schema"] != CONTROL_SCHEMA or not isinstance(raw["paused"], bool):
        raise ValueError("control file has a wrong schema or a non-boolean paused value")
    if not isinstance(raw["revision"], int) or isinstance(raw["revision"], bool) or raw["revision"] < 0:
        raise ValueError("control revision must be a non-negative integer")
    return ControlState(
        paused=raw["paused"], revision=raw["revision"], history=_parse_history(raw["history"])
    )


def _parse_ledger_day(raw: Any, expected_day: str) -> LedgerDay:
    if not isinstance(raw, dict) or set(raw) != {"schema", "date", "revision", "entries"}:
        raise ValueError("ledger day must have exactly schema, date, revision and entries")
    if raw["schema"] != LEDGER_SCHEMA or raw["date"] != expected_day:
        raise ValueError("ledger day has a wrong schema or a date that does not match its file name")
    if not isinstance(raw["revision"], int) or isinstance(raw["revision"], bool) or raw["revision"] < 0:
        raise ValueError("ledger revision must be a non-negative integer")
    if not isinstance(raw["entries"], list):
        raise ValueError("ledger entries must be a list")
    keys = {"post_id", "attempt_id", "content_fingerprint", "state", "claimed_at", "updated_at"}
    entries = []
    for item in raw["entries"]:
        if not isinstance(item, dict) or set(item) != keys:
            raise ValueError("ledger entry has missing or unknown fields")
        if not all(isinstance(item[key], str) for key in keys):
            raise ValueError("ledger entry values must be strings")
        if not ID_PATTERN.match(item["post_id"]) or not ID_PATTERN.match(item["attempt_id"]):
            raise ValueError("ledger entry has an invalid post or attempt ID")
        if not FINGERPRINT_PATTERN.match(item["content_fingerprint"]):
            raise ValueError("ledger entry has an invalid content fingerprint")
        parse_utc(item["claimed_at"])
        parse_utc(item["updated_at"])
        entries.append(replace(LedgerEntry(**item), state=LedgerEntryState(item["state"])))
    if len({entry.attempt_id for entry in entries}) != len(entries):
        raise ValueError("ledger attempt IDs must be unique")
    return LedgerDay(day=raw["date"], revision=raw["revision"], entries=tuple(entries))


class QueueStore:
    """Reads and writes one publishing repository directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._lock_depth = 0
        self._lock_handle: Any = None

    # Paths

    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_FILENAME

    @property
    def posts_dir(self) -> Path:
        return self.root / "posts"

    @property
    def control_path(self) -> Path:
        return self.root / "state" / "control.json"

    def post_path(self, post_id: str) -> Path:
        if not ID_PATTERN.match(post_id):
            raise StoreError(f"invalid post ID: {post_id!r}")
        return self.posts_dir / f"{post_id}.json"

    def ledger_path(self, day: date) -> Path:
        return self.root / "ledger" / f"{day.year:04d}" / f"{day.isoformat()}.json"

    # Setup and locking

    def initialize(self) -> list[str]:
        """Create the repository layout. Existing files are never overwritten."""
        created: list[str] = []
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in (self.posts_dir, self.root / "media", self.root / "state", self.root / "ledger"):
            directory.mkdir(parents=True, exist_ok=True)
            keep = directory / ".gitkeep"
            if not any(directory.iterdir()):
                keep.touch()
        if not self.config_path.exists():
            self._create_exclusive(self.config_path, render_default_config().encode("utf-8"))
            created.append(CONFIG_FILENAME)
        gitignore = self.root / ".gitignore"
        existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
        missing = [line for line in GITIGNORE_LINES if line not in existing]
        if missing:
            self._replace(gitignore, ("\n".join(existing + missing) + "\n").encode("utf-8"))
            created.append(".gitignore")
        return created

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive advisory lock over the repository. Reentrant within one store object."""
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        try:
            import fcntl
        except ImportError as error:  # not POSIX
            raise StoreError("the publisher store needs POSIX file locking (Linux or macOS)") from error
        if not self.root.is_dir():
            raise StoreError(f"publishing repository not found: {self.root}")
        handle = open(self.root / LOCK_FILENAME, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            self._lock_depth = 1
            self._lock_handle = handle
            yield
        finally:
            self._lock_depth = 0
            self._lock_handle = None
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _replace(self, path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(temporary, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def _create_exclusive(self, path: Path, payload: bytes) -> None:
        """Create a file that must not already exist. Raises FileExistsError otherwise."""
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            raise

    # Configuration and control

    def load_config(self) -> PublisherConfig:
        return load_config(self.config_path)

    def load_control(self) -> ControlState:
        try:
            raw = json.loads(self.control_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ControlState()
        except (OSError, ValueError) as error:
            raise LedgerCorruptError(f"control file is unreadable: {error}") from error
        try:
            return _parse_control(raw)
        except ValueError as error:
            raise LedgerCorruptError(f"control file is invalid: {error}") from error

    def save_control(self, control: ControlState, expected_revision: int) -> ControlState:
        with self.lock():
            current = self.load_control()
            if current.revision != expected_revision:
                raise RevisionConflictError(
                    f"control state changed (revision {current.revision}, expected {expected_revision})"
                )
            saved = replace(control, revision=expected_revision + 1)
            self._replace(self.control_path, _dump(saved.to_dict()))
            return saved

    # Posts

    def load_post(self, post_id: str) -> Post:
        path = self.post_path(post_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise PostNotFoundError(f"no post with ID {post_id!r}")
        except (OSError, ValueError) as error:
            raise PostValidationError([f"{path.name} is not readable JSON: {error}"])
        post = Post.from_dict(raw)
        if post.id != post_id:
            raise PostValidationError([f"{path.name} contains post ID {post.id!r}"])
        return post

    def load_snapshot(self) -> QueueSnapshot:
        """Load every post. Malformed files are reported, never skipped silently."""
        posts: list[Post] = []
        invalid: list[InvalidPostFile] = []
        if self.posts_dir.is_dir():
            for path in sorted(self.posts_dir.glob("*.json")):
                try:
                    posts.append(self.load_post(path.stem))
                except PostValidationError as error:
                    invalid.append(InvalidPostFile(path=f"posts/{path.name}", problems=tuple(error.problems)))
                except StoreError as error:
                    invalid.append(InvalidPostFile(path=f"posts/{path.name}", problems=(str(error),)))
        return QueueSnapshot(posts=tuple(posts), invalid=tuple(invalid))

    def create_post(self, post: Post) -> Post:
        prepared = replace(post, revision=0, content_fingerprint=post.computed_fingerprint())
        Post.from_dict(prepared.to_dict())
        with self.lock():
            try:
                self._create_exclusive(self.post_path(post.id), prepared.to_json().encode("utf-8"))
            except FileExistsError:
                raise PostExistsError(f"a post with ID {post.id!r} already exists")
        return prepared

    def save_post(self, post: Post, expected_revision: int) -> Post:
        """Compare and swap: write only if the stored revision is still ``expected_revision``."""
        with self.lock():
            current = self.load_post(post.id)
            if current.revision != expected_revision:
                raise RevisionConflictError(
                    f"post {post.id} changed (revision {current.revision}, expected {expected_revision}); "
                    "reload it and repeat the change"
                )
            prepared = replace(
                post, revision=expected_revision + 1, content_fingerprint=post.computed_fingerprint()
            )
            Post.from_dict(prepared.to_dict())
            self._replace(self.post_path(post.id), prepared.to_json().encode("utf-8"))
            return prepared

    # Media

    def media_file(self, relative_path: str) -> Path:
        """Resolve a media reference, refusing anything that leaves the repository."""
        root = self.root.resolve()
        candidate = (root / relative_path).resolve()
        if root not in candidate.parents:
            raise StoreError(f"media path leaves the repository: {relative_path!r}")
        return candidate

    # Ledger

    def load_ledger_day(self, day: date) -> LedgerDay | None:
        path = self.ledger_path(day)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise LedgerCorruptError(f"ledger file {path.name} is unreadable: {error}") from error
        try:
            return _parse_ledger_day(raw, day.isoformat())
        except ValueError as error:
            raise LedgerCorruptError(f"ledger file {path.name} is invalid: {error}") from error

    def claim_day(self, day: date, entry: LedgerEntry, max_per_day: int) -> LedgerDay:
        """Record a publishing intent for a local day, or raise DayAlreadyClaimedError.

        The claim is persisted before anything is sent, so the daily limit
        survives crashes and never depends on memory.
        """
        parse_local_date(day.isoformat())
        with self.lock():
            current = self.load_ledger_day(day)
            if current is None:
                created = LedgerDay(day=day.isoformat(), revision=1, entries=(entry,))
                try:
                    self._create_exclusive(self.ledger_path(day), _dump(created.to_dict()))
                except FileExistsError:
                    raise DayAlreadyClaimedError(f"{day.isoformat()} was claimed by another writer")
                return created
            if len(current.occupying) >= max_per_day:
                holder = current.occupying[0]
                raise DayAlreadyClaimedError(
                    f"{day.isoformat()} is already used by post {holder.post_id} ({holder.state.value})"
                )
            if any(existing.attempt_id == entry.attempt_id for existing in current.entries):
                raise StoreError(f"attempt {entry.attempt_id} is already in the ledger")
            updated = LedgerDay(
                day=current.day, revision=current.revision + 1, entries=current.entries + (entry,)
            )
            self._replace(self.ledger_path(day), _dump(updated.to_dict()))
            return updated

    def update_ledger_entry(self, day: date, attempt_id: str, state: LedgerEntryState, at: str) -> LedgerDay:
        with self.lock():
            current = self.load_ledger_day(day)
            if current is None or not any(entry.attempt_id == attempt_id for entry in current.entries):
                raise StoreError(f"no ledger entry for attempt {attempt_id} on {day.isoformat()}")
            entries = tuple(
                replace(entry, state=state, updated_at=at) if entry.attempt_id == attempt_id else entry
                for entry in current.entries
            )
            updated = LedgerDay(day=current.day, revision=current.revision + 1, entries=entries)
            self._replace(self.ledger_path(day), _dump(updated.to_dict()))
            return updated

    def find_ledger_entry(self, attempt_id: str) -> tuple[date, LedgerEntry] | None:
        """Locate an attempt anywhere in the ledger (used by recovery and reconciliation)."""
        ledger_root = self.root / "ledger"
        if not ledger_root.is_dir():
            return None
        for path in sorted(ledger_root.glob("*/*.json")):
            try:
                day = date.fromisoformat(path.stem)
            except ValueError:
                raise LedgerCorruptError(f"unexpected file in the ledger: {path.name}")
            loaded = self.load_ledger_day(day)
            for entry in loaded.entries if loaded else ():
                if entry.attempt_id == attempt_id:
                    return day, entry
        return None
