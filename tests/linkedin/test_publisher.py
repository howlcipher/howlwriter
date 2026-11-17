"""The publish run with mocked transports: intent, one per day, ambiguity, crashes, gates.

Every transport here is a scripted fake. Passing these tests shows the queue
and ledger logic is right; it shows nothing about the live LinkedIn API.
"""

import random
from datetime import date

import pytest

from howlwriter.linkedin.models import AttemptOutcome, LifecycleState
from howlwriter.linkedin.publisher import PublishCoordinator, RunOutcome, TransportResult
from howlwriter.linkedin.service import OperationRefused
from howlwriter.linkedin.store import LedgerEntryState
from tests.linkedin.helpers import (
    FakeTransport,
    ambiguous,
    failure,
    go_live,
    make_coordinator,
    scheduled_post,
    success,
    write_config,
)

S = LifecycleState
DAY = date(2026, 11, 16)
SLOT = "2026-11-16T13:30:00Z"


@pytest.fixture
def due(service, store, clock):
    """One approved post due right now, with publishing switched on."""
    go_live(store)
    post = scheduled_post(service, "Due today", "2026-11-16")
    clock.set(SLOT)
    return post


def ledger_states(store, day=DAY):
    ledger = store.load_ledger_day(day)
    return [entry.state for entry in ledger.entries] if ledger else []


# Switches and gates


def test_default_configuration_never_calls_the_transport(service, store, clock):
    post = scheduled_post(service, "Due today", "2026-11-16")
    clock.set(SLOT)
    transport = FakeTransport()
    report = make_coordinator(store, clock, transport).run()
    assert (report.outcome, report.post_id) == (RunOutcome.DRY_RUN, post.id)
    assert transport.calls == [] and store.load_ledger_day(DAY) is None
    assert store.load_post(post.id) == post


@pytest.mark.parametrize(
    "switches, expected",
    [
        ({"publishing_enabled": True, "dry_run": True}, RunOutcome.DRY_RUN),
        ({"publishing_enabled": False, "dry_run": False}, RunOutcome.DISABLED),
    ],
)
def test_both_switches_are_required(service, store, clock, switches, expected):
    write_config(store, **switches)
    scheduled_post(service, "Due today", "2026-11-16")
    clock.set(SLOT)
    transport = FakeTransport()
    assert make_coordinator(store, clock, transport).run().outcome is expected
    assert transport.calls == [] and store.load_ledger_day(DAY) is None


def test_default_gate_refuses_everything(due, store, clock):
    transport = FakeTransport()
    report = PublishCoordinator(store, transport, clock=clock).run()
    assert report.outcome is RunOutcome.BLOCKED and "no trusted verification and approval gates" in report.messages[0]
    assert transport.calls == [] and store.load_post(due.id).state is S.SCHEDULED


def test_an_empty_gate_list_does_not_mean_no_gates(due, store, clock):
    transport = FakeTransport()
    assert PublishCoordinator(store, transport, clock=clock, gates=[]).run().outcome is RunOutcome.BLOCKED
    assert transport.calls == []


def test_any_blocking_gate_stops_the_send(due, store, clock):
    class Blocker:
        def blockers(self, post):
            return ["verification verdict is REJECT"]

    transport = FakeTransport()
    report = make_coordinator(store, clock, transport, gates=[Blocker()]).run()
    assert report.outcome is RunOutcome.BLOCKED and report.messages == ("verification verdict is REJECT",)
    assert transport.calls == [] and store.load_ledger_day(DAY) is None


def test_a_dry_run_reports_what_the_gates_would_block(service, store, clock):
    """Review finding: a dry run said "would be sent" for posts the real run blocks."""
    class Blocker:
        def blockers(self, post):
            return ["the approval is 31 day(s) old (limit 30)"]

    write_config(store, publishing_enabled=True, dry_run=True)
    post = scheduled_post(service, "Due today", "2026-11-16")
    clock.set(SLOT)
    transport = FakeTransport()
    report = make_coordinator(store, clock, transport, gates=[Blocker()]).run()
    assert report.outcome is RunOutcome.BLOCKED and report.post_id == post.id
    assert report.messages == (
        "dry run: a real run would block this post",
        "the approval is 31 day(s) old (limit 30)",
    )
    assert transport.calls == [] and store.load_ledger_day(DAY) is None and store.load_post(post.id) == post


