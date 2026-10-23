"""Tests for web API publishing and Google status endpoints."""

from pathlib import Path
from fastapi.testclient import TestClient

from tests.fakes.google_docs import FakeGoogleDocsAdapter
from howlwriter.publishing.google.publisher import GoogleDocsPublisher
from howlwriter.publishing.registry import register_publisher
from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_api_google_status(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOWLWRITER_CREDENTIALS_DIR", str(tmp_path / "creds"))
    res = client.get("/api/publish/google/status")
    assert res.status_code == 200
    data = res.json()
    assert "authenticated" in data
    assert data["authenticated"] is False
    assert "token_path" in data


def test_api_publish_nonexistent_file():
    res = client.post(
        "/api/publish",
        json={
            "file_path": "/tmp/nonexistent_howlwriter_file_12345.md",
            "destination": "google-docs",
        },
    )
    assert res.status_code == 404
    data = res.json()
    err_msg = data.get("error") or data.get("detail", "")
    assert "File not found" in err_msg


def test_api_publish_unsupported_destination(tmp_path: Path):
    doc_path = tmp_path / "paper.md"
    doc_path.write_text("# Test\nContent", encoding="utf-8")

    res = client.post(
        "/api/publish",
        json={
            "file_path": str(doc_path),
            "destination": "unknown_cloud_dest",
        },
    )
    assert res.status_code == 400
    data = res.json()
    err_msg = data.get("error") or data.get("detail", "")
    assert "Unsupported" in err_msg


def test_api_publish_success(tmp_path: Path):
    fake = FakeGoogleDocsAdapter()
    pub = GoogleDocsPublisher(adapter=fake)
    register_publisher("google_docs", pub)
    register_publisher("google-docs", pub)

    doc_path = tmp_path / "final_report.md"
    doc_path.write_text("# Final Security Audit\n\nAll tests passed.", encoding="utf-8")

    res = client.post(
        "/api/publish",
        json={
            "file_path": str(doc_path),
            "destination": "google-docs",
            "title": "Cloud Security Audit",
            "allow_unverified": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["document_id"] is not None
    assert "docs.google.com" in data["document_url"]


def test_api_publish_of_a_file_with_windows_line_endings_is_not_refused_as_changed(tmp_path: Path):
    # The approval hash must describe the text that is published, not the raw bytes the platform decoded.
    fake = FakeGoogleDocsAdapter()
    pub = GoogleDocsPublisher(adapter=fake)
    register_publisher("google_docs", pub)
    register_publisher("google-docs", pub)
    doc_path = tmp_path / "crlf.md"
    doc_path.write_bytes(b"# Report\r\n\r\nAll tests passed on the second run today.\r\n")
    res = client.post("/api/publish", json={"file_path": str(doc_path), "destination": "google-docs",
                                            "allow_unverified": True})
    data = res.json()
    assert data["success"] is True and data["status"] == "SUCCESS"


def test_api_publish_reports_the_real_status_when_the_destination_does_not_confirm(tmp_path: Path):
    fake = FakeGoogleDocsAdapter()
    fake.truncate_tail_chars = 20
    pub = GoogleDocsPublisher(adapter=fake)
    register_publisher("google_docs", pub)
    register_publisher("google-docs", pub)
    doc_path = tmp_path / "doc.md"
    doc_path.write_text("# Report\n\nAll of these tests passed on the second run today without incident.", encoding="utf-8")
    data = client.post("/api/publish", json={"file_path": str(doc_path), "destination": "google-docs",
                                             "allow_unverified": True}).json()
    assert data["success"] is False and data["status"] == "UNCONFIRMED" and data["document_id"]
