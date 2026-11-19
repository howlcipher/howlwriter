"""A JSON body must declare itself as JSON (FastAPI strict_content_type)."""

from fastapi.testclient import TestClient

from howlwriter.web.app import create_app

client = TestClient(create_app(), base_url="http://127.0.0.1:8765")


def test_json_body_without_content_type_is_rejected():
    res = client.post("/api/documents/stats", content=b'{"path": "a.md", "content": "x"}')
    assert res.status_code == 422
    res = client.post(
        "/api/documents/stats",
        content=b'{"path": "a.md", "content": "x"}',
        headers={"Content-Type": "text/plain"},
    )
    assert res.status_code == 422


def test_json_body_with_content_type_is_accepted():
    res = client.post("/api/documents/stats", json={"path": "a.md", "content": "x"})
    assert res.status_code == 200