# Success, failure, ambiguity


def test_successful_publication_is_recorded_everywhere(due, store, clock):
    transport = FakeTransport(success("urn:li:share:42"))
    report = make_coordinator(store, clock, transport).run()
    post = store.load_post(due.id)
    assert report.outcome is RunOutcome.PUBLISHED and transport.calls == [due.id]
    assert post.state is S.PUBLISHED and post.linkedin_post_id == "urn:li:share:42"
    assert post.attempts[-1].outcome is AttemptOutcome.SUCCESS
    assert post.attempts[-1].content_fingerprint == due.computed_fingerprint()
    assert [e.action for e in post.history][-2:] == ["publish_intent", "publish_success"]
    assert ledger_states(store) == [LedgerEntryState.PUBLISHED]


def test_intent_is_persisted_before_the_transport_is_called(due, store, clock):
    seen = {}

    class Inspecting:
        def publish(self, post):
            stored = store.load_post(post.id)
            seen["state"] = stored.state
            seen["attempt"] = stored.attempts[-1].outcome
            seen["ledger"] = ledger_states(store)
            return success()

    labels = []
    make_coordinator(store, clock, Inspecting(), checkpoint=labels.append).run()
    assert seen == {"state": S.PUBLISHING, "attempt": AttemptOutcome.PENDING, "ledger": [LedgerEntryState.INTENT]}
    assert labels == ["intent", "outcome"]


def test_definite_failure_releases_the_day_and_never_retries_itself(due, store, clock):
    transport = FakeTransport(failure("HTTP 401 invalid token"))
    coordinator = make_coordinator(store, clock, transport)
    assert coordinator.run().outcome is RunOutcome.FAILED
    post = store.load_post(due.id)
    assert post.state is S.FAILED and post.linkedin_post_id is None
    assert ledger_states(store) == [LedgerEntryState.RELEASED]
    clock.advance(minutes=30)
    assert coordinator.run().outcome is RunOutcome.NOTHING
    assert transport.calls == [due.id]


@pytest.mark.parametrize(
    "result",
    [
        ambiguous(),
        TimeoutError("read timed out"),
        TransportResult(AttemptOutcome.SUCCESS, None, "201 without an id header"),
        TransportResult(AttemptOutcome.SUCCESS, "   ", ""),
        TransportResult(AttemptOutcome.PENDING, None, ""),
        "not a result object",
    ],
)
def test_anything_unclear_becomes_uncertain_and_is_never_resent(due, store, clock, result):
    transport = FakeTransport(result)
    coordinator = make_coordinator(store, clock, transport)
    assert coordinator.run().outcome is RunOutcome.UNCERTAIN
    post = store.load_post(due.id)
    assert post.state is S.UNCERTAIN and post.attempts[-1].outcome is AttemptOutcome.AMBIGUOUS
    assert ledger_states(store) == [LedgerEntryState.UNCERTAIN]
    for _ in range(3):
        clock.advance(minutes=20)
        assert coordinator.run().outcome is RunOutcome.NOTHING
    assert transport.calls == [due.id]


def test_uncertain_day_blocks_other_posts_that_day_but_not_the_next(due, service, store, clock):
    tomorrow = scheduled_post(service, "Tomorrow", "2026-11-17")
    transport = FakeTransport(ambiguous(), success("urn:li:share:7"))
    coordinator = make_coordinator(store, clock, transport)
    coordinator.run()
    clock.set("2026-11-17T13:30:00Z")
    assert coordinator.run().outcome is RunOutcome.PUBLISHED
    assert transport.calls == [due.id, tomorrow.id]
    assert store.load_post(due.id).state is S.UNCERTAIN


def test_reconcile_as_published_records_the_id(due, service, store, clock):
    make_coordinator(store, clock, FakeTransport(ambiguous())).run()
    post = service.reconcile(due.id, actor="owner", was_published=True, linkedin_post_id="urn:li:share:99")
    assert post.state is S.PUBLISHED and post.linkedin_post_id == "urn:li:share:99"
    assert ledger_states(store) == [LedgerEntryState.PUBLISHED]
    assert post.history[-1].actor == "owner" and post.history[-1].action == "reconciled"


