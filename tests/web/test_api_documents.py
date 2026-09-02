"""Tests for web API documents endpoints."""

from pathlib import Path
from fastapi.testclient import TestClient

from howlwriter.web.app import create_app

client = TestClient(create_app())


def test_open_and_save_document(tmp_path: Path):
    doc_path = tmp_path / "test_doc.md"
    doc_path.write_text("# Test Document\n\nThis is a sample document for testing.", encoding="utf-8")

    # Open
    res = client.post("/api/documents/open", json={"path": str(doc_path)})
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "test_doc"
    assert "sample document" in data["content"]
    assert data["word_count"] > 0
    assert data["line_count"] == 3

    # Save
    new_content = "# Updated Title\n\nNew paragraph content here with more words."
    res_save = client.post("/api/documents/save", json={"path": str(doc_path), "content": new_content})
    assert res_save.status_code == 200
    assert doc_path.read_text(encoding="utf-8") == new_content

    # Open non-existent
    res_err = client.post("/api/documents/open", json={"path": str(tmp_path / "missing.md")})
    assert res_err.status_code == 404


def test_document_stats():
    res = client.post(
        "/api/documents/stats",
        json={"path": "sample.md", "content": "One two three four five."},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["word_count"] == 5
    assert data["title"] == "sample"
