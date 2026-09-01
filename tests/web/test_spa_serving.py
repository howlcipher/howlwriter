"""Tests for SPA static asset serving in FastAPI app."""

from fastapi.testclient import TestClient
from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_serve_index_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "HowlWriter" in res.text
    assert '<div id="root">' in res.text


def test_serve_spa_client_routes():
    for route in ["/workspace", "/academic", "/runs", "/providers"]:
        res = client.get(route)
        assert res.status_code == 200
        assert '<div id="root">' in res.text
