"""The web app sends no CORS headers: only its own page (same origin) may talk to it."""

from fastapi.testclient import TestClient

from howlwriter.web.app import create_app

client = TestClient(create_app(), base_url="http://127.0.0.1:8765")

ORIGINS = [
    "http://evil.com",
    "https://evil.com",
    "http://attacker.org",
    "http://localhost.evil.com",
    "http://127.0.0.1.evil.com",
    "http://localhost:3000",
    "http://127.0.0.1:8000",
    "http://localhost",
]


def _assert_no_cors(res):
    assert not any(name.lower().startswith("access-control-") for name in res.headers), dict(res.headers)


def test_no_cors_headers_for_any_cross_origin_request():
    for origin in ORIGINS:
        _assert_no_cors(client.get("/api/providers/choices", headers={"Origin": origin}))
        preflight = client.options(
            "/api/documents/stats",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-howlwriter-owner-confirmed",
            },
        )
        _assert_no_cors(preflight)
        assert preflight.status_code in (400, 403, 405)


def test_same_origin_requests_still_work():
    res = client.get("/api/providers/choices", headers={"Origin": "http://127.0.0.1:8765"})
    assert res.status_code == 200
    res = client.post(
        "/api/documents/stats",
        json={"path": "a.md", "content": "one two"},
        headers={"Origin": "http://127.0.0.1:8765"},
    )
    assert res.status_code == 200
    _assert_no_cors(res)