def test_reconcile_as_not_published_allows_an_explicit_retry(due, service, store, clock):
    transport = FakeTransport(ambiguous(), success("urn:li:share:5"))
    coordinator = make_coordinator(store, clock, transport)
    coordinator.run()
    failed = service.reconcile(due.id, actor="owner", was_published=False)
    assert failed.state is S.FAILED and ledger_states(store) == [LedgerEntryState.RELEASED]
    assert coordinator.run().outcome is RunOutcome.NOTHING, "a FAILED post is not retried on its own"
    # authorized=True stands in for the approval workflow's authorize-schedule action.
    requeued = service.reschedule(
        due.id, actor="owner", new_date="2026-11-16", new_time="09:00", authorized=True
    )
    assert requeued.state is S.SCHEDULED
    clock.set("2026-11-16T14:00:00Z")
    assert coordinator.run().outcome is RunOutcome.PUBLISHED
    assert len(store.load_post(due.id).attempts) == 2 and transport.calls == [due.id, due.id]


def test_reconcile_rules(due, service, store, clock):
    with pytest.raises(OperationRefused):
        service.reconcile(due.id, actor="owner", was_published=True, linkedin_post_id="urn:li:share:1")
    make_coordinator(store, clock, FakeTransport(ambiguous())).run()
    with pytest.raises(OperationRefused, match="required"):
        service.reconcile(due.id, actor="owner", was_published=True)
    with pytest.raises(OperationRefused):
        service.reconcile(due.id, actor="owner", was_published=False, linkedin_post_id="urn:li:share:1")
    assert store.load_post(due.id).state is S.UNCERTAIN


def test_archiving_a_published_post_keeps_the_linkedin_record(due, service, store, clock):
    make_coordinator(store, clock, FakeTransport(success("urn:li:share:42"))).run()
    archived = service.archive(due.id, actor="owner")
    assert archived.state is S.ARCHIVED and archived.linkedin_post_id == "urn:li:share:42"
    assert "LinkedIn post is untouched" in archived.history[-1].detail
    assert ledger_states(store) == [LedgerEntryState.PUBLISHED]


# One post per calendar day


def test_second_due_post_the_same_day_is_not_sent(due, service, store, clock):
    other = scheduled_post(service, "Other", "2026-11-17")
    path = store.post_path(other.id)
    path.write_text(path.read_text().replace('"2026-11-17"', '"2026-11-16"'))
    transport = FakeTransport()
    coordinator = make_coordinator(store, clock, transport)
    assert coordinator.run().outcome is RunOutcome.PUBLISHED
    clock.set("2026-11-16T14:00:00Z")
    report = coordinator.run()
    assert report.outcome is RunOutcome.NOTHING and report.evaluation.reason.value == "DAY_ALREADY_USED"
    assert transport.calls == [due.id] and store.load_post(other.id).state is S.SCHEDULED


def test_a_deleted_ledger_file_does_not_reopen_the_day(due, service, store, clock):
    """The limit is cross checked against the posts' own attempt records."""
    other = scheduled_post(service, "Other", "2026-11-17")
    transport = FakeTransport()
    coordinator = make_coordinator(store, clock, transport)
    coordinator.run()
    store.ledger_path(DAY).unlink()
    path = store.post_path(other.id)
    path.write_text(path.read_text().replace('"2026-11-17"', '"2026-11-16"'))
    assert coordinator.run().outcome is RunOutcome.NOTHING
    assert transport.calls == [due.id]


def test_a_fresh_coordinator_has_no_memory_and_still_respects_the_day(due, service, store, clock):
    transport = FakeTransport()
    make_coordinator(store, clock, transport).run()
    other = scheduled_post(service, "Other", "2026-11-18")
    service.reschedule(other.id, actor="tester", new_date="2026-11-17", authorized=True)
    clock.set("2026-11-17T03:00:00Z")  # still 16 November in Detroit
    assert make_coordinator(store, clock, transport).run().outcome is RunOutcome.NOTHING
    clock.set("2026-11-17T13:30:00Z")
    assert make_coordinator(store, clock, transport).run().outcome is RunOutcome.PUBLISHED
    assert transport.calls == [due.id, other.id]


