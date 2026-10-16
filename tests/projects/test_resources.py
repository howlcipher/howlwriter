"""The heavy-work governor: idle priority, thread caps, deadlines, restart after a kill."""

from __future__ import annotations

import os
import sys
import time

import pytest

from howlwriter.projects.resources import HeavyWorker, JobTimeout, ResourcePolicy, governed_run, thread_env


def test_policy_clamps_threads():
    assert ResourcePolicy.from_dict({"threads": 0}).threads == 1
    assert ResourcePolicy.from_dict({"threads": 10_000}).threads == (os.cpu_count() or 1)
    assert ResourcePolicy.from_dict({"bogus": 1}).threads == 2
    assert thread_env(3)["OMP_NUM_THREADS"] == "3"


def test_worker_runs_jobs_and_survives_errors():
    worker = HeavyWorker(ResourcePolicy(job_timeout=30))
    try:
        assert worker.run("sleep", 0.01) == 0.01
        with pytest.raises(RuntimeError):
            worker.run("sleep", "not-a-number")
        assert worker.run("sleep", 0.01) == 0.01
        assert worker.stats["errors"] == 1 and worker.stats["restarts"] == 0
    finally:
        worker.close()


def test_job_past_its_deadline_is_killed_and_the_worker_restarts():
    worker = HeavyWorker(ResourcePolicy(job_timeout=1))
    try:
        started = time.monotonic()
        with pytest.raises(JobTimeout):
            worker.run("sleep", 30)
        assert time.monotonic() - started < 10
        assert worker.run("sleep", 0.01, timeout=20) == 0.01
        assert worker.stats["timeouts"] == 1 and worker.stats["restarts"] == 1
    finally:
        worker.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="SCHED_IDLE is Linux-specific")
def test_worker_runs_at_idle_priority():
    worker = HeavyWorker(ResourcePolicy())
    try:
        worker.run("sleep", 0.01)
        pid = worker._process.pid
        assert os.sched_getscheduler(pid) == os.SCHED_IDLE
        assert os.getpriority(os.PRIO_PROCESS, pid) == 19
        environ = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
        assert b"OMP_NUM_THREADS=2" in environ
    finally:
        worker.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="SCHED_IDLE is Linux-specific")
def test_external_tools_run_at_idle_priority():
    result = governed_run(
        [sys.executable, "-c", "import os; print(os.sched_getscheduler(0), os.getpriority(0, 0))"],
        timeout=30,
        capture_output=True,
        text=True,
    )
    policy, nice = result.stdout.split()
    assert int(policy) == os.SCHED_IDLE and int(nice) == 19


def test_busy_machine_wait_is_bounded(monkeypatch):
    worker = HeavyWorker(ResourcePolicy(max_wait=0.5))
    monkeypatch.setattr(os, "getloadavg", lambda: (1e9, 1e9, 1e9))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert worker.wait_for_quiet() >= 0.5
