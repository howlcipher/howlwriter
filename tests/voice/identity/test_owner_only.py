"""Owner-only changes refuse when nobody can be asked.

Authorship decisions and Workshop answers decide what trains the person's
voice. Run by an AI agent or a script (no terminal, or a non-browser HTTP
client), they must say the owner gave the decision, and are then recorded as
relayed; otherwise nothing changes.
"""

from __future__ import annotations

import io
import sys

import pytest

from howlwriter.cli.main import main
from howlwriter.voice.identity import review
from howlwriter.voice.identity import workshop as ws
from howlwriter.voice.identity.scanner import scan
from howlwriter.voice.identity.store import IdentityStore

ANSWER = "Short version: the parser choked on a malformed header, so I made it skip and log it instead."


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def scanned(env, drive, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO())  # no terminal, as for an agent
    scan("william", sources=[str(drive)])
    pending = review.queue(IdentityStore("william"))
    assert pending
    return pending[0].doc_id


def _decisions():
    return IdentityStore("william").load_decisions()


def test_set_without_terminal_refuses_and_changes_nothing(scanned, capsys):
    assert main(["voice", "review", "--identity", "william", "--set", scanned, "h"]) == 4
    assert not _decisions()
    assert "only the owner may decide" in capsys.readouterr().err


def test_set_relayed_by_the_owner_is_recorded_as_relayed(scanned):
    command = ["voice", "review", "--identity", "william", "--set", scanned, "h", "--owner-confirmed"]
    assert main(command) == 0
    assert _decisions()[scanned].source == "owner_relayed"


def test_set_at_a_terminal_needs_no_flag(scanned, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Terminal())
    assert main(["voice", "review", "--identity", "william", "--set", scanned, "h"]) == 0
    assert _decisions()[scanned].source == "user_attestation"


def test_piped_interactive_review_refuses_even_with_the_flag(scanned):
    sys.stdin.write("h\nh\nh\n")
    sys.stdin.seek(0)
    command = ["voice", "review", "--identity", "william", "--interactive", "--owner-confirmed"]
    assert main(command) == 4
    assert not _decisions()


def test_worksheet_apply_without_terminal_refuses(scanned, tmp_path):
    sheet = tmp_path / "queue.yaml"
    sheet.write_text(f"pending:\n- doc_id: {scanned}\n  decision: h\n", encoding="utf-8")
    assert main(["voice", "review", "--identity", "william", "--apply", str(sheet)]) == 4
    assert not _decisions()
    assert main(["voice", "review", "--identity", "william", "--apply", str(sheet), "--owner-confirmed"]) == 0
    assert _decisions()[scanned].source == "owner_relayed"


def test_reading_the_queue_needs_no_owner(scanned):
    assert main(["voice", "review", "--identity", "william", "--json"]) == 0


def _answer(*extra: str) -> list[str]:
    prompt = ws.Workshop("agent").next_prompt(context="technical")
    return [
        "voice", "workshop", "--identity", "agent", "answer", "--prompt-id", prompt.prompt_id,
        "--subject", prompt.subject, "--text", ANSWER, *extra,
    ]


def test_workshop_answer_as_own_writing_needs_the_owner(env, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    assert main(_answer("--self-written", "--approve")) == 4
    assert not ws.Workshop("agent").samples()
    # An answer that claims nothing about who wrote it never counts, so it may be saved.
    assert main(_answer()) == 0
    sample = next(iter(ws.Workshop("agent").samples().values()))
    assert not sample.self_written
    assert main(["voice", "workshop", "--identity", "agent", "remove", sample.sample_id]) == 4
    assert main(["voice", "workshop", "--identity", "agent", "exclude", sample.sample_id]) == 0
    assert main(["voice", "workshop", "--identity", "agent"]) == 4  # no session without a terminal


def test_workshop_relayed_answer_is_saved(env, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    assert main(_answer("--self-written", "--approve", "--owner-confirmed")) == 0
    (sample,) = ws.Workshop("agent").samples().values()
    assert sample.status == ws.STATUS_APPROVED


@pytest.fixture
def client(scanned):
    from fastapi.testclient import TestClient

    from howlwriter.web.app import create_app

    return TestClient(create_app())


@pytest.mark.parametrize(
    "headers, status, source",
    [
        ({}, 403, None),
        ({"Sec-Fetch-Site": "cross-site"}, 403, None),
        ({"Sec-Fetch-Site": "same-origin"}, 200, "user_attestation"),
        ({"X-HowlWriter-Owner-Confirmed": "1"}, 200, "owner_relayed"),
    ],
)
def test_web_attestation_needs_the_page_or_the_owner(client, scanned, headers, status, source):
    response = client.post(
        f"/api/voice-intel/william/review/{scanned}", json={"authorship": "h"}, headers=headers
    )
    assert response.status_code == status
    if status == 403:
        assert response.json()["code"] == "owner_confirmation_required"
        assert not _decisions()
    else:
        assert _decisions()[scanned].source == source


def test_web_workshop_owner_only_actions(client):
    prompt = client.post("/api/voice-intel/william/workshop/prompt", json={"context": "technical"}).json()
    body = {"prompt_id": prompt["prompt_id"], "subject": prompt["subject"], "text": ANSWER}
    samples = "/api/voice-intel/william/workshop/samples"
    assert client.post(samples, json={**body, "self_written": True}).status_code == 403
    saved = client.post(samples, json=body)
    assert saved.status_code == 200
    sid = saved.json()["sample_id"]
    assert client.post(f"{samples}/{sid}/actions/approve").status_code == 403
    assert client.post(f"{samples}/{sid}/actions/remove").status_code == 403
    assert client.post(f"{samples}/{sid}/context", json={"context": "casual"}).status_code == 403
    assert client.post(f"{samples}/{sid}/actions/exclude").status_code == 200


def test_agent_guide_matches_the_code():
    from pathlib import Path

    from howlwriter.cli import owner as cli_owner
    from howlwriter.web import owner as web_owner

    root = Path(__file__).resolve().parents[3]
    guide = (root / "docs" / "agents.md").read_text(encoding="utf-8")
    assert f"| {cli_owner.EXIT_OWNER_REQUIRED} |" in guide
    assert web_owner.OWNER_CONFIRMED_HEADER in guide and "--owner-confirmed" in guide
    assert cli_owner.SOURCE_RELAYED in guide
    assert "docs/agents.md" in (root / "AGENTS.md").read_text(encoding="utf-8")
    for entry in ("CLAUDE.md", "GEMINI.md"):
        assert (root / entry).read_text(encoding="utf-8").strip() == "@AGENTS.md"