def test_paused_run_sends_nothing(due, service, store, clock):
    service.set_paused(True, actor="owner")
    transport = FakeTransport()
    assert make_coordinator(store, clock, transport).run().outcome is RunOutcome.NOTHING
    assert transport.calls == []


def test_empty_and_invalid_queues(service, store, clock):
    go_live(store)
    transport = FakeTransport()
    coordinator = make_coordinator(store, clock, transport)
    assert coordinator.run().outcome is RunOutcome.NOTHING
    scheduled_post(service, "Due", "2026-11-16")
    (store.posts_dir / "junk.json").write_text("[]")
    clock.set(SLOT)
    assert coordinator.run().outcome is RunOutcome.BLOCKED
    assert transport.calls == []


def test_corrupt_ledger_stops_the_run(due, store, clock):
    path = store.ledger_path(DAY)
    path.parent.mkdir(parents=True)
    path.write_text("{")
    transport = FakeTransport()
    with pytest.raises(Exception, match="ledger"):
        make_coordinator(store, clock, transport).run()
    assert transport.calls == [] and store.load_post(due.id).state is S.SCHEDULED


# Crash recovery and checkpoints


class Crash(BaseException):
    """Simulates the process dying (a cancelled or timed out workflow run)."""


def test_crash_during_the_send_becomes_uncertain_on_the_next_run(due, store, clock):
    class Dying:
        def publish(self, post):
            raise Crash()

    with pytest.raises(Crash):
        make_coordinator(store, clock, Dying()).run()
    assert store.load_post(due.id).state is S.PUBLISHING
    transport = FakeTransport()
    clock.advance(minutes=30)
    report = make_coordinator(store, clock, transport).run()
    assert report.recovered == (due.id,) and report.outcome is RunOutcome.NOTHING
    assert store.load_post(due.id).state is S.UNCERTAIN
    assert ledger_states(store) == [LedgerEntryState.UNCERTAIN] and transport.calls == []


def test_interrupted_post_blocks_a_dry_run_evaluation_without_being_touched(due, store, clock):
    class Dying:
        def publish(self, post):
            raise Crash()

    with pytest.raises(Crash):
        make_coordinator(store, clock, Dying()).run()
    write_config(store, publishing_enabled=True, dry_run=True)
    report = make_coordinator(store, clock, FakeTransport()).run()
    assert report.outcome is RunOutcome.BLOCKED and report.evaluation.reason.value == "IN_FLIGHT"
    assert store.load_post(due.id).state is S.PUBLISHING


def test_recovery_restores_a_lost_ledger_claim(due, store, clock):
    class Dying:
        def publish(self, post):
            raise Crash()

    with pytest.raises(Crash):
        make_coordinator(store, clock, Dying()).run()
    store.ledger_path(DAY).unlink()
    make_coordinator(store, clock, FakeTransport()).run()
    assert ledger_states(store) == [LedgerEntryState.UNCERTAIN]


def test_crash_between_ledger_claim_and_post_update_releases_the_day(due, store, clock, monkeypatch):
    original = store.save_post

    def dying_save(post, expected_revision):
        if post.state is S.PUBLISHING:
            raise Crash()
        return original(post, expected_revision)

    monkeypatch.setattr(store, "save_post", dying_save)
    transport = FakeTransport()
    with pytest.raises(Crash):
        make_coordinator(store, clock, transport).run()
    assert ledger_states(store) == [LedgerEntryState.INTENT] and transport.calls == []
    monkeypatch.setattr(store, "save_post", original)
    report = make_coordinator(store, clock, transport, attempt_id_factory=lambda: "attempt-retry").run()
    assert report.outcome is RunOutcome.PUBLISHED and transport.calls == [due.id]
    assert ledger_states(store) == [LedgerEntryState.RELEASED, LedgerEntryState.PUBLISHED]


def test_failed_intent_checkpoint_sends_nothing(due, store, clock):
    def checkpoint(label):
        raise RuntimeError("push rejected")

    transport = FakeTransport()
    report = make_coordinator(store, clock, transport, checkpoint=checkpoint).run()
    assert report.outcome is RunOutcome.FAILED and transport.calls == []
    assert store.load_post(due.id).state is S.FAILED
    assert ledger_states(store) == [LedgerEntryState.RELEASED]


