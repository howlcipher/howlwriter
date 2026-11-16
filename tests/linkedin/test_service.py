"""Queue operations: drafting, the review boundary, scheduling, rescheduling, pause, archive."""

import hashlib
from dataclasses import replace

import pytest

from howlwriter.linkedin.models import IllegalTransitionError, LifecycleState, MediaRef
from howlwriter.linkedin.service import DEFAULT, OperationRefused, QueueService
from howlwriter.publishing.base import RevisionConflictError
from tests.linkedin.helpers import approved_post, make_service, ref_for, scheduled_post

S = LifecycleState


def actions(post):
    return [event.action for event in post.history]


# Drafting and validation


def test_add_draft_records_identity_fingerprint_and_audit(service, store):
    post = service.add_draft(
        title="Launch notes", text="We shipped.\n\nhttps://example.com/x", actor="tester",
        urls=("https://example.com/x",), scheduled_date="2026-11-20",
    )
    stored = store.load_post(post.id)
    assert stored == post and stored.state is S.DRAFT and stored.revision == 0
    assert stored.fingerprint_is_current and stored.timezone == "America/Detroit"
    assert stored.created_at == stored.updated_at == "2026-11-16T12:00:00Z"
    assert actions(stored) == ["created"]


def test_generated_ids_are_unique_and_safe(store, clock):
    real = QueueService(store, clock)
    first = real.add_draft(title="Same Title!", text="One", actor="tester")
    second = real.add_draft(title="Same Title!", text="Two", actor="tester")
    odd = real.add_draft(title="../../etc", text="Three", actor="tester")
    assert first.id != second.id and first.id.startswith("same-title-")
    assert "/" not in odd.id and "." not in odd.id


def test_actor_is_required(service):
    with pytest.raises(OperationRefused):
        service.add_draft(title="No actor", text="Body", actor="  ")


def test_validate_reports_length_and_blocks_submission(service):
    post = service.add_draft(title="Too long", text="x" * 3001, actor="tester")
    findings = service.validate(post.id)
    assert any(f.code == "LINKEDIN_CHAR_LIMIT" and f.severity == "error" for f in findings)
    with pytest.raises(OperationRefused):
        service.submit_for_review(post.id, actor="tester")
    assert service.store.load_post(post.id).state is S.DRAFT


def test_validate_flags_control_characters_and_link_inconsistency(service):
    post = service.add_draft(
        title="Odd", text="Bell\x07 here", actor="tester", urls=("https://example.com/not-in-text",)
    )
    codes = {finding.code for finding in service.validate(post.id)}
    assert {"LINKEDIN_CONTROL_CHARACTERS", "URL_NOT_IN_TEXT"} <= codes


def test_url_with_embedded_credentials_is_an_error(service):
    post = service.add_draft(
        title="Leak", text="see https://user:pw@example.com/a", actor="tester",
        urls=("https://user:pw@example.com/a",),
    )
    assert any(f.code == "URL_INVALID" for f in service.validate(post.id))


def test_modified_image_bytes_are_detected(service, store):
    image = store.root / "media" / "chart.png"
    image.write_bytes(b"\x89PNG original")
    media = (MediaRef("media/chart.png", hashlib.sha256(image.read_bytes()).hexdigest(), "A chart"),)
    post = service.add_draft(title="With image", text="Look", actor="tester", media=media)
    assert not any(f.severity == "error" for f in service.validate(post.id))
    image.write_bytes(b"\x89PNG tampered")
    assert any(f.code == "MEDIA_CHANGED" for f in service.validate(post.id))
    image.unlink()
    assert any(f.code == "MEDIA_MISSING" for f in service.validate(post.id))


# The review and approval boundary


def test_nothing_can_be_approved_with_the_default_verifier(store, clock):
    """Without a real verifier the service has no way to mark a post verified or approved."""
    real = QueueService(store, clock)
    post = real.add_draft(title="Draft", text="Body", actor="tester", scheduled_date="2026-11-20")
    with pytest.raises(OperationRefused, match="no trusted verifier"):
        real.attach_verification(post.id, ref_for(post, "verification"), actor="tester")
    real.submit_for_review(post.id, actor="tester")
    with pytest.raises(OperationRefused):
        real.approve(post.id, ref_for(post), actor="tester")
    with pytest.raises(IllegalTransitionError):
        real.schedule(post.id, actor="tester")
    assert store.load_post(post.id).state is S.READY_FOR_REVIEW
    assert store.load_post(post.id).approval_ref is None


def test_approval_requires_verification_for_the_same_content(service):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    service.submit_for_review(post.id, actor="tester")
    with pytest.raises(OperationRefused, match="verification"):
        service.approve(post.id, ref_for(post), actor="tester")


def test_approval_for_other_content_is_refused(service):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    service.attach_verification(post.id, ref_for(post, "verification"), actor="tester")
    service.submit_for_review(post.id, actor="tester")
    forged = replace(ref_for(post), content_fingerprint="sha256:" + "0" * 64)
    with pytest.raises(OperationRefused, match="different content"):
        service.approve(post.id, forged, actor="tester")


