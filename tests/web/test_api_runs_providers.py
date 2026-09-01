"""Tests for runs history and provider inspection API."""

from fastapi.testclient import TestClient
from howlwriter.diagnostic.run_record import RunRecord, generate_run_id
from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_runs_endpoint(tmp_path):
    run_id = generate_run_id()
    record = RunRecord(
        run_id=run_id,
        command="paper",
        writing_mode="academic",
        success=True,
        status="READY",
    )
    record.save(runs_dir=tmp_path)

    # Test get run
    res = client.get("/api/runs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_providers_endpoint():
    res = client.get("/api/providers")
    assert res.status_code == 200
    data = res.json()
    assert "role_bindings" in data
    assert "available_providers" in data
    assert "reviewer_independence" in data
    roles = [r["role"] for r in data["role_bindings"]]
    assert "writer" in roles
    assert "humanizer" in roles
    assert "final_reviewer" in roles
