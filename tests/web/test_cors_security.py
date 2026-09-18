"""Tests for CORS security configuration in HowlWriter web app (HOWL-CANON-022)."""

from fastapi.testclient import TestClient
from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_cors_preflight_rejected_for_external_origin():
    """External origins such as evil.com must be rejected and not receive CORS allow headers."""
    external_origins = [
        "http://evil.com",
        "https://evil.com",
        "http://attacker.org",
        "http://localhost.evil.com",
        "http://127.0.0.1.evil.com",
    ]
    for origin in external_origins:
        res = client.options(
            "/api/docs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        # Starlette CORS middleware returns 400 or omits Access-Control-Allow-Origin for disallowed origins
        allow_origin = res.headers.get("access-control-allow-origin")
        assert (
            allow_origin != origin and allow_origin != "*"
        ), f"Disallowed origin {origin} was improperly permitted"
        assert res.headers.get("access-control-allow-credentials") != "true"


def test_cors_preflight_allowed_for_loopback():
    """Loopback origins (localhost and 127.0.0.1 with various ports) must be permitted."""
    loopback_origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ]
    for origin in loopback_origins:
        res = client.options(
            "/api/docs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert res.status_code == 200, f"Loopback origin {origin} failed pre-flight: {res.status_code}"
        assert res.headers.get("access-control-allow-origin") == origin
        # Wildcard credentials must be disabled
        assert res.headers.get("access-control-allow-credentials") != "true"
