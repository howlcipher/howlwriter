"""Shared deterministic fakes for the LinkedIn publisher tests. No network, no real clock."""

from __future__ import annotations

from datetime import datetime, timedelta

import yaml

from howlwriter.linkedin.config import CONFIG_SCHEMA, DEFAULTS
from howlwriter.linkedin.models import ArtifactRef, AttemptOutcome, Post, parse_utc
from howlwriter.linkedin.publisher import PublishCoordinator, TransportResult
from howlwriter.linkedin.service import QueueService
from howlwriter.linkedin.store import QueueStore

#: Monday 16 November 2026, 07:00 in America/Detroit (EST, UTC-5).
START = "2026-11-16T12:00:00Z"
SHA = "a" * 64


class FakeClock:
    def __init__(self, moment: str = START) -> None:
        self.moment = parse_utc(moment)

    def now(self) -> datetime:
        return self.moment

    def set(self, moment: str) -> None:
        self.moment = parse_utc(moment)

    def advance(self, **delta) -> None:
        self.moment += timedelta(**delta)


class AcceptAllVerifier:
    """Test stand-in for the trusted verification and approval checks. Never shipped."""

    def problems(self, kind, post, ref):
        return []


class AllowGate:
    def blockers(self, post):
        return []


class FakeTransport:
    """Scripted transport. Records every call so tests can prove nothing was sent twice."""

    def __init__(self, *results) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    def publish(self, post: Post):
        self.calls.append(post.id)
        result = self.results.pop(0) if self.results else success(f"urn:li:share:{len(self.calls)}")
        if isinstance(result, BaseException):
            raise result
        return result


def success(identifier: str = "urn:li:share:1") -> TransportResult:
    return TransportResult(AttemptOutcome.SUCCESS, identifier, "created")


def failure(detail: str = "HTTP 401") -> TransportResult:
    return TransportResult(AttemptOutcome.FAILED, None, detail)


def ambiguous(detail: str = "timeout after send") -> TransportResult:
    return TransportResult(AttemptOutcome.AMBIGUOUS, None, detail)


def write_config(store: QueueStore, **overrides) -> None:
    data = {"schema": CONFIG_SCHEMA, **DEFAULTS, **overrides}
    store.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def go_live(store: QueueStore, **overrides) -> None:
    write_config(store, publishing_enabled=True, dry_run=False, **overrides)


def make_service(store: QueueStore, clock: FakeClock, **kwargs) -> QueueService:
    counter = iter(range(1, 10000))
    kwargs.setdefault("verifier", AcceptAllVerifier())
    kwargs.setdefault("id_factory", lambda title: f"post-{next(counter):03d}")
    return QueueService(store, clock, **kwargs)


def ref_for(post: Post, kind: str = "approvals") -> ArtifactRef:
    return ArtifactRef(path=f"{kind}/{post.id}.json", sha256=SHA, content_fingerprint=post.computed_fingerprint())


def approved_post(service: QueueService, title: str = "A post", date: str | None = None, time: str | None = None):
    post = service.add_draft(
        title=title, text=f"{title}. Body text.", actor="tester", scheduled_date=date, scheduled_time=time
    )
    service.attach_verification(post.id, ref_for(post, "verification"), actor="tester")
    service.submit_for_review(post.id, actor="tester")
    return service.approve(post.id, ref_for(post), actor="tester")


def scheduled_post(service: QueueService, title: str, date: str, time: str | None = None) -> Post:
    post = approved_post(service, title, date, time)
    return service.schedule(post.id, actor="tester")


def dated_draft(service: QueueService, title: str, date: str, time: str | None = None) -> Post:
    """An unapproved post with a date: local commands may still move it."""
    return service.add_draft(
        title=title, text=f"{title}. Body text.", actor="tester", scheduled_date=date, scheduled_time=time
    )


def make_coordinator(store, clock, transport, **kwargs) -> PublishCoordinator:
    counter = iter(range(1, 10000))
    kwargs.setdefault("gates", [AllowGate()])
    kwargs.setdefault("attempt_id_factory", lambda: f"attempt-{next(counter):03d}")
    return PublishCoordinator(store, transport, clock=clock, **kwargs)
