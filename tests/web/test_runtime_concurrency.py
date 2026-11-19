"""The web runtime: sync handlers run off the event loop, SSE is thread-safe, jobs are retained sanely."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from howlwriter.web import jobs as jobs_module
from howlwriter.web.app import create_app
from howlwriter.web.jobs import JobManager, get_job_manager


@pytest.fixture
def live_server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_slow_sync_handler_does_not_block_the_event_loop(live_server, monkeypatch):
    from howlwriter.web.routes import voices

    def slow_names():
        time.sleep(1.0)
        return []

    monkeypatch.setattr(voices.VoiceStore, "list_names", staticmethod(slow_names))
    job = get_job_manager().create_job("test")

    slow = {}

    def call_slow():
        started = time.time()
        slow["status"] = httpx.get(f"{live_server}/api/voices", timeout=10).status_code
        slow["elapsed"] = time.time() - started

    worker = threading.Thread(target=call_slow)
    worker.start()
    time.sleep(0.2)  # the slow request is now inside its handler
    started = time.time()
    response = httpx.get(f"{live_server}/api/jobs/{job.job_id}", timeout=10)
    fast = time.time() - started
    worker.join(timeout=10)

    assert response.status_code == 200
    assert slow["status"] == 200 and slow["elapsed"] >= 0.9
    assert fast < 0.5, f"job status was delayed {fast:.2f}s behind a slow handler"


def test_sse_event_from_another_thread_arrives_promptly(live_server):
    job = get_job_manager().create_job("test")
    events = []
    with httpx.stream("GET", f"{live_server}/api/jobs/{job.job_id}/events", timeout=5) as response:
        lines = response.iter_lines()
        for line in lines:
            events.append(line)
            if line.startswith("event: snapshot"):
                break
        threading.Timer(0.1, job.fail, args=("boom",)).start()
        started = time.time()
        for line in lines:
            events.append(line)
            if line.startswith("event: failed"):
                break
        elapsed = time.time() - started
    assert "event: failed" in events
    assert elapsed < 1.0


def test_closed_loop_listener_is_dropped():
    import asyncio

    job = jobs_module.Job(job_type="test")
    loop = asyncio.new_event_loop()
    loop.close()
    job.add_listener(asyncio.Queue(), loop)
    job.fail("x")  # must not raise
    assert job._listeners == []


def test_remove_listener_matches_by_queue():
    import asyncio

    job = jobs_module.Job(job_type="test")
    loop = asyncio.new_event_loop()
    queue = asyncio.Queue()
    job.add_listener(queue, loop)
    job.remove_listener(queue)
    loop.close()
    assert job._listeners == []


def test_retention_evicts_finished_jobs_before_running_ones():
    manager = JobManager(max_retained_jobs=3)
    running = manager.create_job("a")
    done = manager.create_job("b")
    done.fail("x")
    manager.create_job("c")
    manager.create_job("d")  # over the limit: the finished job goes
    assert manager.get_job(done.job_id) is None
    assert manager.get_job(running.job_id) is running


def test_running_jobs_are_evicted_only_above_the_hard_cap():
    manager = JobManager(max_retained_jobs=3)
    first = manager.create_job("a")
    for _ in range(10):
        manager.create_job("b")
    assert manager.get_job(first.job_id) is first  # all running, under the cap
    manager._HARD_CAP = 5
    manager.create_job("c")
    assert manager.get_job(first.job_id) is None
