"""The publishing run: decide, persist intent, send once, persist the outcome.

This module contains no LinkedIn code. The transport is an injected protocol
(the real one arrives in M4; tests use fakes) and so are the gates that must
all agree before anything is sent. The default gate refuses everything, so a
coordinator built without real verification and approval gates cannot publish.

Order of operations for a real run, each step persisted before the next:

1. Recover: a post left in PUBLISHING by an interrupted run becomes UNCERTAIN.
   It is never retried automatically.
2. Evaluate the queue (pure scheduler).
3. Claim the local day in the ledger (publishing intent, exclusive).
4. Move the post to PUBLISHING with a PENDING attempt.
5. Checkpoint, so the intent is durable outside this process (a git push in M4).
6. Call the transport exactly once.
7. Persist PUBLISHED, FAILED (definitely not sent) or UNCERTAIN (cannot tell).
"""

from __future__ import annotations

import enum
import secrets
from dataclasses import dataclass, replace
from datetime import date
from typing import Callable, Protocol, Sequence

from howlwriter.linkedin.models import (
    MAX_DETAIL_CHARS,
    AttemptOutcome,
    HistoryEvent,
    LifecycleState,
    Post,
    PublishAttempt,
    format_utc,
    parse_utc,
)
from howlwriter.linkedin.scheduler import Action, Evaluation, evaluate, local_date
from howlwriter.linkedin.service import Clock, SystemClock
from howlwriter.linkedin.store import (
    DayAlreadyClaimedError,
    LedgerCorruptError,
    LedgerEntry,
    LedgerEntryState,
    QueueStore,
)

S = LifecycleState
ACTOR = "publisher"


@dataclass(frozen=True)
class TransportResult:
    """What the transport knows after one send. AMBIGUOUS means it cannot tell."""

    outcome: AttemptOutcome
    linkedin_post_id: str | None = None
    detail: str = ""


class PostTransport(Protocol):
    def publish(self, post: Post) -> TransportResult: ...


class PublishGate(Protocol):
    """A precondition for sending. Returns the reasons it blocks, or an empty list."""

    def blockers(self, post: Post) -> list[str]: ...


class RefuseAllGate:
    """Fail closed default: a coordinator built without real gates cannot publish."""

    def blockers(self, post: Post) -> list[str]:
        return ["no trusted verification and approval gates are installed (see approval.publish_gates)"]


class RunOutcome(str, enum.Enum):
    NOTHING = "NOTHING"
    BLOCKED = "BLOCKED"
    DRY_RUN = "DRY_RUN"
    DISABLED = "DISABLED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class RunReport:
    outcome: RunOutcome
    evaluation: Evaluation | None
    post_id: str | None = None
    messages: tuple[str, ...] = ()
    recovered: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "post_id": self.post_id,
            "messages": list(self.messages),
            "recovered": list(self.recovered),
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
        }


def _new_attempt_id() -> str:
    return f"attempt-{secrets.token_hex(6)}"


def _kind(error: BaseException) -> str:
    """Name an error without its message, which may carry a token or a credentialed URL."""
    return type(error).__name__


def _clip(text: str) -> str:
    return text if len(text) <= MAX_DETAIL_CHARS else text[: MAX_DETAIL_CHARS - 3] + "..."


