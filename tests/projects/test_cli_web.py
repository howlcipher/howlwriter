"""`howlwriter project` commands and the /api/projects routes."""

from __future__ import annotations

import json
import time

import pytest

from howlwriter.cli.main import main


@pytest.fixture
def opened(lab_folder, capsys):
    pytest.importorskip("pypdf")
    code = main(["project", "open", str(lab_folder), "--no-ocr", "--no-transcribe", "--no-frames", "--json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    return lab_folder, report


def _json(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_open_scan_and_rescan(opened, capsys):
    folder, report = opened
    assert report["files"] == 4 and report["new_or_changed"] == 4
    code, again = _json(capsys, ["project", "scan", str(folder), "--json", "--no-ocr", "--no-transcribe"])
    assert code == 0 and again["unchanged"] == 4 and again["new_or_changed"] == 0


def test_cli_sources_classify_and_status(opened, capsys):
    folder, _ = opened
    code, sources = _json(capsys, ["project", "sources", str(folder), "--json"])
    assert {s["category"] for s in sources} >= {"assignment_instructions", "supporting_reference"}
    code, record = _json(
        capsys, ["project", "classify", str(folder), "draft notes.md", "supporting_reference", "--json"]
    )
    # No terminal (as for an AI agent): recorded as the agent's change, not the user's.
    assert record["category_source"] == "agent"
    code, status = _json(capsys, ["project", "status", str(folder), "--json"])
    assert status["sources"] == 4 and status["requirements"] >= 6


def test_cli_classify_records_who_made_the_change(opened, capsys, monkeypatch):
    from howlwriter.cli import owner

    folder, _ = opened
    argv = ["project", "classify", str(folder), "draft notes.md", "rubric", "--json"]
    code, record = _json(capsys, [*argv, "--owner-confirmed"])
    assert code == 0 and record["category_source"] == "owner_relayed"
    monkeypatch.setattr(owner, "has_terminal", lambda: True)
    code, record = _json(capsys, argv)
    assert record["category_source"] == "user" and record["category_reason"] == "set by the user"


def test_cli_search_requirements_and_validation(opened, capsys, tmp_path):
    folder, _ = opened
    code, hits = _json(capsys, ["project", "search", str(folder), "TLS 1.3 certificate", "--json"])
    assert hits and "why" in hits[0]
    code, coverage = _json(capsys, ["project", "requirements", str(folder), "--json"])
    assert coverage["total"] >= 6
    draft = tmp_path / "draft.md"
    draft.write_text("## Results\n\nThe sensor generated 9 alerts [ev-000000000000].\n", encoding="utf-8")
    code, result = _json(capsys, ["project", "validate", str(folder), str(draft), "--json"])
    assert code == 3 and result["verdict"] == "BLOCKED"


def test_cli_skeleton_draft_is_saved_privately(opened, capsys, private_dirs, tmp_path):
    folder, _ = opened
    out = tmp_path / "skeleton.md"
    code = main(["project", "draft", str(folder), "--skeleton", "--out", str(out)])
    captured = capsys.readouterr()
    assert code == 0 and "[MISSING:" in out.read_text(encoding="utf-8")
    assert str(private_dirs) in captured.err


def test_cli_model_draft_refuses_remote_without_authorization(opened, capsys):
    folder, _ = opened
    from types import SimpleNamespace

    from howlwriter.integration.howlplane_bridge import set_howlplane_bridge

    set_howlplane_bridge(
        SimpleNamespace(
            registry=SimpleNamespace(get_binding=lambda d, r: SimpleNamespace(provider="openai")),
            is_available=lambda: True,
        )
    )
    assert main(["project", "draft", str(folder)]) == 2
    assert "authorize-remote" in capsys.readouterr().err


def test_cli_remote_gates_need_the_owner_without_a_terminal(opened, capsys, monkeypatch):
    import io
    import sys

    folder, _ = opened
    monkeypatch.setattr(sys, "stdin", io.StringIO())  # an agent or a script: nobody to ask
    assert main(["project", "authorize-remote", str(folder), "--json"]) == 4
    assert "only the owner may decide" in capsys.readouterr().err
    code, status = _json(capsys, ["project", "authorize-remote", str(folder), "--revoke", "--json"])
    assert code == 0 and status["remote_inference_authorized"] is False  # revoking keeps it local
    assert main(["project", "draft", str(folder), "--allow-remote"]) == 4  # refused before any model call
    capsys.readouterr()
    code, status = _json(
        capsys, ["project", "authorize-remote", str(folder), "--owner-confirmed", "--json"]
    )
    assert code == 0 and status["remote_inference_authorized"] is True


def test_cli_unknown_project_and_missing_voice(lab_folder, capsys):
    assert main(["project", "status", "no-such-project"]) == 1
    assert "no project" in capsys.readouterr().err


def test_cli_compare_requires_captures(opened, capsys):
    folder, _ = opened
    assert main(["project", "compare", str(folder), "draft notes.md", "tls-reference.docx"]) == 1
    assert "not a packet capture" in capsys.readouterr().err


def test_cli_compare_two_captures(lab_folder, capsys):
    pytest.importorskip("dpkt")
    from tests.projects.fixtures import make_pcap

    make_pcap(lab_folder / "evidence" / "before.pcap", tls13=False, http=False)
    make_pcap(lab_folder / "evidence" / "after.pcap", tls13=True, http=False)
    assert main(["project", "open", str(lab_folder), "--no-ocr", "--no-transcribe", "--json"]) == 0
    capsys.readouterr()
    code, data = _json(capsys, ["project", "compare", str(lab_folder), "before.pcap", "after.pcap", "--json"])
    assert code == 0 and data["status"] == "derived_by_calculation"
    assert {f["aspect"] for f in data["findings"]} >= {"frames and protocols", "TLS", "payload visibility"}


# --- web ---------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from howlwriter.web.app import create_app

    return TestClient(create_app())


def _wait(client, job):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['job_id']}").json()
        if job["status"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_web_open_scan_and_browse_evidence(client, lab_folder):
    pytest.importorskip("pypdf")
    opened = client.post("/api/projects", json={"folder": str(lab_folder)})
    assert opened.status_code == 200
    pid = opened.json()["project_id"]
    job = _wait(
        client, client.post(f"/api/projects/{pid}/scan", json={"ocr": False, "transcribe": False}).json()
    )
    assert job["status"] == "COMPLETED", job
    assert job["result"]["payload"]["files"] == 4
    sources = client.get(f"/api/projects/{pid}/sources").json()
    assert len(sources) == 4
    evidence = client.get(f"/api/projects/{pid}/evidence").json()
    assert evidence and all("text" not in e["observation"] for e in evidence)
    hits = client.get(f"/api/projects/{pid}/search", params={"q": "certificate TLS 1.3"}).json()
    assert hits and hits[0]["why"]
    notes = next(s for s in sources if s["path"] == "draft notes.md")
    changed = client.post(
        f"/api/projects/{pid}/sources/{notes['source_id']}/category", json={"category": "rubric"}
    )
    assert changed.json()["category"] == "rubric"
    # A client other than HowlWriter's page is recorded as an agent unless it relays the owner.
    assert changed.json()["category_source"] == "agent"
    url = f"/api/projects/{pid}/sources/{notes['source_id']}/category"
    page = client.post(url, json={"category": "rubric"}, headers={"Sec-Fetch-Site": "same-origin"})
    assert page.json()["category_source"] == "user"
    relayed = client.post(url, json={"category": "rubric"}, headers={"X-HowlWriter-Owner-Confirmed": "1"})
    assert relayed.json()["category_source"] == "owner_relayed"
    assert (
        client.post(
            f"/api/projects/{pid}/sources/{notes['source_id']}/category", json={"category": "bogus"}
        ).status_code
        == 400
    )


def test_web_requirements_skeleton_and_validation(client, lab_folder):
    pytest.importorskip("pypdf")
    pid = client.post("/api/projects", json={"folder": str(lab_folder)}).json()["project_id"]
    _wait(client, client.post(f"/api/projects/{pid}/scan", json={"ocr": False, "transcribe": False}).json())
    coverage = client.get(f"/api/projects/{pid}/requirements").json()
    assert coverage["total"] >= 6
    rid = coverage["rows"][0]["requirement_id"]
    marked = client.post(f"/api/projects/{pid}/requirements/{rid}/status", json={"status": "not_applicable"})
    assert marked.json()["status"] == "not_applicable"
    skeleton = client.post(f"/api/projects/{pid}/draft/skeleton", json={}).json()
    assert "[MISSING:" in skeleton["text"] and skeleton["path"].startswith("draft-")
    result = client.post(f"/api/projects/{pid}/validate", json={"text": skeleton["text"]}).json()
    assert (
        result["verdict"] in ("INCOMPLETE", "REVIEW") and "fabricated_citation" not in result["issue_counts"]
    )


def test_web_refuses_broad_or_private_folders(client, tmp_path):
    from pathlib import Path

    for folder in ("/", str(Path.home()), str(Path.home() / ".howlwriter"), str(tmp_path / "missing")):
        assert client.post("/api/projects", json={"folder": folder}).status_code == 400


def test_web_browser_requires_policy_and_session(client, lab_folder):
    pid = client.post("/api/projects", json={"folder": str(lab_folder)}).json()["project_id"]
    assert client.get(f"/api/projects/{pid}/browser").json()["state"] == "stopped"
    assert client.post(f"/api/projects/{pid}/browser/start", json={"mode": "research"}).status_code == 400
    assert (
        client.post(f"/api/projects/{pid}/browser/navigate", json={"url": "https://x.org"}).status_code == 409
    )
    assert client.post(f"/api/projects/{pid}/browser/actions/act-1/approve").status_code == 409
    assert client.post(f"/api/projects/{pid}/browser/explode").status_code == 404
    assert client.get("/api/projects/not-a-project").status_code == 404


def test_web_browser_session_lifecycle(client, lab_folder):
    pytest.importorskip("playwright")
    from howlwriter.projects.testlab import TestLab

    pid = client.post("/api/projects", json={"folder": str(lab_folder)}).json()["project_id"]
    with TestLab() as lab:
        started = client.post(
            f"/api/projects/{pid}/browser/start",
            json={"mode": "interactive", "interactive_origins": [lab.origin], "headless": True},
        )
        if started.status_code == 500:
            pytest.skip("Chromium unavailable")
        try:
            assert started.json()["state"] == "running"
            assert (
                client.post(f"/api/projects/{pid}/browser/navigate", json={"url": lab.url("/lab")}).json()[
                    "outcome"
                ]
                == "ok"
            )
            refused = client.post(
                f"/api/projects/{pid}/browser/request", json={"kind": "click", "selector": "#submit"}
            )
            assert refused.status_code == 403
            queued = client.post(
                f"/api/projects/{pid}/browser/request", json={"kind": "click", "selector": "#run"}
            ).json()
            assert queued["status"]["pending"]
            assert lab.state.runs == 0
            done = client.post(f"/api/projects/{pid}/browser/actions/{queued['action_id']}/approve").json()
            assert done["outcome"] == "ok" and lab.state.runs == 1
            assert client.post(f"/api/projects/{pid}/browser/pause").json()["state"] == "paused"
            assert client.post(f"/api/projects/{pid}/browser/read").status_code == 403
            assert client.post(f"/api/projects/{pid}/browser/resume").json()["state"] == "running"
            assert client.post(f"/api/projects/{pid}/browser/read-only").json()["policy"]["mode"] == "observe"
            status = client.get(f"/api/projects/{pid}/browser").json()
            assert any(a["changed_state"] for a in status["recent_actions"])
        finally:
            client.post(f"/api/projects/{pid}/browser/stop")
    assert client.get(f"/api/projects/{pid}/browser").json()["state"] == "stopped"


def test_web_remote_gates_need_the_page_or_the_owner(client, lab_folder):
    pid = client.post("/api/projects", json={"folder": str(lab_folder)}).json()["project_id"]
    refused = client.post(f"/api/projects/{pid}/authorize-remote")
    assert refused.status_code == 403 and refused.json()["code"] == "owner_confirmation_required"
    assert client.post(f"/api/projects/{pid}/draft", json={"allow_remote": True}).status_code == 403
    assert client.post(f"/api/projects/{pid}/authorize-remote?allow=false").status_code == 200
    relayed = client.post(
        f"/api/projects/{pid}/authorize-remote", headers={"X-HowlWriter-Owner-Confirmed": "1"}
    )
    assert relayed.json()["remote_inference_authorized"] is True
    page = client.post(f"/api/projects/{pid}/authorize-remote", headers={"Sec-Fetch-Site": "same-origin"})
    assert page.status_code == 200


@pytest.mark.parametrize(
    ("verdict", "flag", "expected"),
    [
        ("BLOCKED", True, 3),
        ("BLOCKED", False, 0),  # the documented default: the verdict is in the output
        ("READY_FOR_HUMAN_REVIEW", True, 0),
    ],
)
def test_cli_draft_fail_if_blocked_exits_3_on_a_not_ready_verdict(
    opened, capsys, monkeypatch, verdict, flag, expected
):
    from howlwriter.projects import writing
    from howlwriter.voice import selection

    folder, _ = opened
    seen = []

    def fake_draft(workspace, brief, **kwargs):
        seen.append(kwargs)
        provenance = {"validation": {"verdict": verdict}}
        return {"text": "## Results\n\nBody.", "path": "draft.md", "provenance": provenance}

    monkeypatch.setattr(writing, "draft", fake_draft)
    monkeypatch.setattr(selection, "apply_selection", lambda config, **kwargs: None)
    argv = ["project", "draft", str(folder), "--json"] + (["--fail-if-blocked"] if flag else [])
    assert main(argv) == expected
    assert len(seen) == 1
    assert json.loads(capsys.readouterr().out)["provenance"]["validation"]["verdict"] == verdict


def test_cli_skeleton_ignores_fail_if_blocked(opened, capsys, private_dirs, tmp_path):
    folder, _ = opened
    assert main(["project", "draft", str(folder), "--skeleton", "--fail-if-blocked"]) == 0
