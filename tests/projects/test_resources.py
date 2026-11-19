"""The heavy-work governor: idle priority, thread caps, deadlines, restart after a kill."""

from __future__ import annotations

import os
import subprocess
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
        [sys.executable, "-c",
         "import os, time\n"
         "for _ in range(200):\n"
         "    if os.getpriority(0, 0) == 19: break\n"
         "    time.sleep(0.01)\n"
         "time.sleep(0.05)\n"
         "print(os.sched_getscheduler(0), os.getpriority(0, 0))"],
        timeout=30,
        capture_output=True,
        text=True,
    )
    policy, nice = result.stdout.split()
    assert int(policy) == os.SCHED_IDLE and int(nice) == 19


def test_governed_run_returns_a_completed_process():
    result = governed_run([sys.executable, "-c", "import sys; print(1); print(2, file=sys.stderr); sys.exit(3)"],
                          timeout=30, capture_output=True, text=True)
    assert result.returncode == 3 and result.stdout.strip() == "1" and result.stderr.strip() == "2"
    echoed = governed_run([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                          timeout=30, capture_output=True, text=True, input="abc")
    assert echoed.stdout.strip() == "ABC"
    with pytest.raises(subprocess.CalledProcessError):
        governed_run([sys.executable, "-c", "raise SystemExit(2)"], timeout=30, check=True)


def test_governed_run_kills_a_child_that_times_out():
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        governed_run([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.5)
    assert time.monotonic() - started < 30


@pytest.mark.skipif(not hasattr(os, "getpriority"), reason="needs os.getpriority")
def test_governed_run_raises_the_childs_niceness_without_preexec(monkeypatch):
    import inspect

    from howlwriter.projects import resources

    assert "preexec_fn" not in inspect.getsource(resources.governed_run)
    # The parent lowers priority just after start, so the child waits for it before reading.
    code = ("import os, time\n"
            "for _ in range(200):\n"
            "    if os.getpriority(0, 0) == 19: break\n"
            "    time.sleep(0.01)\n"
            "print(os.getpriority(0, 0))")
    on = governed_run([sys.executable, "-c", code], timeout=30, capture_output=True, text=True,
                      policy=ResourcePolicy(idle_priority=True))
    assert on.stdout.strip() == "19"
    off = governed_run([sys.executable, "-c", "import os; print(os.getpriority(0, 0))"], timeout=30,
                       capture_output=True, text=True, policy=ResourcePolicy(idle_priority=False))
    assert int(off.stdout.strip()) < 19


def test_busy_machine_wait_is_bounded(monkeypatch):
    worker = HeavyWorker(ResourcePolicy(max_wait=0.5))
    monkeypatch.setattr(os, "getloadavg", lambda: (1e9, 1e9, 1e9))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert worker.wait_for_quiet() >= 0.5