class PublishCoordinator:
    def __init__(
        self,
        store: QueueStore,
        transport: PostTransport,
        *,
        clock: Clock | None = None,
        gates: Sequence[PublishGate] | None = None,
        checkpoint: Callable[[str], None] | None = None,
        attempt_id_factory: Callable[[], str] = _new_attempt_id,
    ) -> None:
        self.store = store
        self.transport = transport
        self.clock = clock or SystemClock()
        # An empty gate list would mean "no checks"; that is never accepted.
        self.gates: tuple[PublishGate, ...] = tuple(gates) if gates else (RefuseAllGate(),)
        self.checkpoint = checkpoint or (lambda label: None)
        self._attempt_id_factory = attempt_id_factory

    def run(self) -> RunReport:
        with self.store.lock():
            config = self.store.load_config()
            real_run = config.publishing_enabled and not config.dry_run
            recovered: tuple[str, ...] = ()
            messages: list[str] = []
            if real_run:
                recovered = self._recover_interrupted()
                if recovered:
                    try:
                        self.checkpoint("recovery")
                    except Exception as error:
                        messages.append(
                            f"recovery was saved locally but the checkpoint failed ({_kind(error)})"
                        )
            now = self.clock.now()
            today = local_date(now, config.tzinfo)
            evaluation = evaluate(
                config,
                self.store.load_control(),
                self.store.load_snapshot(),
                self.store.load_ledger_day(today),
                now,
            )

            def report(outcome: RunOutcome, post_id: str | None = None, *extra: str) -> RunReport:
                return RunReport(outcome, evaluation, post_id, tuple(messages) + tuple(extra), recovered)

            if evaluation.action is Action.BLOCKED:
                return report(RunOutcome.BLOCKED, None, *evaluation.notes)
            if evaluation.action is not Action.PUBLISH or evaluation.candidate_id is None:
                return report(RunOutcome.NOTHING, None, *evaluation.notes)
            post = self.store.load_post(evaluation.candidate_id)
            # The gates only read, so a dry run evaluates them too and rehearses the real decision.
            blockers = [reason for gate in self.gates for reason in gate.blockers(post)]
            if config.dry_run:
                if blockers:
                    return report(
                        RunOutcome.BLOCKED, post.id, "dry run: a real run would block this post", *blockers
                    )
                return report(
                    RunOutcome.DRY_RUN, post.id, "dry run: this post would be sent; nothing was sent"
                )
            if not config.publishing_enabled:
                return report(RunOutcome.DISABLED, post.id, "publishing is disabled; nothing was sent")
            if blockers:
                return report(RunOutcome.BLOCKED, post.id, *blockers)

            # Intent: claim the day, then mark the post, then make both durable.
            started = format_utc(now)
            attempt = PublishAttempt(
                attempt_id=self._attempt_id_factory(),
                started_at=started,
                content_fingerprint=post.computed_fingerprint(),
            )
            entry = LedgerEntry(
                post_id=post.id,
                attempt_id=attempt.attempt_id,
                content_fingerprint=attempt.content_fingerprint,
                state=LedgerEntryState.INTENT,
                claimed_at=started,
                updated_at=started,
            )
            try:
                self.store.claim_day(today, entry, config.max_posts_per_day)
            except DayAlreadyClaimedError as error:
                return report(RunOutcome.NOTHING, post.id, str(error))
            publishing = self._save(
                replace(post, state=S.PUBLISHING, attempts=post.attempts + (attempt,)),
                post,
                "publish_intent",
                attempt.attempt_id,
            )
            try:
                self.checkpoint("intent")
            except Exception as error:
                # Nothing was sent, so this is a definite non-publication.
                detail = f"intent could not be made durable ({_kind(error)}); nothing was sent"
                self._finish(publishing, today, AttemptOutcome.FAILED, None, detail)
                return report(RunOutcome.FAILED, post.id, detail)

            try:
                result = self.transport.publish(publishing)
            except Exception as error:
                # An unexpected transport error may hide a completed request.
                result = TransportResult(AttemptOutcome.AMBIGUOUS, None, f"transport raised {_kind(error)}")
            outcome, linkedin_id, detail = self._normalize(result)
            self._finish(publishing, today, outcome, linkedin_id, detail)
            try:
                self.checkpoint("outcome")
            except Exception as error:
                messages.append(
                    f"the outcome was saved locally but the checkpoint failed ({_kind(error)}). "
                    "The durable copy still shows PUBLISHING, so the next run will mark it UNCERTAIN "
                    "instead of sending again."
                )
            mapping = {
                AttemptOutcome.SUCCESS: RunOutcome.PUBLISHED,
                AttemptOutcome.FAILED: RunOutcome.FAILED,
                AttemptOutcome.AMBIGUOUS: RunOutcome.UNCERTAIN,
            }
            return report(mapping[outcome], post.id, detail)

    # Internals

    def _save(self, post: Post, original: Post, action: str, detail: str = "") -> Post:
        at = format_utc(self.clock.now())
        event = HistoryEvent(at=at, actor=ACTOR, action=action, detail=detail)
        return self.store.save_post(
            replace(post, updated_at=max(at, original.updated_at), history=original.history + (event,)),
            original.revision,
        )

    @staticmethod
    def _normalize(result: object) -> tuple[AttemptOutcome, str | None, str]:
        """Reduce a transport answer to a safe outcome. Anything unclear is AMBIGUOUS."""
        if not isinstance(result, TransportResult) or result.outcome is AttemptOutcome.PENDING:
            return AttemptOutcome.AMBIGUOUS, None, "the transport returned an unusable result"
        detail = _clip(result.detail if isinstance(result.detail, str) else "")
        if result.outcome is AttemptOutcome.SUCCESS:
            identifier = result.linkedin_post_id
            if not isinstance(identifier, str) or not identifier.strip() or "\n" in identifier:
                return (
                    AttemptOutcome.AMBIGUOUS,
                    None,
                    "success was reported without a usable LinkedIn post ID",
                )
            return AttemptOutcome.SUCCESS, identifier.strip()[:200], detail
        return result.outcome, None, detail

    def _finish(
        self, publishing: Post, day, outcome: AttemptOutcome, linkedin_id: str | None, detail: str
    ) -> Post:
        attempt = publishing.attempts[-1]
        finished = format_utc(self.clock.now())
        closed = replace(
            attempt, outcome=outcome, finished_at=max(finished, attempt.started_at), detail=detail
        )
        state = {
            AttemptOutcome.SUCCESS: S.PUBLISHED,
            AttemptOutcome.FAILED: S.FAILED,
            AttemptOutcome.AMBIGUOUS: S.UNCERTAIN,
        }[outcome]
        ledger_state = {
            AttemptOutcome.SUCCESS: LedgerEntryState.PUBLISHED,
            AttemptOutcome.FAILED: LedgerEntryState.RELEASED,
            AttemptOutcome.AMBIGUOUS: LedgerEntryState.UNCERTAIN,
        }[outcome]
        saved = self._save(
            replace(
                publishing,
                state=state,
                attempts=publishing.attempts[:-1] + (closed,),
                linkedin_post_id=linkedin_id,
            ),
            publishing,
            f"publish_{outcome.value.lower()}",
            detail,
        )
        self.store.update_ledger_entry(day, attempt.attempt_id, ledger_state, finished)
        return saved

    def _recover_interrupted(self) -> tuple[str, ...]:
        """Resolve what an interrupted run left behind, without ever sending again."""
        config = self.store.load_config()
        recovered: list[str] = []
        snapshot = self.store.load_snapshot()
        for post in snapshot.posts:
            if post.state is not S.PUBLISHING or post.last_attempt is None:
                continue
            attempt = post.last_attempt
            day = local_date(parse_utc(attempt.started_at), config.tzinfo)
            now = format_utc(self.clock.now())
            located = self.store.find_ledger_entry(attempt.attempt_id)
            if located is None:
                # The post says an attempt started but the ledger lost it: restore the claim.
                current = self.store.load_ledger_day(day)
                entry = LedgerEntry(
                    post.id,
                    attempt.attempt_id,
                    attempt.content_fingerprint,
                    LedgerEntryState.UNCERTAIN,
                    now,
                    now,
                )
                if current is None:
                    self.store.claim_day(day, entry, config.max_posts_per_day)
                else:
                    self.store.claim_day(day, entry, len(current.occupying) + 1)
            detail = "the run was interrupted after the intent was saved; the request may have been sent"
            self._finish(post, located[0] if located else day, AttemptOutcome.AMBIGUOUS, None, detail)
            recovered.append(post.id)

        # An INTENT entry left behind. If the post never recorded the attempt, nothing was
        # sent: release the day. If the post already closed the attempt (the run stopped
        # between saving the post and updating the ledger), copy the post's outcome.
        # Every ledger day is examined, not only today: a crash on day D must be repaired on D+1.
        closed_states = {
            AttemptOutcome.SUCCESS: LedgerEntryState.PUBLISHED,
            AttemptOutcome.FAILED: LedgerEntryState.RELEASED,
            AttemptOutcome.AMBIGUOUS: LedgerEntryState.UNCERTAIN,
        }
        for day in self._ledger_days():
            ledger = self.store.load_ledger_day(day)
            for entry in ledger.entries if ledger else ():
                if entry.state is not LedgerEntryState.INTENT:
                    continue
                owner = self.store.load_snapshot().by_id(entry.post_id)
                attempts = owner.attempts if owner else ()
                attempt = next((a for a in attempts if a.attempt_id == entry.attempt_id), None)
                if attempt is None:
                    state = LedgerEntryState.RELEASED
                elif owner.state is not S.PUBLISHING and attempt.outcome in closed_states:
                    state = closed_states[attempt.outcome]
                else:
                    continue
                self.store.update_ledger_entry(day, entry.attempt_id, state, format_utc(self.clock.now()))
                recovered.append(f"ledger:{entry.attempt_id}")
        return tuple(recovered)

    def _ledger_days(self) -> list[date]:
        """Every day that has a ledger file, oldest first."""
        ledger_root = self.store.root / "ledger"
        if not ledger_root.is_dir():
            return []
        days: list[date] = []
        for path in sorted(ledger_root.glob("*/*.json")):
            try:
                days.append(date.fromisoformat(path.stem))
            except ValueError:
                raise LedgerCorruptError(f"unexpected file in the ledger: {path.name}")
        return days
