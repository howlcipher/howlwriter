"""Unit tests for the evaluation Web API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from howlwriter.web.app import create_app


def test_web_evaluation_cases_endpoint():
    app = create_app()
    client = TestClient(app)

    res = client.get("/api/evaluation/cases")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 30
    assert any(c["id"] == "academic_privacy_001" for c in data)


def test_web_evaluation_runs_endpoint():
    app = create_app()
    client = TestClient(app)

    res = client.get("/api/evaluation/runs")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
