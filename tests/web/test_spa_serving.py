"""Tests for SPA static asset serving in FastAPI app."""

from fastapi.testclient import TestClient
from howlwriter.web.app import create_app

client = TestClient(create_app(), base_url="http://127.0.0.1:8765")


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


def _spa(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text('<div id="root">HowlWriter</div>', encoding="utf-8")
    (static / "logo.txt").write_text("logo", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    return create_app(static_dir=static)


def test_static_file_is_served_and_traversal_is_not(tmp_path):
    spa = TestClient(_spa(tmp_path), base_url="http://127.0.0.1:8765")
    assert spa.get("/logo.txt").text == "logo"
    for path in ("/..%2Fsecret.txt", "/..%2F..%2Fsecret.txt", "/%2e%2e%2fsecret.txt"):
        res = spa.get(path)
        assert "TOP-SECRET" not in res.text
        assert res.status_code in (200, 404)


def test_traversal_through_raw_asgi_scope_is_not_served(tmp_path):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import unquote

    app = _spa(tmp_path)

    async def call(raw):
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "scheme": "http", "path": unquote(raw), "raw_path": raw.encode(), "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:8765")], "server": ("127.0.0.1", 8765),
            "client": ("127.0.0.1", 5555), "root_path": "",
        }
        out = {}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                out["status"] = message["status"]
            if message["type"] == "http.response.body":
                out["body"] = out.get("body", b"") + message.get("body", b"")

        await app(scope, receive, send)
        return out

    for raw in ("/..%2Fsecret.txt", "/..%2F..%2Fsecret.txt"):
        # A worker thread has no running loop, even when an earlier test left one behind.
        with ThreadPoolExecutor(1) as pool:
            out = pool.submit(asyncio.run, call(raw)).result()
        assert b"TOP-SECRET" not in out["body"]
        assert out["status"] == 200 and b'id="root"' in out["body"]


def test_bare_api_path_is_404(tmp_path):
    spa = TestClient(_spa(tmp_path), base_url="http://127.0.0.1:8765")
    assert spa.get("/api").status_code == 404
    assert spa.get("/api/nope").status_code == 404
