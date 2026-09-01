"""Tests for web API lint and redpen endpoints."""

from fastapi.testclient import TestClient
from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_lint_endpoint():
    text = "In conclusion, it is important to delve into the tapestry of the ecosystem."
    res = client.post("/api/lint", json={"text": text, "title": "Draft"})
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] > 0
    rule_codes = [m["rule_code"] for m in data["matches"]]
    assert any(
        "BANNED" in code or "CLICHE" in code or "RHETORICAL" in code
        for code in rule_codes
    )


def test_redpen_endpoint():
    text = "# Introduction\n\nRecent empirical studies definitively confirm that everything is perfect."
    res = client.post("/api/redpen", json={"text": text, "title": "Draft"})
    assert res.status_code == 200
    data = res.json()
    assert "findings" in data
    assert isinstance(data["findings"], list)
