"""The web UI is asked which model to use; nothing runs until it answers."""

from __future__ import annotations

import contextvars
import threading

from fastapi.testclient import TestClient
import pytest

from howlwriter.integration import howlplane_bridge as bridge_module
from howlwriter.integration import provider_choice as pc
from howlwriter.integration.howlplane_bridge import HowlPlaneWritingBridge, set_howlplane_bridge
from howlwriter.web.app import create_app
from howlwriter.web.jobs import JobManager

try:
    from howlplane.control_plane.agent_execution import FakeAgentBackend
    from howlplane.control_plane.role_binding import RoleBindingRegistry, RoleDispatcher
except ImportError:  # pragma: no cover - HowlPlane is a test dependency here
    pytest.skip("HowlPlane is not installed", allow_module_level=True)

TEXT = "It is important to note that the results were very good. The test passed and the team was happy."


@pytest.fixture
def ran(monkeypatch):
    """A fresh unbound bridge; records which model backend would have run."""
    monkeypatch.setattr(pc, "PROCESS_DEFAULTS", {"writer": None, "reviewer": None, "interactive": False})
    providers: list[str] = []

    def backend_for(provider):
        providers.append(provider)
        return FakeAgentBackend(agent_id=provider, default_stdout="The results were good. The test passed.")

    monkeypatch.setattr(bridge_module, "_backend_for", backend_for)
    registry = RoleBindingRegistry()
    set_howlplane_bridge(
        HowlPlaneWritingBridge(dispatcher=RoleDispatcher(binding_registry=registry), registry=registry)
    )
    yield providers
    set_howlplane_bridge(None)


def test_choices_list_the_four_models():
    body = TestClient(create_app()).get("/api/providers/choices").json()
    assert [c["provider"] for c in body["choices"]] == ["claude_code", "agy", "codex", "local_ollama"]
    remote = next(c for c in body["choices"] if c["provider"] == "codex")
    assert "will be sent to Codex" in remote["disclosure"]


def test_a_model_step_without_a_choice_asks_and_sends_nothing(ran):
    response = TestClient(create_app()).post("/api/humanize", json={"text": TEXT})
    assert response.status_code == 409
    assert response.json()["code"] == "model_choice_required"
    assert response.json()["role"] == "humanizer"
    assert ran == []


def test_continue_without_a_model_runs_the_rule_based_path(ran):
    response = TestClient(create_app()).post(
        "/api/humanize", json={"text": TEXT}, headers={pc.HEADER_PROVIDER: "none"}
    )
    assert response.status_code == 200 and ran == []


def test_the_chosen_model_runs_for_that_request_only(ran):
    client = TestClient(create_app())
    response = client.post("/api/humanize", json={"text": TEXT}, headers={pc.HEADER_PROVIDER: "codex"})
    assert response.status_code == 200
    assert ran and set(ran) == {"codex"}
    assert client.post("/api/humanize", json={"text": TEXT}).status_code == 409  # asked again


def test_rule_based_requests_never_ask(ran):
    response = TestClient(create_app()).post("/api/humanize", json={"text": TEXT, "deterministic_only": True})
    assert response.status_code == 200 and ran == []


def test_background_jobs_keep_the_request_choice():
    manager = JobManager()
    job = manager.create_job(job_type="t", stages=[])
    seen = {}
    done = threading.Event()
    token = pc.REQUEST_PROVIDER.set("agy")
    try:
        def task(_job):
            seen["provider"] = pc.REQUEST_PROVIDER.get()
            done.set()

        manager.start_in_background(job, task)
    finally:
        pc.REQUEST_PROVIDER.reset(token)
    assert done.wait(5) and seen["provider"] == "agy"


def test_send_confirmation_header_applies_only_to_the_named_model(ran):
    def in_request():
        pc.apply_request_headers({pc.HEADER_PROVIDER: "claude", pc.HEADER_CONFIRMED: "1"})
        bridge = bridge_module.get_howlplane_bridge()
        return bridge.is_remote_confirmed("claude_code"), bridge.is_remote_confirmed("codex")

    assert contextvars.copy_context().run(in_request) == (True, False)
    assert pc.REQUEST_PROVIDER.get() is None  # nothing leaks out of the request
