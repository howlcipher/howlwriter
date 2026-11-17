"""Scheduling evaluation with a fake clock: slots, DST, lateness, conflicts, pause, calendar edges."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from howlwriter.linkedin.scheduler import Action, PostStatus, Reason, due_at, local_date
from tests.linkedin.helpers import approved_post, scheduled_post, write_config

DETROIT = ZoneInfo("America/Detroit")


def utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def status_of(evaluation, post_id):
    return next(item for item in evaluation.assessments if item.post_id == post_id).status


# Slot arithmetic


@pytest.mark.parametrize(
    "day, slot, expected",
    [
        (date(2026, 11, 16), "08:30", "2026-11-16T13:30:00Z"),  # EST
        (date(2026, 7, 1), "08:30", "2026-07-01T12:30:00Z"),  # EDT
        (date(2026, 3, 8), "08:30", "2026-03-08T12:30:00Z"),  # spring forward day
        (date(2026, 3, 7), "08:30", "2026-03-07T13:30:00Z"),  # day before
        (date(2026, 11, 1), "08:30", "2026-11-01T13:30:00Z"),  # fall back day
        (date(2026, 10, 31), "08:30", "2026-10-31T12:30:00Z"),
        (date(2026, 3, 8), "02:30", "2026-03-08T07:30:00Z"),  # skipped wall time lands after the gap
        (date(2026, 11, 1), "01:30", "2026-11-01T05:30:00Z"),  # repeated wall time: first occurrence
        (date(2028, 2, 29), "09:00", "2028-02-29T14:00:00Z"),  # leap day
        (date(2026, 12, 31), "09:00", "2026-12-31T14:00:00Z"),
        (date(2027, 1, 1), "08:30", "2027-01-01T13:30:00Z"),
    ],
)
def test_due_instant_is_correct_across_dst_and_calendar_edges(day, slot, expected):
    assert due_at(day, slot, DETROIT) == utc(expected)


def test_local_day_is_the_detroit_calendar_day_not_the_utc_day():
    assert local_date(utc("2026-11-17T03:00:00Z"), DETROIT) == date(2026, 11, 16)
    assert local_date(utc("2027-01-01T04:59:59Z"), DETROIT) == date(2026, 12, 31)
    assert local_date(utc("2027-01-01T05:00:00Z"), DETROIT) == date(2027, 1, 1)
    with pytest.raises(ValueError):
        local_date(datetime(2026, 11, 16, 12, 0), DETROIT)


# Evaluation


def test_empty_queue_does_nothing(service):
    evaluation = service.evaluate()
    assert (evaluation.action, evaluation.reason) == (Action.NOTHING, Reason.NO_POST_DUE)


def test_post_becomes_due_exactly_at_its_slot(service, clock):
    post = scheduled_post(service, "Today", "2026-11-16")
    clock.set("2026-11-16T13:29:59Z")
    early = service.evaluate()
    assert early.action is Action.NOTHING and status_of(early, post.id) is PostStatus.NOT_YET_DUE
    clock.set("2026-11-16T13:30:00Z")
    on_time = service.evaluate()
    assert (on_time.action, on_time.candidate_id) == (Action.PUBLISH, post.id)


def test_delayed_start_within_the_window_still_publishes(service, clock):
    post = scheduled_post(service, "Today", "2026-11-16")
    clock.set("2026-11-16T16:30:00Z")  # exactly 180 minutes late
    assert service.evaluate().candidate_id == post.id
    clock.set("2026-11-16T16:30:01Z")
    late = service.evaluate()
    assert late.action is Action.NOTHING and status_of(late, post.id) is PostStatus.OVERDUE


def test_missed_slot_is_recovered_by_the_next_slot_check_the_same_day(service, clock):
    """The 08:30 run never started. The 09:00 run finds the 08:30 post still inside its window."""
    post = scheduled_post(service, "Today", "2026-11-16")
    clock.set("2026-11-16T14:00:00Z")
    assert service.evaluate().candidate_id == post.id


def test_post_from_a_past_day_is_held_not_published(service, clock):
    post = scheduled_post(service, "Yesterday", "2026-11-16")
    clock.set("2026-11-17T13:30:00Z")
    evaluation = service.evaluate()
    assert evaluation.action is Action.NOTHING and status_of(evaluation, post.id) is PostStatus.OVERDUE


def test_lateness_window_never_crosses_into_the_next_day(service, store, clock):
    write_config(store, max_lateness_minutes=720, allowed_publish_times=["08:30", "23:30"])
    post = scheduled_post(service, "Late slot", "2026-11-16", "23:30")
    clock.set("2026-11-17T05:10:00Z")  # 00:10 next local day, only 40 minutes late
    evaluation = service.evaluate()
    assert evaluation.action is Action.NOTHING and status_of(evaluation, post.id) is PostStatus.OVERDUE


def test_time_override_selects_the_later_slot(service, clock):
    post = scheduled_post(service, "Nine", "2026-11-16", "09:00")
    clock.set("2026-11-16T13:30:00Z")
    assert service.evaluate().action is Action.NOTHING
    clock.set("2026-11-16T14:00:00Z")
    assert service.evaluate().candidate_id == post.id


def test_changing_the_default_time_moves_posts_without_an_override(service, store, clock):
    post = scheduled_post(service, "Follows default", "2026-11-16")
    write_config(store, default_publish_time="09:00")
    clock.set("2026-11-16T13:45:00Z")
    assert service.evaluate().action is Action.NOTHING
    clock.set("2026-11-16T14:00:00Z")
    assert service.evaluate().candidate_id == post.id


def test_post_with_a_slot_no_longer_supported_is_blocked(service, store, clock):
    post = scheduled_post(service, "Nine", "2026-11-16", "09:00")
    write_config(store, allowed_publish_times=["08:30"])
    clock.set("2026-11-16T14:00:00Z")
    evaluation = service.evaluate()
    assert evaluation.action is Action.NOTHING and status_of(evaluation, post.id) is PostStatus.BLOCKED


def test_post_in_another_timezone_is_blocked(service, store, clock):
    post = scheduled_post(service, "Today", "2026-11-16")
    write_config(store, timezone="America/Chicago")
    clock.set("2026-11-16T15:00:00Z")
    assert status_of(service.evaluate(), post.id) is PostStatus.BLOCKED


def test_dst_days_publish_at_the_local_slot(service, clock):
    clock.set("2027-03-01T12:00:00Z")
    before = scheduled_post(service, "Standard time", "2027-03-13")
    after = scheduled_post(service, "Daylight time", "2027-03-14")
    clock.set("2027-03-13T13:30:00Z")
    assert service.evaluate().candidate_id == before.id
    clock.set("2027-03-14T12:29:59Z")
    assert status_of(service.evaluate(), after.id) is PostStatus.NOT_YET_DUE
    clock.set("2027-03-14T12:30:00Z")
    assert service.evaluate().candidate_id == after.id


def test_two_posts_due_the_same_day_yield_one_candidate(service, store, clock):
    """Hand edited files can collide even though the commands refuse it. One wins, deterministically."""
    first = scheduled_post(service, "First", "2026-11-16")
    second = scheduled_post(service, "Second", "2026-11-17")
    path = store.post_path(second.id)
    path.write_text(path.read_text().replace('"2026-11-17"', '"2026-11-16"'))
    clock.set("2026-11-16T13:30:00Z")
    evaluation = service.evaluate()
    assert evaluation.candidate_id == first.id
    assert status_of(evaluation, second.id) is PostStatus.DAILY_LIMIT_CONFLICT


def test_earlier_slot_wins_a_same_day_collision(service, store, clock):
    late = scheduled_post(service, "Nine", "2026-11-16", "09:00")
    early = scheduled_post(service, "Half past eight", "2026-11-17")
    path = store.post_path(early.id)
    path.write_text(path.read_text().replace('"2026-11-17"', '"2026-11-16"'))
    clock.set("2026-11-16T14:05:00Z")
    assert service.evaluate().candidate_id == early.id
    assert late.id != early.id


def test_global_pause_stops_everything_and_resume_restores_it(service, store, clock):
    post = scheduled_post(service, "Today", "2026-11-16")
    clock.set("2026-11-16T13:30:00Z")
    service.set_paused(True, actor="tester", reason="holiday")
    paused = service.evaluate()
    assert (paused.action, paused.reason) == (Action.NOTHING, Reason.PAUSED)
    service.set_paused(False, actor="tester")
    assert service.evaluate().candidate_id == post.id
    assert [event.action for event in store.load_control().history] == ["paused", "resumed"]


def test_invalid_post_file_blocks_the_whole_run(service, store, clock):
    scheduled_post(service, "Today", "2026-11-16")
    (store.posts_dir / "garbage.json").write_text("{")
    clock.set("2026-11-16T13:30:00Z")
    evaluation = service.evaluate()
    assert (evaluation.action, evaluation.reason) == (Action.BLOCKED, Reason.QUEUE_INVALID)
    assert evaluation.candidate_id is None


def test_only_scheduled_posts_are_candidates(service, clock):
    approved_post(service, "Approved only", "2026-11-16")
    service.add_draft(title="Draft", text="Body", actor="tester", scheduled_date="2026-11-17")
    clock.set("2026-11-16T13:30:00Z")
    evaluation = service.evaluate()
    assert evaluation.action is Action.NOTHING and evaluation.assessments == ()


def test_hand_edited_text_makes_the_approval_stale_and_blocks(service, store, clock):
    post = scheduled_post(service, "Today", "2026-11-16")
    path = store.post_path(post.id)
    path.write_text(path.read_text().replace("Body text.", "Body text with an unapproved claim."))
    clock.set("2026-11-16T13:30:00Z")
    evaluation = service.evaluate()
    assert evaluation.action is Action.NOTHING
    blocked = next(item for item in evaluation.assessments if item.post_id == post.id)
    assert blocked.status is PostStatus.BLOCKED and "approval" in " ".join(blocked.reasons)


def test_evaluation_never_changes_anything(service, store, clock):
    scheduled_post(service, "Today", "2026-11-16")
    clock.set("2026-11-16T13:30:00Z")
    before = {path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    service.evaluate()
    service.preview_queue()
    after = {path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    assert before == after
