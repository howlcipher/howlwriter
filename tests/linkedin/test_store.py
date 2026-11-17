"""Persistence: atomic writes, compare and swap, exclusive creation, and the daily ledger."""

import json
import multiprocessing
from dataclasses import replace
from datetime import date

import pytest

from howlwriter.linkedin.config import ConfigError
from howlwriter.linkedin.models import PostValidationError
from howlwriter.linkedin.store import (
    DayAlreadyClaimedError,
    LedgerCorruptError,
    LedgerEntry,
    LedgerEntryState,
    PostExistsError,
    PostNotFoundError,
    QueueStore,
    StoreError,
)
from howlwriter.publishing.base import RevisionConflictError
from tests.linkedin.helpers import START

DAY = date(2026, 11, 16)
FP = "sha256:" + "b" * 64


def entry(attempt: str = "attempt-001", post: str = "post-001", state=LedgerEntryState.INTENT) -> LedgerEntry:
    return LedgerEntry(post, attempt, FP, state, START, START)


def test_initialize_is_idempotent_and_never_overwrites(store):
    store.config_path.write_text(store.config_path.read_text().replace("dry_run: true", "dry_run: false"))
    assert store.initialize() == []
    assert store.load_config().dry_run is False
    assert ".publisher.lock" in (store.root / ".gitignore").read_text()


def test_missing_config_is_an_error_not_a_default(tmp_path):
    with pytest.raises(ConfigError):
        QueueStore(tmp_path).load_config()


def test_save_requires_the_current_revision(service, store):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    first = store.save_post(replace(post, title="One"), expected_revision=0)
    assert first.revision == 1
    with pytest.raises(RevisionConflictError):
        store.save_post(replace(post, title="Lost update"), expected_revision=0)
    assert store.load_post(post.id).title == "One"


def test_create_refuses_an_existing_id(service, store):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    with pytest.raises(PostExistsError):
        store.create_post(post)


def test_save_recomputes_the_stored_fingerprint(service, store):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    saved = store.save_post(replace(post, text="Changed", content_fingerprint=post.content_fingerprint), 0)
    assert saved.fingerprint_is_current and saved.content_fingerprint != post.content_fingerprint


def test_save_refuses_an_invalid_record(service, store):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    with pytest.raises(PostValidationError):
        store.save_post(replace(post, title=""), 0)
    assert store.load_post(post.id).title == "Draft"


def test_snapshot_reports_malformed_files_instead_of_skipping_them(service, store):
    good = service.add_draft(title="Good", text="Body", actor="tester")
    (store.posts_dir / "broken-json.json").write_text("{not json")
    (store.posts_dir / "wrong-shape.json").write_text(json.dumps({"id": "wrong-shape"}))
    renamed = good.to_dict() | {"id": "another-id"}
    (store.posts_dir / "mismatch-id.json").write_text(json.dumps(renamed))
    snapshot = store.load_snapshot()
    assert [post.id for post in snapshot.posts] == [good.id]
    assert sorted(item.path for item in snapshot.invalid) == [
        "posts/broken-json.json", "posts/mismatch-id.json", "posts/wrong-shape.json",
    ]


def test_empty_repository_has_an_empty_snapshot(store):
    snapshot = store.load_snapshot()
    assert snapshot.posts == () and snapshot.invalid == ()


def test_unknown_post_and_unsafe_ids(store):
    with pytest.raises(PostNotFoundError):
        store.load_post("missing-post")
    with pytest.raises(StoreError):
        store.load_post("../../etc/passwd")


def test_media_paths_cannot_leave_the_repository(store):
    with pytest.raises(StoreError):
        store.media_file("media/../../outside.png")
    assert store.media_file("media/a.png").parent == (store.root / "media").resolve()


def test_no_temporary_files_are_left_behind(service, store):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    store.save_post(replace(post, title="Two"), 0)
    assert not list(store.root.rglob("*.tmp"))


# Ledger


def test_a_day_can_be_claimed_once(store):
    store.claim_day(DAY, entry(), 1)
    with pytest.raises(DayAlreadyClaimedError):
        store.claim_day(DAY, entry("attempt-002", "post-002"), 1)
    assert [item.attempt_id for item in store.load_ledger_day(DAY).entries] == ["attempt-001"]


