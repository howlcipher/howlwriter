"""The provenance endpoint: read-only, and private by default.

The privacy stance matches /api/voices, which returns summaries by default and
source paths only on request. A provenance record at full level carries every
prompt HowlWriter built, and those prompts carry the user's own sentences.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from howlwriter.domain.generation_provenance import (
    ContributionSummary,
    GenerationProvenance,
    ModelCallRecord,
    StageRecord,
)
from howlwriter.provenance.assemble import save_provenance
from howlwriter.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    return TestClient(create_app())


def _record(run_id: str = "hw-test-1") -> GenerationProvenance:
    return GenerationProvenance(
        run_id=run_id,
        workflow="howl-outline",
        writing_mode="linkedin",
        generation_freedom="LOW",
        outline_present=True,
        complete=True,
        artifact_sha256="a" * 64,
        calls=[
            ModelCallRecord(
                sequence=1,
                role="writer",
                provider="agy",
                model=None,
                system_instruction="SYSTEM TEXT",
                user_prompt="EXACT PROMPT THE USER WOULD RECOGNISE",
                user_prompt_sha256="b" * 64,
                user_prompt_chars=37,
            ),
            ModelCallRecord(
                sequence=2,
                role="final_reviewer",
                provider="codex",
                model="some-model",
                model_status="REPORTED",
                independence_status="INDEPENDENT",
            ),
        ],
        stages=[
            StageRecord(name="outline_writer", sequence=1, model_backed=True, call_sequences=[1]),
            StageRecord(name="outline_coverage", sequence=2, status="PASS"),
        ],
        contribution=ContributionSummary(claims_supplied=3, claims_represented=3),
    )


def test_a_run_without_provenance_reports_that_rather_than_an_empty_record(client):
    response = client.get("/api/provenance/hw-nonexistent")
    assert response.status_code == 404
    assert "no provenance record" in response.json()["error"].lower()


def test_prompts_are_withheld_by_default(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    save_provenance(_record(), level="full")

    body = client.get("/api/provenance/hw-test-1").json()

    assert body["prompts_included"] is False
    assert all(call["user_prompt"] == "" for call in body["calls"])
    # Hashes and lengths still travel, so the record stays checkable.
    assert body["calls"][0]["user_prompt_sha256"]
    assert body["calls"][0]["user_prompt_chars"] == 37


def test_prompts_are_returned_only_on_explicit_request(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    save_provenance(_record(), level="full")

    body = client.get("/api/provenance/hw-test-1?include_prompts=true").json()

    assert body["prompts_included"] is True
    assert "EXACT PROMPT THE USER WOULD RECOGNISE" in body["calls"][0]["user_prompt"]


def test_a_summary_record_says_why_it_has_no_prompts(client, tmp_path, monkeypatch):
    """Empty prompt text must not read as "no prompt was sent"."""
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    save_provenance(_record(), level="summary")

    body = client.get("/api/provenance/hw-test-1?include_prompts=true").json()

    assert "recorded at summary level" in body.get("prompt_note", "")


def test_the_timeline_orders_stages_and_attaches_their_calls(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    save_provenance(_record())

    timeline = client.get("/api/provenance/hw-test-1").json()["timeline"]

    assert [n["name"] for n in timeline][:2] == ["outline_writer", "outline_coverage"]
    assert timeline[0]["calls"] == [1]
    assert timeline[0]["model_backed"] is True


def test_a_call_no_stage_claims_still_appears_on_the_timeline(client, tmp_path, monkeypatch):
    """An unattributed model invocation is exactly what an inspector should surface."""
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    save_provenance(_record())

    timeline = client.get("/api/provenance/hw-test-1").json()["timeline"]
    names = [n["name"] for n in timeline]

    assert "final_reviewer" in names
    unattributed = next(n for n in timeline if n["name"] == "final_reviewer")
    assert "not attributed" in unattributed["detail"]


def test_unknown_models_are_counted_and_never_filled_in(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    save_provenance(_record())

    body = client.get("/api/provenance/hw-test-1").json()

    assert body["unknown_model_calls"] == 1
    assert body["models_used"] == ["some-model"]
    writer = next(c for c in body["calls"] if c["role"] == "writer")
    assert writer["model"] is None
    assert writer["model_status"] == "PROVIDER_DID_NOT_REPORT"


def test_the_endpoint_serves_the_manifest_it_generated(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path))
    save_provenance(_record())

    body = client.get("/api/provenance/hw-test-1").json()
    assert "HowlWriter Generation Manifest" in body["manifest"]
    assert "not reported by provider" in body["manifest"]


def test_the_provenance_routes_are_read_only(client):
    """No verb here may alter a record of something that already happened."""
    schema = client.get("/openapi.json").json()
    provenance_paths = {p: v for p, v in schema["paths"].items() if "/api/provenance" in p}

    assert provenance_paths
    for path, verbs in provenance_paths.items():
        assert set(verbs) <= {"get"}, f"{path} exposes more than GET"
