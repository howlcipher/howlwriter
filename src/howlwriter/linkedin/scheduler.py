"""Deterministic scheduling evaluation. Pure functions: no clock, no files, no network.

Given the configuration, the pause switch, the queue, today's ledger and an
explicit "now", ``evaluate`` says which single post (if any) is due. A run is
slot agnostic: the hosted workflow simply runs at each supported time and the
answer depends only on the time it actually started, which is what makes late
and missed runs safe.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from howlwriter.linkedin.config import PublisherConfig
from howlwriter.linkedin.models import AttemptOutcome, LifecycleState, Post, parse_local_date, parse_utc
from howlwriter.linkedin.store import ControlState, LedgerDay, QueueSnapshot


class Action(str, enum.Enum):
    PUBLISH = "PUBLISH"
    NOTHING = "NOTHING"
    BLOCKED = "BLOCKED"


class Reason(str, enum.Enum):
    DUE = "DUE"
    PAUSED = "PAUSED"
    QUEUE_INVALID = "QUEUE_INVALID"
    IN_FLIGHT = "IN_FLIGHT"
    DAY_ALREADY_USED = "DAY_ALREADY_USED"
    NO_POST_DUE = "NO_POST_DUE"


class PostStatus(str, enum.Enum):
    DUE = "DUE"
    NOT_YET_DUE = "NOT_YET_DUE"
    FUTURE = "FUTURE"
    OVERDUE = "OVERDUE"
    BLOCKED = "BLOCKED"
    DAILY_LIMIT_CONFLICT = "DAILY_LIMIT_CONFLICT"


@dataclass(frozen=True)
class PostAssessment:
    post_id: str
    status: PostStatus
    due_at: str | None
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "status": self.status.value,
            "due_at": self.due_at,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class Evaluation:
    now: str
    local_date: str
    action: Action
    reason: Reason
    candidate_id: str | None
    assessments: tuple[PostAssessment, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "now": self.now,
            "local_date": self.local_date,
            "action": self.action.value,
            "reason": self.reason.value,
            "candidate_id": self.candidate_id,
            "assessments": [item.to_dict() for item in self.assessments],
            "notes": list(self.notes),
        }


def local_date(now: datetime, tz: ZoneInfo) -> date:
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    return now.astimezone(tz).date()


def due_at(day: date, slot: str, tz: ZoneInfo) -> datetime:
    """The UTC instant a slot occurs on a local day, defined across daylight saving changes.

    A wall time skipped by a spring-forward change resolves to the same elapsed
    time after the gap (02:30 becomes 03:30). A wall time repeated by a
    fall-back change resolves to its first occurrence.
    """
    hour, minute = (int(part) for part in slot.split(":"))
    wall = datetime.combine(day, time(hour, minute), tzinfo=tz)
    return wall.astimezone(timezone.utc)


def effective_time(post: Post, config: PublisherConfig) -> str:
    return post.scheduled_time or config.default_publish_time


def schedule_problems(post: Post, config: PublisherConfig) -> list[str]:
    """Why a post's schedule cannot be honored under the current configuration."""
    problems: list[str] = []
    if post.timezone != config.timezone:
        problems.append(f"post timezone {post.timezone} differs from the configured {config.timezone}")
    slot = effective_time(post, config)
    if slot not in config.allowed_publish_times:
        problems.append(
            f"time {slot} is not a supported slot {list(config.allowed_publish_times)}; "
            "supporting it needs an explicit schedule configuration change"
        )
    return problems


def _used_today_by_posts(snapshot: QueueSnapshot, today: date, tz: ZoneInfo) -> list[str]:
    """Posts whose own records show a publication (or possible publication) today.

    A cross check that holds even if a ledger file were lost: the ledger is the
    primary record, and this independent evidence can only block, never allow.
    """
    used = []
    for post in snapshot.posts:
        for attempt in post.attempts:
            if attempt.outcome in (AttemptOutcome.SUCCESS, AttemptOutcome.AMBIGUOUS, AttemptOutcome.PENDING):
                if local_date(parse_utc(attempt.started_at), tz) == today:
                    used.append(post.id)
                    break
    return used