@pytest.mark.parametrize("state", [LedgerEntryState.PUBLISHED, LedgerEntryState.UNCERTAIN])
def test_published_and_uncertain_days_stay_claimed(store, state):
    store.claim_day(DAY, entry(), 1)
    store.update_ledger_entry(DAY, "attempt-001", state, START)
    with pytest.raises(DayAlreadyClaimedError):
        store.claim_day(DAY, entry("attempt-002"), 1)


def test_only_a_definite_failure_releases_the_day(store):
    store.claim_day(DAY, entry(), 1)
    store.update_ledger_entry(DAY, "attempt-001", LedgerEntryState.RELEASED, START)
    ledger = store.claim_day(DAY, entry("attempt-002"), 1)
    assert [item.state for item in ledger.entries] == [LedgerEntryState.RELEASED, LedgerEntryState.INTENT]
    assert ledger.revision == 3


def test_ledger_days_are_independent_across_month_and_year_boundaries(store):
    for day in (date(2026, 12, 31), date(2027, 1, 1), date(2028, 2, 29), date(2028, 3, 1)):
        store.claim_day(day, entry(f"attempt-{day.strftime('%Y%m%d')}"), 1)
    assert store.ledger_path(date(2027, 1, 1)).parent.name == "2027"
    assert store.find_ledger_entry("attempt-20280229")[0] == date(2028, 2, 29)


@pytest.mark.parametrize("payload", ["{broken", "{}", json.dumps({"schema": "x", "date": "2026-11-16", "revision": 0, "entries": []})])
def test_corrupt_ledger_blocks_instead_of_allowing(store, payload):
    path = store.ledger_path(DAY)
    path.parent.mkdir(parents=True)
    path.write_text(payload)
    with pytest.raises(LedgerCorruptError):
        store.claim_day(DAY, entry(), 1)


def test_ledger_file_for_the_wrong_date_is_rejected(store):
    store.claim_day(DAY, entry(), 1)
    other = store.ledger_path(date(2026, 11, 17))
    other.write_text(store.ledger_path(DAY).read_text())
    with pytest.raises(LedgerCorruptError):
        store.load_ledger_day(date(2026, 11, 17))


def test_corrupt_control_file_blocks(store):
    store.control_path.write_text('{"paused": "no"}')
    with pytest.raises(LedgerCorruptError):
        store.load_control()


def _claim(root: str, number: int, queue) -> None:
    try:
        QueueStore(root).claim_day(DAY, entry(f"attempt-{number:03d}", f"post-{number:03d}"), 1)
        queue.put(("won", number))
    except DayAlreadyClaimedError:
        queue.put(("lost", number))


def test_concurrent_processes_cannot_both_claim_a_day(store):
    """Four real processes race for one day. Exactly one may win; bounded to four workers."""
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [context.Process(target=_claim, args=(str(store.root), n, queue)) for n in range(1, 5)]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=60) for _ in workers]
    for worker in workers:
        worker.join(timeout=60)
        assert worker.exitcode == 0
    assert sorted(kind for kind, _ in results) == ["lost", "lost", "lost", "won"]
    assert len(store.load_ledger_day(DAY).occupying) == 1


def _edit(root: str, post_id: str, number: int, queue) -> None:
    store = QueueStore(root)
    try:
        store.save_post(replace(store.load_post(post_id), title=f"Writer {number}"), expected_revision=0)
        queue.put("saved")
    except RevisionConflictError:
        queue.put("conflict")


def test_concurrent_writers_cannot_lose_an_update(service, store):
    post = service.add_draft(title="Draft", text="Body", actor="tester")
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [context.Process(target=_edit, args=(str(store.root), post.id, n, queue)) for n in range(3)]
    for worker in workers:
        worker.start()
    results = sorted(queue.get(timeout=60) for _ in workers)
    for worker in workers:
        worker.join(timeout=60)
    assert results == ["conflict", "conflict", "saved"]
    assert store.load_post(post.id).revision == 1
