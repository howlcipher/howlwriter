"""Browser authorization: allowlists, read-only enforcement, approvals, refusal of graded submission.

Policy tests run without a browser. The live tests drive a real headless
Chromium against the local test lab and skip when Chromium is not installed.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from howlwriter.projects import models as m
from howlwriter.projects.browser import BrowserPolicy, BrowserPolicyError, BrowserSession, origin_of
from howlwriter.projects.testlab import TestLab
from howlwriter.projects.workspace import ProjectWorkspace


@pytest.fixture
def workspace(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    return ProjectWorkspace.create(folder)


# --- policy ----------------------------------------------------------------------


def test_origin_normalization():
    assert origin_of("https://Docs.Example.org:443/a?b") == "https://docs.example.org"
    assert origin_of("http://127.0.0.1:8080/x") == "http://127.0.0.1:8080"
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x.org"):
        with pytest.raises(BrowserPolicyError):
            origin_of(bad)


def test_allowlist_is_exact_and_wildcards_are_research_only():
    policy = BrowserPolicy(mode="research", allowed_origins=["https://*.suricata.io", "https://example.org"])
    assert policy.allows("https://docs.suricata.io/en/latest/")
    assert policy.allows("https://suricata.io/")
    assert not policy.allows("https://evil-suricata.io/")
    assert not policy.allows("http://docs.suricata.io/")
    assert not policy.allows("https://example.org.evil.net/")
    assert not policy.allows("file:///etc/passwd")
    with pytest.raises(BrowserPolicyError):
        BrowserPolicy(
            mode="interactive", allowed_origins=["https://*.x.org"], interactive_origins=["https://lab.x.org"]
        )


def test_modes_need_approved_origins():
    with pytest.raises(BrowserPolicyError):
        BrowserPolicy(mode="research")
    with pytest.raises(BrowserPolicyError):
        BrowserPolicy(mode="interactive", allowed_origins=["https://x.org"])
    with pytest.raises(BrowserPolicyError):
        BrowserPolicy(mode="anything", allowed_origins=["https://x.org"])


class FakeRequest:
    def __init__(self, url, method="GET", navigation=False):
        self.url, self.method, self._navigation = url, method, navigation

    def is_navigation_request(self):
        return self._navigation


class FakeRoute:
    def __init__(self):
        self.outcome = None

    def abort(self, reason):
        self.outcome = "abort"

    def continue_(self):
        self.outcome = "continue"


def _route(session, url, method="GET"):
    route = FakeRoute()
    session._route(route, FakeRequest(url, method))
    return route.outcome


def test_network_layer_enforces_read_only_and_allowlist(workspace):
    research = BrowserSession(
        workspace, BrowserPolicy(mode="research", allowed_origins=["https://ref.example"])
    )
    assert _route(research, "https://ref.example/page") == "continue"
    assert _route(research, "https://tracker.example/pixel") == "abort"
    assert _route(research, "https://ref.example/form", "POST") == "abort"
    lab = BrowserSession(
        workspace,
        BrowserPolicy(mode="interactive", allowed_origins=[], interactive_origins=["https://lab.example"]),
    )
    assert _route(lab, "https://lab.example/run", "POST") == "abort"  # no approved action running
    lab._executing = "act-1"
    assert _route(lab, "https://lab.example/run", "POST") == "continue"
    assert _route(lab, "https://other.example/run", "POST") == "abort"
    assert {b["reason"] for b in research.blocked} == {
        "origin not approved",
        "POST blocked in read-only research mode",
    }


def test_actions_need_a_running_unpaused_interactive_session(workspace):
    session = BrowserSession(
        workspace, BrowserPolicy(mode="observe", allowed_origins=["https://lab.example"])
    )
    with pytest.raises(BrowserPolicyError, match="not running"):
        session.read()
    session.state = "running"
    with pytest.raises(BrowserPolicyError, match="read-only"):
        session.request("click", "#run")
    session.pause()
    with pytest.raises(BrowserPolicyError, match="paused"):
        session.navigate("https://lab.example/")


def test_browser_profile_is_dedicated_and_private(workspace):
    session = BrowserSession(workspace, BrowserPolicy(mode="research", allowed_origins=["https://x.org"]))
    assert workspace.directory in session.profile_dir.parents


# --- live (real Chromium) ---------------------------------------------------------------


@pytest.fixture
def live(workspace):
    pytest.importorskip("playwright")
    lab = TestLab().__enter__()
    sessions = []

    def start(policy):
        session = BrowserSession(workspace, policy, headless=True)
        try:
            session.start()
        except Exception as error:  # Chromium not installed in this environment
            pytest.skip(f"Chromium unavailable: {str(error).splitlines()[0][:120]}")
        sessions.append(session)
        return session

    yield lab, start
    for session in sessions:
        session.stop()
    lab.__exit__(None, None, None)


def _state(lab):
    return json.load(urllib.request.urlopen(lab.url("/lab/state.json")))


def test_research_mode_reads_records_provenance_and_flags_injection(live, workspace):
    lab, start = live
    session = start(BrowserPolicy(mode="research", allowed_origins=[lab.origin]))
    assert session.navigate(lab.url("/reference")).outcome == "ok"
    item = session.read()
    assert item.status == m.EXTRACTED and item.source_type == "browser"
    assert item.observation["title"] == "Suricata and TLS inspection notes"
    assert "What remains visible" in item.observation["headings"]
    assert item.observation["prompt_injection_suspected"] is True
    assert "retrieved" in item.citation and lab.url("/reference") in item.citation
    assert _state(lab)["runs"] == 0  # the injected instruction was not followed


def test_navigation_outside_the_allowlist_and_redirects_are_blocked(live):
    lab, start = live
    session = start(BrowserPolicy(mode="research", allowed_origins=[lab.origin]))
    assert session.navigate(lab.outside_origin + "/x").outcome == "blocked"
    assert session.navigate(lab.url("/go-outside")).outcome == "blocked"


def test_observe_mode_cannot_change_state_even_through_page_scripts(live):
    lab, start = live
    session = start(BrowserPolicy(mode="observe", allowed_origins=[lab.origin]))
    session.navigate(lab.url("/lab"))
    item = session.read()
    assert item.status == m.DIRECTLY_OBSERVED and "Experiment runs: 0" in item.excerpt
    session.page.click("#beacon")
    session.page.wait_for_timeout(300)
    try:
        session.page.click("#run")
        session.page.wait_for_timeout(300)
    except Exception:
        pass
    assert _state(lab) == {"runs": 0, "last": "no runs yet", "submitted": False, "posts": []}
    assert any("POST blocked" in b["reason"] for b in session.blocked)
    with pytest.raises(BrowserPolicyError):
        session.request("click", "#run")


def test_interactive_mode_requires_approval_records_audit_and_refuses_submission(live, workspace):
    lab, start = live
    session = start(BrowserPolicy(mode="interactive", allowed_origins=[], interactive_origins=[lab.origin]))
    session.navigate(lab.url("/lab"))
    with pytest.raises(BrowserPolicyError, match="graded work"):
        session.request("click", "#submit")
    denied = session.request("click", "#run")
    session.deny(denied)
    assert _state(lab)["runs"] == 0
    fill = session.request("fill", "#rate", "20")
    session.approve(fill)
    pending = session.request("click", "#run")
    assert session.status()["pending"][0]["target"].startswith("#run (Run experiment)")
    assert _state(lab)["runs"] == 0
    action = session.approve(pending)
    assert action.outcome == "ok" and action.changed_state and action.decision == "approved"
    state = _state(lab)
    assert state["runs"] == 1 and state["last"] == "60 alerts from 200 packets" and not state["submitted"]
    evidence = workspace.load_evidence()[action.evidence_ids[0]]
    assert "60 alerts from 200 packets" in evidence.excerpt
    assert "approved by the user" in evidence.observation["performed_by"]
    assert any("not performed by hand" in limit for limit in evidence.limitations)
    log = workspace.load_actions()
    kinds = [(a.kind, a.decision, a.outcome) for a in log]
    assert ("click", "denied", "blocked") in kinds and ("click", "approved", "ok") in kinds
    assert all(not a.changed_state for a in log if a.kind in ("navigate", "read", "screenshot"))


def test_secret_fill_is_redacted_everywhere(live, workspace, monkeypatch):
    lab, start = live
    monkeypatch.setenv("LAB_RATE_SECRET", "987654")
    session = start(BrowserPolicy(mode="interactive", allowed_origins=[], interactive_origins=[lab.origin]))
    session.navigate(lab.url("/lab"))
    session.approve(session.request("fill", "#rate", secret_env="LAB_RATE_SECRET"))
    assert session.page.input_value("#rate") == "987654"
    stored = (workspace.directory / "actions.jsonl").read_text() + (
        workspace.directory / "evidence.json"
    ).read_text()
    assert "987654" not in stored
    assert any(a.value_redacted for a in workspace.load_actions())


def test_switching_to_read_only_denies_pending_actions(live):
    lab, start = live
    session = start(BrowserPolicy(mode="interactive", allowed_origins=[], interactive_origins=[lab.origin]))
    session.navigate(lab.url("/lab"))
    session.request("click", "#run")
    session.set_read_only()
    assert session.policy.mode == "observe" and not session.pending
    assert _state(lab)["runs"] == 0


def test_screenshot_evidence_keeps_the_original_artifact(live, workspace):
    lab, start = live
    session = start(BrowserPolicy(mode="observe", allowed_origins=[lab.origin]))
    session.navigate(lab.url("/lab"))
    item = session.screenshot("lab")
    path = workspace.directory / "cache" / "browser" / item.observation["file"]
    assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
    import hashlib

    assert hashlib.sha256(path.read_bytes()).hexdigest() == item.observation["sha256"]