def test_a_ledger_left_at_intent_after_the_post_closed_is_repaired(due, store, clock, monkeypatch):
    """Review finding: a crash between saving the post and the ledger kept the day used forever."""
    def checkpoint(label):
        raise RuntimeError("push rejected")

    def crash(*args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(store, "update_ledger_entry", crash)
        with pytest.raises(OSError):
            make_coordinator(store, clock, FakeTransport(), checkpoint=checkpoint).run()
    assert store.load_post(due.id).state is S.FAILED
    assert ledger_states(store) == [LedgerEntryState.INTENT]
    report = make_coordinator(store, clock, FakeTransport()).run()
    assert any(item.startswith("ledger:") for item in report.recovered)
    assert ledger_states(store) == [LedgerEntryState.RELEASED]


def test_checkpoint_error_text_is_never_stored_or_reported(due, store, clock):
    def checkpoint(label):
        raise RuntimeError("push to https://x-access-token:SECRET-PUSH-TOKEN@github.com failed")

    report = make_coordinator(store, clock, FakeTransport(), checkpoint=checkpoint).run()
    assert "SECRET-PUSH-TOKEN" not in " ".join(report.messages)
    assert "SECRET-PUSH-TOKEN" not in store.post_path(due.id).read_text()
    assert "RuntimeError" in report.messages[0]


def test_failed_outcome_checkpoint_keeps_the_local_result_and_warns(due, store, clock):
    def checkpoint(label):
        if label == "outcome":
            raise RuntimeError("push rejected")

    report = make_coordinator(store, clock, FakeTransport(), checkpoint=checkpoint).run()
    assert report.outcome is RunOutcome.PUBLISHED and "UNCERTAIN" in report.messages[0]
    assert store.load_post(due.id).state is S.PUBLISHED


def test_transport_secrets_in_exception_text_are_not_persisted(due, store, clock):
    transport = FakeTransport(RuntimeError("Authorization: Bearer SECRET-TOKEN-VALUE"))
    make_coordinator(store, clock, transport).run()
    assert "SECRET-TOKEN-VALUE" not in store.post_path(due.id).read_text()


# Property style invariant over many simulated weeks


def test_never_more_than_one_publication_per_local_day_under_random_operations(service, store, clock):
    """Seeded simulation: random outcomes, delays, duplicate runs and collisions. Fixed seed, 45 days."""
    go_live(store)
    rng = random.Random(8675309)
    clock.set("2026-10-25T12:00:00Z")  # the window spans the 1 November DST change
    sent_days: dict[str, list[str]] = {}

    class Recording:
        def publish(self, post):
            day = clock.now().astimezone(store.load_config().tzinfo).date().isoformat()
            sent_days.setdefault(day, []).append(post.id)
            roll = rng.random()
            if roll < 0.6:
                return success(f"urn:li:share:{post.id}")
            if roll < 0.8:
                return ambiguous()
            if roll < 0.9:
                raise TimeoutError("lost response")
            return failure()

    coordinator = make_coordinator(store, clock, Recording())
    for offset in range(1, 46):
        day = date(2026, 10, 25).toordinal() + offset
        scheduled_post(service, f"Day {offset}", date.fromordinal(day).isoformat(), rng.choice([None, "09:00"]))
    for _ in range(45 * 6):
        clock.advance(hours=rng.choice([1, 2, 3, 5, 7]))
        if rng.random() < 0.15:
            posts = [p for p in store.load_snapshot().posts if p.state is S.SCHEDULED]
            if len(posts) > 1:  # hand edited collision
                a, b = rng.sample(posts, 2)
                path = store.post_path(b.id)
                path.write_text(path.read_text().replace(f'"{b.scheduled_date}"', f'"{a.scheduled_date}"', 1))
        for _ in range(rng.choice([1, 1, 2, 3])):  # duplicate and overlapping triggers
            coordinator.run()

    assert sent_days, "the simulation must actually publish"
    assert all(len(ids) == 1 for ids in sent_days.values()), sent_days
    all_sent = [post_id for ids in sent_days.values() for post_id in ids]
    assert len(all_sent) == len(set(all_sent)), "no post was ever sent twice"
    for post in store.load_snapshot().posts:
        if post.state is S.PUBLISHED:
            assert post.linkedin_post_id and all_sent.count(post.id) == 1