def test_a_draft_cannot_skip_review(service):
    post = service.add_draft(title="Draft", text="Body", actor="tester", scheduled_date="2026-11-20")
    with pytest.raises(IllegalTransitionError):
        service.approve(post.id, ref_for(post), actor="tester")
    with pytest.raises(IllegalTransitionError):
        service.schedule(post.id, actor="tester")


@pytest.mark.parametrize("change", ["text", "urls", "media"])
def test_any_content_change_invalidates_approval_and_verification(service, change):
    post = scheduled_post(service, "Approved", "2026-11-20")
    edits = {
        "text": {"text": post.text + " One more claim."},
        "urls": {"urls": ("https://example.com/new",)},
        "media": {"media": (MediaRef("media/a.png", "c" * 64, "Alt"),)},
    }
    edited = service.update_content(post.id, actor="tester", **edits[change])
    assert edited.state is S.DRAFT
    assert edited.approval_ref is None and edited.verification_ref is None
    assert edited.history[-1].action == "content_edited" and "approval" in edited.history[-1].detail


def test_an_identical_edit_changes_nothing(service):
    post = scheduled_post(service, "Approved", "2026-11-20")
    same = service.update_content(post.id, actor="tester", text=post.text)
    assert same == post


def test_return_to_draft_discards_approval(service):
    post = approved_post(service, "Approved", "2026-11-20")
    assert service.return_to_draft(post.id, actor="tester").approval_ref is None


# Scheduling


def test_schedule_and_cancel_keep_the_approval(service):
    post = scheduled_post(service, "Queued", "2026-11-20")
    assert post.state is S.SCHEDULED
    cancelled = service.cancel(post.id, actor="tester")
    assert cancelled.state is S.APPROVED and cancelled.approval_is_current
    assert service.evaluate().assessments == ()


def test_scheduling_needs_a_date(service):
    post = approved_post(service, "No date")
    with pytest.raises(OperationRefused, match="date"):
        service.schedule(post.id, actor="tester")


def test_same_day_collisions_are_refused(service):
    scheduled_post(service, "First", "2026-11-20")
    with pytest.raises(OperationRefused, match="already holds"):
        service.add_draft(title="Second", text="Body", actor="tester", scheduled_date="2026-11-20")
    other = service.add_draft(title="Third", text="Body", actor="tester", scheduled_date="2026-11-21")
    with pytest.raises(OperationRefused, match="already holds"):
        service.reschedule(other.id, actor="tester", new_date="2026-11-20")


def test_past_dates_and_unsupported_times_are_refused(service):
    with pytest.raises(OperationRefused, match="past"):
        service.add_draft(title="Old", text="Body", actor="tester", scheduled_date="2026-11-15")
    with pytest.raises(OperationRefused, match="not a supported slot"):
        service.add_draft(title="Odd", text="Body", actor="tester", scheduled_date="2026-11-20", scheduled_time="10:15")
    with pytest.raises(ValueError):
        service.add_draft(title="Bad", text="Body", actor="tester", scheduled_date="2026-02-30")


def test_reschedule_is_audited_and_keeps_approval(service):
    post = scheduled_post(service, "Queued", "2026-11-20")
    moved = service.reschedule(post.id, actor="owner", new_date="2026-12-31", new_time="09:00")
    assert (moved.scheduled_date, moved.scheduled_time, moved.state) == ("2026-12-31", "09:00", S.SCHEDULED)
    assert moved.approval_is_current and moved.verification_is_current
    assert moved.history[-1].action == "rescheduled" and moved.history[-1].actor == "owner"
    assert "2026-11-20 default -> 2026-12-31 09:00" in moved.history[-1].detail
    back = service.reschedule(post.id, actor="owner", new_time=DEFAULT)
    assert back.scheduled_time is None and back.scheduled_date == "2026-12-31"


def test_reschedule_across_leap_day_and_year_end(service):
    post = scheduled_post(service, "Leap", "2027-12-31")
    assert service.reschedule(post.id, actor="tester", new_date="2028-02-29").scheduled_date == "2028-02-29"
    with pytest.raises(ValueError):
        service.reschedule(post.id, actor="tester", new_date="2027-02-29")


def test_finished_posts_cannot_be_rescheduled_or_edited(service):
    post = scheduled_post(service, "Done", "2026-11-20")
    archived = service.archive(post.id, actor="tester")
    assert archived.state is S.ARCHIVED
    with pytest.raises(OperationRefused):
        service.reschedule(post.id, actor="tester", new_date="2026-11-22")
    with pytest.raises(OperationRefused):
        service.update_content(post.id, actor="tester", text="New")
    with pytest.raises(IllegalTransitionError):
        service.archive(post.id, actor="tester")


def test_archiving_frees_the_date(service):
    post = scheduled_post(service, "Drop me", "2026-11-20")
    service.archive(post.id, actor="tester")
    assert service.add_draft(title="Replacement", text="Body", actor="tester", scheduled_date="2026-11-20")


