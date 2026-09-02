"""The voices API: summaries by default, source paths only on request."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from howlwriter.voice.corpus.build import build_voice
from howlwriter.web.app import create_app
from tests.voice.corpus.conftest import synthetic_prose

REAL_SENTENCE = (
    "The rollback took eleven minutes, which was longer than the incident that "
    "caused it, and nobody had touched the runbook since the migration."
)


@pytest.fixture
def voices(tmp_path, monkeypatch):
    """Build two local voices into a temporary registry."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for index in range(14):
        (corpus / f"secret_project_{index}.md").write_text(
            f"# Note {index}\n\n{REAL_SENTENCE}\n\n{synthetic_prose(index)}\n",
            encoding="utf-8",
        )
    registry = tmp_path / "voices"
    registry.mkdir()
    monkeypatch.setenv("HOWLWRITER_VOICES_DIR", str(registry))

    build_voice("jane", [corpus], store_root=registry, deterministic_only=True)
    build_voice("house-style", [corpus], store_root=registry,
                deterministic_only=True, profile_type="shared_style")
    return registry


@pytest.fixture
def client():
    return TestClient(create_app())


def test_listing_voices(client, voices):
    response = client.get("/api/voices")
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert names == {"jane", "house-style"}

    jane = next(row for row in response.json() if row["name"] == "jane")
    assert jane["profile_type"] == "personal_voice"
    assert jane["included_documents"] > 0
    assert jane["training_words"] > 0
    assert jane["overall_confidence"]


def test_listing_is_empty_when_no_voices_exist(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_VOICES_DIR", str(tmp_path / "none"))
    assert client.get("/api/voices").json() == []


def test_voice_detail_returns_traits_and_evidence(client, voices):
    response = client.get("/api/voices/jane")
    assert response.status_code == 200
    body = response.json()

    assert body["name"] == "jane"
    assert body["version"] >= 1
    assert body["traits"]
    for trait in body["traits"]:
        assert trait["value"]
        assert trait["confidence_band"] in ("HIGH", "MEDIUM", "LOW", "VERY_LOW", "UNKNOWN")
        assert trait["supporting_documents"] >= 0
    assert body["corpus"]["included_documents"] > 0
    assert "overall_confidence" in body["validation"]


def test_voice_detail_never_contains_corpus_prose_or_paths(client, voices):
    """The privacy invariant, asserted at the API boundary."""
    body = client.get("/api/voices/jane").text
    assert "rollback took eleven minutes" not in body
    assert "since the migration" not in body
    assert "secret_project" not in body


def test_a_shared_style_reports_its_own_type(client, voices):
    assert client.get("/api/voices/house-style").json()["profile_type"] == "shared_style"


def test_unknown_voice_is_a_404_that_explains_itself(client, voices):
    response = client.get("/api/voices/nobody")
    assert response.status_code == 404
    assert "voice build" in response.json()["error"]


def test_an_unsafe_name_is_rejected(client, voices):
    assert client.get("/api/voices/..%2Fescape").status_code in (400, 404)


def test_sources_are_withheld_without_explicit_confirmation(client, voices):
    response = client.get("/api/voices/jane/sources")
    assert response.status_code == 400
    assert "private local data" in response.json()["error"]
    assert "secret_project" not in response.text


def test_sources_are_returned_when_explicitly_requested(client, voices):
    response = client.get("/api/voices/jane/sources", params={"confirm": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "jane"
    assert body["sources"]
    for record in body["sources"]:
        assert record["path"]
        assert "text" not in record
    # It names files, which is exactly why it is behind the flag.
    assert any("secret_project" in record["path"] for record in body["sources"])


def test_rebuild_runs_on_the_existing_job_runner(client, voices):
    response = client.post(
        "/api/voices/jane/rebuild", json={"deterministic": True, "reuse_cache": True}
    )
    assert response.status_code == 200
    job = response.json()
    assert job["job_type"] == "voice_rebuild"
    assert job["job_id"]
    assert [stage["id"] for stage in job["stages"]][:3] == [
        "discovering", "extracting", "deduplicating",
    ]

    # The job is threaded; poll the shared job endpoint until it settles.
    import time
    for _ in range(200):
        status = client.get(f"/api/jobs/{job['job_id']}").json()
        if status["status"] in ("COMPLETED", "FAILED"):
            break
        time.sleep(0.05)
    assert status["status"] == "COMPLETED", status.get("error_message")
    assert status["result"]["name"] == "jane"
    assert status["result"]["detail"]["traits"]


def test_rebuild_of_an_unknown_voice_is_a_404(client, voices):
    assert client.post("/api/voices/nobody/rebuild", json={}).status_code == 404


def test_humanize_accepts_a_named_voice(client, voices):
    response = client.post("/api/humanize", json={
        "text": "This is a short document. It says one thing and then stops.",
        "deterministic_only": True,
        "voice": "jane",
    })
    assert response.status_code == 200


def test_humanize_rejects_both_voice_flags_at_once(client, voices):
    response = client.post("/api/humanize", json={
        "text": "Some text here that is long enough to process.",
        "deterministic_only": True,
        "voice": "jane",
        "voice_profile": "/tmp/other.json",
    })
    assert response.status_code == 400
    assert "alternatives" in response.json()["error"]


def test_humanize_rejects_an_unknown_named_voice(client, voices):
    response = client.post("/api/humanize", json={
        "text": "Some text here that is long enough to process.",
        "deterministic_only": True,
        "voice": "nobody",
    })
    assert response.status_code == 400
    assert "no personal voice named" in response.json()["error"]


def test_the_existing_voice_profile_field_still_works(client, voices, tmp_path):
    from howlwriter.domain.voice import VoiceProfile

    legacy = tmp_path / "legacy.json"
    legacy.write_text(VoiceProfile(author_name="A Writer").to_json(), encoding="utf-8")
    response = client.post("/api/humanize", json={
        "text": "Some text here that is long enough to process.",
        "deterministic_only": True,
        "voice_profile": str(legacy),
    })
    assert response.status_code == 200


def test_the_openapi_schema_exposes_the_voice_endpoints(client, voices):
    schema = client.get("/openapi.json").json()
    assert "/api/voices" in schema["paths"]
    assert "/api/voices/{name}" in schema["paths"]
    assert "/api/voices/{name}/rebuild" in schema["paths"]


def test_existing_serializers_remain_compatible(client, voices):
    """Adding the voice field must not break the endpoints that predate it."""
    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/providers").status_code == 200
    assert client.post("/api/lint", json={"text": "A short document to lint."}).status_code == 200
