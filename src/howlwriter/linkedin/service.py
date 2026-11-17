"""Queue management operations: drafting, review hand-off, scheduling, pause, archive.

Every operation is a read, a change, and a compare-and-swap write, with an
audit event recorded in the same write. Nothing here sends anything anywhere.

Verification reports and approvals are separate artifacts. This service only
attaches a reference to one after an injected verifier accepts it, and the
default verifier refuses everything. Reports are checked by
``verification.ReportVerifier`` and approvals by ``approval.ApprovalVerifier``;
there is no placeholder approval.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Protocol

from howlwriter.linkedin.checks import CheckFinding, check_post, has_errors
from howlwriter.linkedin.config import PublisherConfig
from howlwriter.linkedin.models import (
    EDITABLE_STATES,
    RESCHEDULABLE_STATES,
    ArtifactRef,
    AttemptOutcome,
    HistoryEvent,
    LifecycleState,
    MediaRef,
    Post,
    format_utc,
    parse_local_date,
    require_transition,
)
from howlwriter.linkedin.scheduler import Evaluation, assess_post, evaluate, local_date, occupied_dates
from howlwriter.linkedin.store import ControlState, LedgerEntryState, QueueStore

S = LifecycleState

#: States in which a verification report may be attached or refreshed.
VERIFIABLE_STATES = frozenset({S.DRAFT, S.READY_FOR_REVIEW, S.APPROVED, S.SCHEDULED, S.FAILED})
#: Why a local command may not move an approved post.
APPROVED_MOVE_REFUSAL = (
    "an approved post is moved only by the approval workflow (action authorize-schedule), which "
    "records that the approver authorized the new slot; a local move would be blocked at publish time"
)


class OperationRefused(ValueError):
    """The operation is not allowed in the current state. Nothing was changed."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ArtifactVerifier(Protocol):
    """Decides whether a verification report or approval record is genuine for a post."""

    def problems(self, kind: str, post: Post, ref: ArtifactRef) -> list[str]: ...


class RefuseAllVerifier:
    """Fail closed default, used whenever no real verifier is supplied."""

    def problems(self, kind: str, post: Post, ref: ArtifactRef) -> list[str]:
        return [f"{kind} artifacts are refused: no trusted verifier is installed for this operation"]


def new_post_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "post"
    return f"{slug}-{secrets.token_hex(4)}"


@dataclass(frozen=True)
class Move:
    post_id: str
    from_date: str
    to_date: str
    from_time: str | None
    to_time: str | None

    def describe(self) -> str:
        return (
            f"{self.from_date} {self.from_time or 'default'} -> {self.to_date} {self.to_time or 'default'}"
        )

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "from_time": self.from_time,
            "to_time": self.to_time,
        }


@dataclass(frozen=True)
class BulkPlan:
    moves: tuple[Move, ...]
    conflicts: tuple[str, ...]

    @property
    def is_applicable(self) -> bool:
        return bool(self.moves) and not self.conflicts

    def to_dict(self) -> dict:
        return {"moves": [move.to_dict() for move in self.moves], "conflicts": list(self.conflicts)}


#: Sentinel meaning "leave the time override as it is".
KEEP = "keep"
#: Value meaning "remove the override and follow the configured default time".
DEFAULT = "default"