# Bulk rescheduling


def _dates(service):
    return {post.title: post.scheduled_date for post in service.store.load_snapshot().posts}


def test_bulk_shift_moves_every_eligible_future_post(service, clock):
    scheduled_post(service, "A", "2026-11-17")
    scheduled_post(service, "B", "2026-11-18")
    service.add_draft(title="C", text="Body", actor="tester", scheduled_date="2026-11-19")
    service.add_draft(title="Undated", text="Body", actor="tester")
    plan = service.plan_bulk_reschedule(shift_days=7)
    assert _dates(service)["A"] == "2026-11-17", "planning must not write"
    applied = service.apply_bulk_reschedule(actor="owner", shift_days=7)
    assert applied == plan and len(plan.moves) == 3
    assert _dates(service) == {"A": "2026-11-24", "B": "2026-11-25", "C": "2026-11-26", "Undated": None}
    moved = next(post for post in service.store.load_snapshot().posts if post.title == "A")
    assert moved.approval_is_current and moved.history[-1].detail.startswith("bulk:")


def test_bulk_shift_by_one_day_does_not_collide_with_itself(service):
    for title, day in (("A", "2026-11-17"), ("B", "2026-11-18"), ("C", "2026-11-19")):
        scheduled_post(service, title, day)
    assert service.apply_bulk_reschedule(actor="owner", shift_days=1).is_applicable
    assert _dates(service) == {"A": "2026-11-18", "B": "2026-11-19", "C": "2026-11-20"}


def test_bulk_shift_is_all_or_nothing_on_conflict(service):
    scheduled_post(service, "A", "2026-11-17")
    scheduled_post(service, "B", "2026-11-20")
    plan = service.apply_bulk_reschedule(actor="owner", shift_days=3, from_date="2026-11-17")
    assert plan.is_applicable
    scheduled_post(service, "Fixed", "2026-11-19")
    blocked = service.apply_bulk_reschedule(actor="owner", shift_days=-1, from_date="2026-11-20")
    assert not blocked.is_applicable and "already held" in blocked.conflicts[0]
    assert _dates(service) == {"A": "2026-11-20", "B": "2026-11-23", "Fixed": "2026-11-19"}


def test_bulk_shift_into_the_past_is_refused(service):
    scheduled_post(service, "A", "2026-11-17")
    plan = service.apply_bulk_reschedule(actor="owner", shift_days=-5)
    assert not plan.is_applicable and "past" in plan.conflicts[0]
    assert _dates(service)["A"] == "2026-11-17"


def test_bulk_time_change_validates_the_slot(service):
    scheduled_post(service, "A", "2026-11-17")
    assert not service.plan_bulk_reschedule(new_time="07:45").is_applicable
    service.apply_bulk_reschedule(actor="owner", new_time="09:00")
    assert service.store.load_snapshot().posts[0].scheduled_time == "09:00"
    assert not service.plan_bulk_reschedule().is_applicable


def test_bulk_reschedule_handles_an_empty_queue(service):
    plan = service.apply_bulk_reschedule(actor="owner", shift_days=1)
    assert plan.moves == () and not plan.is_applicable


def test_bulk_reschedule_spans_dst_month_and_year_boundaries(service, clock):
    clock.set("2026-12-20T12:00:00Z")
    scheduled_post(service, "Year end", "2026-12-31")
    scheduled_post(service, "Leap eve", "2028-02-28")
    service.apply_bulk_reschedule(actor="owner", shift_days=1)
    assert _dates(service) == {"Year end": "2027-01-01", "Leap eve": "2028-02-29"}


# Concurrency


def test_a_stale_writer_gets_a_conflict_not_a_silent_overwrite(store, clock):
    one, two = make_service(store, clock), make_service(store, clock)
    post = one.add_draft(title="Shared", text="Body", actor="tester", scheduled_date="2026-11-20")
    stale = store.load_post(post.id)
    one.reschedule(post.id, actor="one", new_date="2026-11-21")
    with pytest.raises(RevisionConflictError):
        store.save_post(replace(stale, title="Stale"), expected_revision=stale.revision)
    assert two.reschedule(post.id, actor="two", new_date="2026-11-22").revision == 2


def test_preview_lists_posts_in_schedule_order_with_states(service, clock):
    scheduled_post(service, "Later", "2026-11-19", "09:00")
    scheduled_post(service, "Sooner", "2026-11-17")
    service.add_draft(title="Idea", text="Body", actor="tester")
    rows = service.preview_queue()
    assert [row["title"] for row in rows] == ["Sooner", "Later", "Idea"]
    assert rows[0]["scheduled_time"] == "08:30" and rows[0]["time_is_override"] is False
    assert rows[1]["queue_status"] == "FUTURE" and rows[1]["approval"] == "current"
    assert rows[2]["approval"] == "none" and rows[2]["queue_status"] is None