def assess_post(post: Post, config: PublisherConfig, now: datetime) -> PostAssessment:
    """Classify one SCHEDULED post against the clock and its own approval state."""
    tz = config.tzinfo
    today = local_date(now, tz)
    reasons = schedule_problems(post, config)
    if not post.approval_is_current:
        reasons.append("the recorded approval does not match the current content")
    if not post.fingerprint_is_current:
        reasons.append("the stored content fingerprint does not match the content (edited outside the tool)")
    if post.scheduled_date is None:
        return PostAssessment(post.id, PostStatus.BLOCKED, None, tuple(reasons + ["no scheduled date"]))
    day = parse_local_date(post.scheduled_date)
    due = due_at(day, effective_time(post, config), tz)
    due_text = due.strftime("%Y-%m-%dT%H:%M:%SZ")
    if reasons:
        return PostAssessment(post.id, PostStatus.BLOCKED, due_text, tuple(reasons))
    if day > today:
        return PostAssessment(post.id, PostStatus.FUTURE, due_text)
    if day < today:
        return PostAssessment(
            post.id, PostStatus.OVERDUE, due_text, ("its scheduled day has passed; reschedule it to publish",)
        )
    if now < due:
        return PostAssessment(post.id, PostStatus.NOT_YET_DUE, due_text)
    if now > due + timedelta(minutes=config.max_lateness_minutes):
        return PostAssessment(
            post.id,
            PostStatus.OVERDUE,
            due_text,
            (f"more than {config.max_lateness_minutes} minutes past its slot; reschedule it to publish",),
        )
    return PostAssessment(post.id, PostStatus.DUE, due_text)


def evaluate(
    config: PublisherConfig,
    control: ControlState,
    snapshot: QueueSnapshot,
    ledger_today: LedgerDay | None,
    now: datetime,
) -> Evaluation:
    """Decide what a publishing run starting at ``now`` should do. Never mutates anything."""
    tz = config.tzinfo
    today = local_date(now, tz)
    by_id = {post.id: post for post in snapshot.posts}
    scheduled = [post for post in snapshot.posts if post.state is LifecycleState.SCHEDULED]
    assessments = [assess_post(post, config, now) for post in scheduled]
    due = sorted(
        (item for item in assessments if item.status is PostStatus.DUE),
        key=lambda item: (item.due_at or "", by_id[item.post_id].created_at, item.post_id),
    )
    winner = due[0].post_id if due else None
    final = tuple(
        PostAssessment(
            item.post_id,
            PostStatus.DAILY_LIMIT_CONFLICT,
            item.due_at,
            (f"post {winner} is due first and only {config.max_posts_per_day} post may publish per day",),
        )
        if item.status is PostStatus.DUE and item.post_id != winner
        else item
        for item in assessments
    )

    def result(action: Action, reason: Reason, candidate: str | None, *notes: str) -> Evaluation:
        return Evaluation(
            now=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            local_date=today.isoformat(),
            action=action,
            reason=reason,
            candidate_id=candidate,
            assessments=final,
            notes=tuple(notes),
        )

    if snapshot.invalid:
        files = ", ".join(item.path for item in snapshot.invalid)
        return result(Action.BLOCKED, Reason.QUEUE_INVALID, None, f"invalid post file(s): {files}")
    in_flight = [post.id for post in snapshot.posts if post.state is LifecycleState.PUBLISHING]
    if in_flight:
        return result(
            Action.BLOCKED,
            Reason.IN_FLIGHT,
            None,
            f"post(s) left in PUBLISHING by an interrupted run: {', '.join(in_flight)}",
        )
    if control.paused:
        return result(Action.NOTHING, Reason.PAUSED, None, "scheduling is paused")
    if ledger_today is not None and len(ledger_today.occupying) >= config.max_posts_per_day:
        holder = ledger_today.occupying[0]
        return result(
            Action.NOTHING,
            Reason.DAY_ALREADY_USED,
            None,
            f"ledger: {today.isoformat()} is used by post {holder.post_id} ({holder.state.value})",
        )
    used = _used_today_by_posts(snapshot, today, tz)
    if len(used) >= config.max_posts_per_day:
        return result(
            Action.NOTHING,
            Reason.DAY_ALREADY_USED,
            None,
            f"post records show a publication or possible publication today: {', '.join(used)}",
        )
    if winner is None:
        return result(Action.NOTHING, Reason.NO_POST_DUE, None)
    return result(Action.PUBLISH, Reason.DUE, winner)


def occupied_dates(snapshot: QueueSnapshot, *, exclude: frozenset[str] = frozenset()) -> dict[str, str]:
    """Map each scheduled date to the post holding it. Archived posts hold nothing."""
    held: dict[str, str] = {}
    for post in snapshot.posts:
        if post.id in exclude or post.scheduled_date is None or post.state is LifecycleState.ARCHIVED:
            continue
        held.setdefault(post.scheduled_date, post.id)
    return held


def next_free_date(taken: set[str], start: date) -> date:
    day = start
    while day.isoformat() in taken:
        day += timedelta(days=1)
    return day