class QueueService:
    def __init__(
        self,
        store: QueueStore,
        clock: Clock | None = None,
        *,
        id_factory: Callable[[str], str] = new_post_id,
        verifier: ArtifactVerifier | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self._id_factory = id_factory
        self._verifier = verifier or RefuseAllVerifier()

    # Helpers

    def _now(self) -> str:
        return format_utc(self.clock.now())

    def _event(self, actor: str, action: str, detail: str = "") -> HistoryEvent:
        actor = actor.strip()
        if not actor:
            raise OperationRefused("an actor is required for the audit trail")
        return HistoryEvent(at=self._now(), actor=actor, action=action, detail=detail)

    def _save(self, post: Post, original: Post, event: HistoryEvent) -> Post:
        updated = replace(post, updated_at=event.at, history=original.history + (event,))
        return self.store.save_post(updated, expected_revision=original.revision)

    def _today(self, config: PublisherConfig) -> date:
        return local_date(self.clock.now(), config.tzinfo)

    def _check_slot(
        self, config: PublisherConfig, post_id: str | None, day: str | None, slot: str | None
    ) -> None:
        """Refuse a schedule that is unsupported, in the past, or collides with another post."""
        if slot is not None and slot not in config.allowed_publish_times:
            raise OperationRefused(
                f"time {slot} is not a supported slot {list(config.allowed_publish_times)}; supporting a new "
                "time needs an explicit schedule configuration change, not a per-post override"
            )
        if day is None:
            return
        target = parse_local_date(day)
        if target < self._today(config):
            raise OperationRefused(f"{day} is in the past ({config.timezone})")
        exclude = frozenset({post_id}) if post_id else frozenset()
        holder = occupied_dates(self.store.load_snapshot(), exclude=exclude).get(day)
        if holder is not None:
            raise OperationRefused(
                f"{day} already holds post {holder}; only {config.max_posts_per_day} post per day is allowed"
            )

    # Drafting and editing

    def add_draft(
        self,
        *,
        title: str,
        text: str,
        actor: str,
        urls: tuple[str, ...] = (),
        media: tuple[MediaRef, ...] = (),
        scheduled_date: str | None = None,
        scheduled_time: str | None = None,
    ) -> Post:
        config = self.store.load_config()
        with self.store.lock():
            self._check_slot(config, None, scheduled_date, scheduled_time)
            event = self._event(actor, "created")
            post = Post(
                id=self._id_factory(title),
                title=title,
                text=text,
                urls=tuple(urls),
                media=tuple(media),
                created_at=event.at,
                updated_at=event.at,
                timezone=config.timezone,
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time,
                history=(event,),
            )
            return self.store.create_post(post)

    def update_content(
        self,
        post_id: str,
        *,
        actor: str,
        title: str | None = None,
        text: str | None = None,
        urls: tuple[str, ...] | None = None,
        media: tuple[MediaRef, ...] | None = None,
    ) -> Post:
        """Edit a post. Any change to text, links or media discards verification and approval."""
        with self.store.lock():
            original = self.store.load_post(post_id)
            if original.state not in EDITABLE_STATES:
                raise OperationRefused(f"a {original.state.value} post cannot be edited")
            edited = replace(
                original,
                title=original.title if title is None else title,
                text=original.text if text is None else text,
                urls=original.urls if urls is None else tuple(urls),
                media=original.media if media is None else tuple(media),
            )
            if edited.computed_fingerprint() == original.computed_fingerprint():
                if edited.title == original.title:
                    return original
                return self._save(edited, original, self._event(actor, "retitled"))
            invalidated = [
                name
                for name, ref in (
                    ("verification", original.verification_ref),
                    ("approval", original.approval_ref),
                )
                if ref is not None
            ]
            detail = f"invalidated: {', '.join(invalidated)}" if invalidated else ""
            edited = replace(edited, state=S.DRAFT, verification_ref=None, approval_ref=None)
            return self._save(edited, original, self._event(actor, "content_edited", detail))

    def validate(self, post_id: str) -> list[CheckFinding]:
        return check_post(self.store.load_post(post_id), self.store.load_config(), self.store)

    # Lifecycle

    def _transition(
        self, post_id: str, target: LifecycleState, actor: str, action: str, detail: str = ""
    ) -> Post:
        with self.store.lock():
            original = self.store.load_post(post_id)
            require_transition(original.state, target)
            return self._save(replace(original, state=target), original, self._event(actor, action, detail))

    def submit_for_review(self, post_id: str, *, actor: str) -> Post:
        findings = self.validate(post_id)
        if has_errors(findings):
            errors = "; ".join(f.message for f in findings if f.severity == "error")
            raise OperationRefused(f"the post has blocking findings: {errors}")
        return self._transition(post_id, S.READY_FOR_REVIEW, actor, "submitted_for_review")

    def return_to_draft(self, post_id: str, *, actor: str) -> Post:
        """Withdraw a post from review or approval. Approval and verification are discarded."""
        with self.store.lock():
            original = self.store.load_post(post_id)
            require_transition(original.state, S.DRAFT)
            reset = replace(original, state=S.DRAFT, approval_ref=None, verification_ref=None)
            return self._save(reset, original, self._event(actor, "returned_to_draft"))

    def attach_verification(self, post_id: str, ref: ArtifactRef, *, actor: str) -> Post:
        """Record a verification report the trusted verifier accepted.

        Before approval this attaches the report. After approval it refreshes the
        report for unchanged content (revalidation shortly before publication);
        the approval stays because the content fingerprint is the same.
        """
        with self.store.lock():
            original = self.store.load_post(post_id)
            if original.state not in VERIFIABLE_STATES:
                raise OperationRefused(f"verification cannot be attached to a {original.state.value} post")
            self._require_artifact("verification", original, ref)
            action = (
                "verification_attached"
                if original.state in (S.DRAFT, S.READY_FOR_REVIEW)
                else "verification_refreshed"
            )
            return self._save(
                replace(original, verification_ref=ref),
                original,
                self._event(actor, action, ref.path),
            )

    def withdraw_verification(self, post_id: str, *, actor: str, detail: str) -> Post:
        """Record that verification blocked the post. Fail closed.

        Any attached report is removed. A post that was already approved or
        scheduled goes back to DRAFT and loses its approval, so it cannot be
        published on the strength of an older, better result.
        """
        with self.store.lock():
            original = self.store.load_post(post_id)
            if original.state not in VERIFIABLE_STATES:
                raise OperationRefused(f"a {original.state.value} post cannot be verified")
            if original.state in (S.DRAFT, S.READY_FOR_REVIEW):
                changed = replace(original, verification_ref=None)
            else:
                require_transition(original.state, S.DRAFT)
                changed = replace(original, state=S.DRAFT, verification_ref=None, approval_ref=None)
            return self._save(changed, original, self._event(actor, "verification_blocked", detail))

    def approve(self, post_id: str, ref: ArtifactRef, *, actor: str) -> Post:
        """Record an approval that the trusted verifier accepted. Never self-authorizing."""
        with self.store.lock():
            original = self.store.load_post(post_id)
            require_transition(original.state, S.APPROVED)
            if not original.verification_is_current:
                raise OperationRefused("approval requires a verification report for the current content")
            self._require_artifact("approval", original, ref)
            return self._save(
                replace(original, state=S.APPROVED, approval_ref=ref),
                original,
                self._event(actor, "approved", ref.path),
            )

    def _require_artifact(self, kind: str, post: Post, ref: ArtifactRef) -> None:
        if ref.content_fingerprint != post.computed_fingerprint():
            raise OperationRefused(f"the {kind} artifact was made for different content")
        problems = self._verifier.problems(kind, post, ref)
        if problems:
            raise OperationRefused("; ".join(problems))

    def schedule(self, post_id: str, *, actor: str) -> Post:
        config = self.store.load_config()
        with self.store.lock():
            original = self.store.load_post(post_id)
            require_transition(original.state, S.SCHEDULED)
            if original.state is S.FAILED:
                raise OperationRefused("a FAILED post must be rescheduled, which re-queues it explicitly")
            self._require_schedulable(config, original, original.scheduled_date, original.scheduled_time)
            return self._save(replace(original, state=S.SCHEDULED), original, self._event(actor, "scheduled"))

    def _require_schedulable(
        self, config: PublisherConfig, post: Post, day: str | None, slot: str | None
    ) -> None:
        if day is None:
            raise OperationRefused("the post has no scheduled date")
        if not post.approval_is_current:
            raise OperationRefused("the post has no approval for its current content")
        self._check_slot(config, post.id, day, slot or config.default_publish_time)

    def cancel(self, post_id: str, *, actor: str) -> Post:
        """Take one post out of the publishing queue. Its approval is kept."""
        return self._transition(post_id, S.APPROVED, actor, "schedule_cancelled")

    def archive(self, post_id: str, *, actor: str) -> Post:
        """Archive the local record. This never deletes anything from LinkedIn."""
        with self.store.lock():
            original = self.store.load_post(post_id)
            require_transition(original.state, S.ARCHIVED)
            detail = "local record only; the LinkedIn post is untouched" if original.linkedin_post_id else ""
            return self._save(
                replace(original, state=S.ARCHIVED), original, self._event(actor, "archived", detail)
            )

    # Scheduling

    def reschedule(
        self,
        post_id: str,
        *,
        actor: str,
        new_date: str | None = None,
        new_time: str = KEEP,
        authorized: bool = False,
    ) -> Post:
        """Change one post's date or time. A scheduling change keeps verification and approval.

        An approved post can only be moved by the approval workflow
        (``authorize-schedule``), which passes ``authorized=True`` and records a
        signed schedule authorization. A local move of an approved post is
        refused: the approval gate would block it at publish time.

        A FAILED post is put back in the queue by this call: that is the only
        retry path, and it is always an explicit, audited human action.
        """
        config = self.store.load_config()
        with self.store.lock():
            original = self.store.load_post(post_id)
            if original.state not in RESCHEDULABLE_STATES:
                raise OperationRefused(f"a {original.state.value} post cannot be rescheduled")
            day = original.scheduled_date if new_date is None else new_date
            slot = (
                original.scheduled_time if new_time == KEEP else (None if new_time == DEFAULT else new_time)
            )
            if day is None:
                raise OperationRefused("a date is required: the post has none yet")
            changes_slot = day != original.scheduled_date or slot != original.scheduled_time
            if original.approval_ref is not None and changes_slot and not authorized:
                raise OperationRefused(APPROVED_MOVE_REFUSAL)
            moved = replace(original, scheduled_date=day, scheduled_time=slot)
            if original.state is S.FAILED:
                self._require_schedulable(config, moved, day, slot)
                moved = replace(moved, state=S.SCHEDULED)
            else:
                self._check_slot(config, post_id, day, slot or config.default_publish_time)
            before = Move(post_id, original.scheduled_date or "none", day, original.scheduled_time, slot)
            detail = before.describe()
            return self._save(moved, original, self._event(actor, "rescheduled", detail))

    def plan_bulk_reschedule(
        self, *, shift_days: int = 0, new_time: str = KEEP, from_date: str | None = None
    ) -> BulkPlan:
        """Plan moving every eligible future post. Nothing is written."""
        config = self.store.load_config()
        today = self._today(config)
        start = max(today, parse_local_date(from_date)) if from_date else today
        snapshot = self.store.load_snapshot()
        conflicts: list[str] = [f"invalid post file: {item.path}" for item in snapshot.invalid]
        if shift_days == 0 and new_time == KEEP:
            conflicts.append("nothing to change: give a day shift or a time")
        if new_time not in (KEEP, DEFAULT) and new_time not in config.allowed_publish_times:
            conflicts.append(f"time {new_time} is not a supported slot {list(config.allowed_publish_times)}")
        eligible = [
            post
            for post in snapshot.posts
            if post.state in RESCHEDULABLE_STATES
            and post.state is not S.FAILED
            and post.scheduled_date is not None
            and parse_local_date(post.scheduled_date) >= start
        ]
        moves: list[Move] = []
        fixed = occupied_dates(snapshot, exclude=frozenset(post.id for post in eligible))
        targets: dict[str, str] = {}
        for post in sorted(eligible, key=lambda item: (item.scheduled_date or "", item.id)):
            target = (parse_local_date(post.scheduled_date or "") + timedelta(days=shift_days)).isoformat()
            slot = post.scheduled_time if new_time == KEEP else (None if new_time == DEFAULT else new_time)
            if parse_local_date(target) < today:
                conflicts.append(f"{post.id} would move to {target}, which is in the past")
            if target in fixed:
                conflicts.append(f"{post.id} would move to {target}, already held by {fixed[target]}")
            if target in targets:
                conflicts.append(f"{post.id} and {targets[target]} would both land on {target}")
            targets.setdefault(target, post.id)
            if target != post.scheduled_date or slot != post.scheduled_time:
                if post.approval_ref is not None:
                    conflicts.append(f"{post.id} is approved: {APPROVED_MOVE_REFUSAL}")
                moves.append(Move(post.id, post.scheduled_date or "", target, post.scheduled_time, slot))
        return BulkPlan(moves=tuple(moves), conflicts=tuple(conflicts))

    def apply_bulk_reschedule(
        self, *, actor: str, shift_days: int = 0, new_time: str = KEEP, from_date: str | None = None
    ) -> BulkPlan:
        """Re-plan under the lock and apply only a conflict free plan. All posts or none."""
        with self.store.lock():
            plan = self.plan_bulk_reschedule(shift_days=shift_days, new_time=new_time, from_date=from_date)
            if not plan.is_applicable:
                return plan
            originals = {move.post_id: self.store.load_post(move.post_id) for move in plan.moves}
            for move in plan.moves:
                original = originals[move.post_id]
                detail = f"bulk: {move.describe()}"
                moved = replace(original, scheduled_date=move.to_date, scheduled_time=move.to_time)
                self._save(moved, original, self._event(actor, "rescheduled", detail))
            return plan

    # Global pause

    def set_paused(self, paused: bool, *, actor: str, reason: str = "") -> ControlState:
        with self.store.lock():
            control = self.store.load_control()
            if control.paused == paused:
                return control
            event = self._event(actor, "paused" if paused else "resumed", reason)
            return self.store.save_control(
                replace(control, paused=paused, history=control.history + (event,)), control.revision
            )

    # Reconciliation of an uncertain publication

    def reconcile(
        self, post_id: str, *, actor: str, was_published: bool, linkedin_post_id: str | None = None
    ) -> Post:
        """Resolve an UNCERTAIN post after a human checked LinkedIn. The only exit from UNCERTAIN."""
        with self.store.lock():
            original = self.store.load_post(post_id)
            if original.state is not S.UNCERTAIN or original.last_attempt is None:
                raise OperationRefused("only an UNCERTAIN post can be reconciled")
            attempt = original.last_attempt
            if was_published and not (linkedin_post_id or "").strip():
                raise OperationRefused("the LinkedIn post ID or URL is required to record a publication")
            if not was_published and linkedin_post_id:
                raise OperationRefused("a LinkedIn post ID was given for a post reported as not published")
            event = self._event(
                actor, "reconciled", "confirmed published" if was_published else "confirmed not published"
            )
            outcome = AttemptOutcome.SUCCESS if was_published else AttemptOutcome.FAILED
            resolved = replace(
                attempt, outcome=outcome, detail=f"{attempt.detail} | reconciled by {actor}".strip(" |")
            )
            updated = replace(
                original,
                state=S.PUBLISHED if was_published else S.FAILED,
                linkedin_post_id=linkedin_post_id.strip() if was_published and linkedin_post_id else None,
                attempts=original.attempts[:-1] + (resolved,),
            )
            saved = self._save(updated, original, event)
            located = self.store.find_ledger_entry(attempt.attempt_id)
            if located is not None:
                day, _entry = located
                state = LedgerEntryState.PUBLISHED if was_published else LedgerEntryState.RELEASED
                self.store.update_ledger_entry(day, attempt.attempt_id, state, event.at)
            return saved

    # Read only views

    def evaluate(self) -> Evaluation:
        """Dry scheduling evaluation: what a run starting now would do. Never mutates."""
        config = self.store.load_config()
        now = self.clock.now()
        return evaluate(
            config,
            self.store.load_control(),
            self.store.load_snapshot(),
            self.store.load_ledger_day(local_date(now, config.tzinfo)),
            now,
        )

    def preview_queue(self) -> list[dict]:
        """Upcoming and unresolved posts in schedule order, with a plain status for each."""
        config = self.store.load_config()
        now = self.clock.now()
        rows = []
        for post in self.store.load_snapshot().posts:
            if post.state in (S.ARCHIVED, S.PUBLISHED):
                continue
            assessment = assess_post(post, config, now) if post.state is S.SCHEDULED else None
            rows.append(
                {
                    "id": post.id,
                    "title": post.title,
                    "state": post.state.value,
                    "scheduled_date": post.scheduled_date,
                    "scheduled_time": post.scheduled_time or config.default_publish_time,
                    "time_is_override": post.scheduled_time is not None,
                    "queue_status": assessment.status.value if assessment else None,
                    "reasons": list(assessment.reasons) if assessment else [],
                    "verification": "current" if post.verification_is_current else "none",
                    "approval": "current" if post.approval_is_current else "none",
                }
            )
        rows.sort(key=lambda row: (row["scheduled_date"] is None, row["scheduled_date"] or "", row["id"]))
        return rows
