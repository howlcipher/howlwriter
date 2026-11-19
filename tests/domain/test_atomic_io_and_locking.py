"""Atomic writes, the directory lock, and the stores that depend on them."""

from __future__ import annotations

import json
import os
import stat
import threading

import pytest

from howlwriter.domain.io import atomic_write_bytes, atomic_write_text
from howlwriter.domain.locking import file_lock
from howlwriter.projects.models import BrowserAction
from howlwriter.projects.workspace import ProjectWorkspace
from howlwriter.voice.identity.store import Decision, IdentityStore


def _run_threads(target, count):
    errors = []

    def wrapped(index):
        try:
            target(index)
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def test_concurrent_atomic_writes_leave_one_valid_version_and_no_temp_files(tmp_path):
    target = tmp_path / "data.txt"

    def write(index):
        for n in range(50):
            atomic_write_text(target, f"writer-{index}-{n}\n" * 200)

    _run_threads(write, 8)
    lines = set(target.read_text(encoding="utf-8").splitlines())
    assert len(lines) == 1 and next(iter(lines)).startswith("writer-")
    assert [p.name for p in tmp_path.iterdir()] == ["data.txt"]


def test_private_write_is_0600(tmp_path):
    target = tmp_path / "secret.txt"
    atomic_write_text(target, "x", private=True)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    other = tmp_path / "secret.bin"
    atomic_write_bytes(other, b"x", private=True)
    assert stat.S_IMODE(other.stat().st_mode) == 0o600


def test_rewrite_keeps_the_existing_mode(tmp_path):
    target = tmp_path / "shared.txt"
    target.write_text("old", encoding="utf-8")
    os.chmod(target, 0o640)
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    atomic_write_bytes(target, b"newer")
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_new_file_gets_umask_default(tmp_path):
    old = os.umask(0o022)
    try:
        target = tmp_path / "new.txt"
        atomic_write_text(target, "x")
    finally:
        os.umask(old)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_new_file_mode_is_read_without_calling_os_umask(tmp_path, monkeypatch):
    from howlwriter.domain import io as io_module

    expected = io_module._current_umask()

    def forbidden(_mask):
        raise AssertionError("os.umask must not be called")

    monkeypatch.setattr(os, "umask", forbidden)
    target = tmp_path / "new.txt"
    atomic_write_text(target, "x")
    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~expected


def test_failed_write_removes_the_temp_file(tmp_path):
    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(tmp_path / "a.txt", "\ud800")
    assert list(tmp_path.iterdir()) == []


def test_file_lock_is_reentrant_and_excludes_other_threads(tmp_path):
    order = []
    inside = threading.Event()
    release = threading.Event()

    def holder():
        with file_lock(tmp_path):
            with file_lock(tmp_path):
                inside.set()
                release.wait(5)
            order.append("holder-done")

    thread = threading.Thread(target=holder)
    thread.start()
    assert inside.wait(5)

    def other():
        with file_lock(tmp_path):
            order.append("other")

    second = threading.Thread(target=other)
    second.start()
    second.join(timeout=0.3)
    assert second.is_alive()  # blocked while the first thread holds the lock
    release.set()
    thread.join(5)
    second.join(5)
    assert order == ["holder-done", "other"]
    assert stat.S_IMODE((tmp_path / ".lock").stat().st_mode) == 0o600


def test_file_lock_needs_an_existing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        with file_lock(tmp_path / "missing"):
            pass


def test_record_decision_from_20_threads_loses_nothing(tmp_path):
    root = tmp_path / "identities"
    store = IdentityStore("tester", root=root)

    def record(index):
        IdentityStore("tester", root=root).record_decision(
            Decision(doc_id=f"doc-{index}", authorship="CONFIRMED_HUMAN_AUTHORED")
        )

    _run_threads(record, 20)
    assert set(store.load_decisions()) == {f"doc-{i}" for i in range(20)}
    log = (store.directory / "decisions.log.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted(json.loads(line)["doc_id"] for line in log) == sorted(f"doc-{i}" for i in range(20))
    assert stat.S_IMODE((store.directory / "decisions.log.jsonl").stat().st_mode) == 0o600


def test_workspace_appends_from_20_threads_lose_nothing(tmp_path):
    base = tmp_path / "projects"
    workspace = ProjectWorkspace("proj", root=base)
    workspace.ensure()

    def append(index):
        ws = ProjectWorkspace("proj", root=base)
        ws.append_action(BrowserAction(action_id=f"a{index}", mode="research", kind="navigate", url="u"))
        ws.append_research({"note": f"n{index}"})

    _run_threads(append, 20)
    assert {a.action_id for a in workspace.load_actions()} == {f"a{i}" for i in range(20)}
    assert {e["note"] for e in workspace.load_research()} == {f"n{i}" for i in range(20)}
