"""The local API answers only loopback Hosts and refuses cross-origin writes."""

import pytest
from fastapi.testclient import TestClient

from howlwriter.web.app import create_app

BASE = "http://127.0.0.1:8765"
BODY = {"path": "a.md", "content": "one two"}


def _client(**kw):
    return TestClient(create_app(**kw), base_url=BASE)


def test_foreign_host_header_is_refused():
    res = _client().get("/api/providers/choices", headers={"Host": "evil.example"})
    assert res.status_code == 400
    res = _client().post("/api/documents/stats", json=BODY, headers={"Host": "evil.example:8765"})
    assert res.status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "localhost", "127.0.0.1:1234"])
def test_loopback_hosts_are_answered(host):
    assert _client().post("/api/documents/stats", json=BODY, headers={"Host": host}).status_code == 200


def test_testserver_host_is_not_allowed():
    res = TestClient(create_app()).post("/api/documents/stats", json=BODY)
    assert res.status_code == 400


def test_foreign_origin_write_is_refused():
    res = _client().post("/api/documents/stats", json=BODY, headers={"Origin": "http://evil.example"})
    assert res.status_code == 403
    assert res.json()["code"] == "origin_not_allowed"
    for method in ("put", "patch", "delete"):
        res = getattr(_client(), method)("/api/documents/stats", headers={"Origin": "http://evil.example"})
        assert res.status_code == 403


def test_other_local_port_origin_is_refused():
    res = _client().post("/api/documents/stats", json=BODY, headers={"Origin": "http://localhost:3000"})
    assert res.status_code == 403


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:8765", "http://localhost:8765", "http://localhost:5173", "http://127.0.0.1:5173"],
)
def test_app_and_vite_origins_pass(origin):
    res = _client().post("/api/documents/stats", json=BODY, headers={"Origin": origin})
    assert res.status_code == 200


def test_no_origin_passes_and_reads_ignore_origin():
    assert _client().post("/api/documents/stats", json=BODY).status_code == 200
    res = _client().get("/api/providers/choices", headers={"Origin": "http://evil.example"})
    assert res.status_code == 200


def test_origin_follows_the_port_given_to_create_app():
    app = create_app(port=9000)
    client = TestClient(app, base_url="http://127.0.0.1:9000")
    assert client.post("/api/documents/stats", json=BODY, headers={"Origin": "http://127.0.0.1:9000"}).status_code == 200
    res = client.post("/api/documents/stats", json=BODY, headers={"Origin": "http://127.0.0.1:8765"})
    assert res.status_code == 403


def test_ipv6_loopback_only_when_bound_to_it():
    v4 = TestClient(create_app(), base_url="http://127.0.0.1:8765")
    assert v4.get("/api/providers/choices", headers={"Host": "[::1]:8765"}).status_code == 400
    v6 = TestClient(create_app(host="::1"), base_url="http://[::1]:8765")
    assert v6.post("/api/documents/stats", json=BODY).status_code == 200
    res = v6.post("/api/documents/stats", json=BODY, headers={"Origin": "http://[::1]:8765"})
    assert res.status_code == 200


def test_http_error_body_has_code_error_and_detail():
    res = _client().post("/api/documents/open", json={"path": "/nonexistent-dir-xyz/none.md"})
    body = res.json()
    assert res.status_code == 404
    assert body["code"] == "not_found"
    assert body["error"] == body["detail"]
