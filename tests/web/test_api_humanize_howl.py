"""Tests for web API humanize and howl endpoints."""

from fastapi.testclient import TestClient
from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_humanize_deterministic_endpoint():
    text = "We must delve into the tapestry of the problem."
    res = client.post(
        "/api/humanize",
        json={"text": text, "deterministic_only": True, "apply_safe_rewrites": True},
    )
    assert res.status_code == 200
    data = res.json()
    assert "transformed_text" in data
    assert "run_id" in data
    assert data["run_id"].startswith("hw-")
    assert data["meaning_preservation_status"] == "PASS"


def test_howl_deterministic_endpoint():
    text = (
        "# Section One\n\nContent for section one with some detailed words.\n\n"
        "## Section Two\n\nMore details."
    )
    res = client.post(
        "/api/howl",
        json={"text": text, "deterministic_only": True},
    )
    assert res.status_code == 200
    data = res.json()
    assert "final_text" in data
    assert "status" in data
    assert data["run_id"].startswith("hw-")
