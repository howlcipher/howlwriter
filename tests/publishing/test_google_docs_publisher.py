"""Tests for Google Docs publishing adapter using hermetic FakeGoogleDocsAdapter."""

from pathlib import Path

from howlwriter.publishing.base import (
    PublicationArtifact,
    PublishContext,
    PublishDestination,
)
from howlwriter.publishing.google.auth import (
    get_auth_status,
    get_token_path,
    revoke_and_logout,
)
from howlwriter.publishing.google.fake import FakeGoogleDocsAdapter
from howlwriter.publishing.google.publisher import GoogleDocsPublisher


def test_create_new_google_doc_with_formatting():
    fake = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake)

    artifact = PublicationArtifact(
        title="AI Ethics in Medicine",
        content=(
            "# AI Ethics in Medicine\n\n"
            "Autonomous diagnostic tools raise liability questions (Smith, 2024).\n\n"
            "## Key Challenges\n\n"
            "- Algorithmic bias\n"
            "- Explainability\n\n"
            "More details at [FDA Guidance](https://www.fda.gov/ai)."
        ),
        format="md",
        source_run_id="run-101",
        authorized_sha256="sha-101",
        metadata={"status": "READY"},
    )
    dest = PublishDestination(
        destination_type="google_docs",
        target="Research Folder",
        folder="Research Folder",
    )
    ctx = PublishContext(run_id="run-101")

    result = publisher.publish(artifact, dest, ctx)

    assert result.is_success
    assert result.status == "SUCCESS"
    assert result.artifact_id is not None
    assert result.url == f"https://docs.google.com/document/d/{result.artifact_id}/edit"

    doc = fake.get_document(result.artifact_id)
    assert doc["title"] == "AI Ethics in Medicine"
    assert "Autonomous diagnostic tools raise liability questions" in doc["body"]
    assert doc["folder"] == "Research Folder"


def test_update_existing_google_doc_replace():
    fake = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake)

    # Pre-create a document
    existing = fake.create_document("Initial Title")
    existing_id = existing["documentId"]
    fake.batch_update(existing_id, [{"insertText": {"text": "Old draft content that must be replaced.\n"}}])

    artifact = PublicationArtifact(
        title="Updated Title",
        content="New finalized body text.",
        format="md",
        source_run_id="run-102",
        authorized_sha256="sha-102",
        metadata={"status": "READY"},
    )
    dest = PublishDestination(
        destination_type="google_docs",
        update_doc_id=existing_id,
        update_mode="replace",
    )
    ctx = PublishContext(run_id="run-102")

    result = publisher.publish(artifact, dest, ctx)

    assert result.is_success
    assert result.artifact_id == existing_id
    updated_doc = fake.get_document(existing_id)
    assert "Old draft content" not in updated_doc["body"]
    assert "New finalized body text." in updated_doc["body"]


def test_update_existing_google_doc_append():
    fake = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake)

    existing = fake.create_document("Log Document")
    existing_id = existing["documentId"]
    fake.batch_update(existing_id, [{"insertText": {"text": "Section 1 content.\n"}}])

    artifact = PublicationArtifact(
        title="Appendix",
        content="Section 2 appended content.",
        format="md",
        source_run_id="run-103",
        authorized_sha256="sha-103",
        metadata={"status": "READY"},
    )
    dest = PublishDestination(
        destination_type="google_docs",
        update_doc_id=existing_id,
        update_mode="append",
    )
    ctx = PublishContext(run_id="run-103")

    result = publisher.publish(artifact, dest, ctx)

    assert result.is_success
    doc = fake.get_document(existing_id)
    assert "Section 1 content." in doc["body"]
    assert "Section 2 appended content." in doc["body"]


def test_update_nonexistent_doc_fails_gracefully():
    fake = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake)

    artifact = PublicationArtifact(
        title="Ghost Doc",
        content="Content",
        format="md",
        source_run_id="run-104",
        authorized_sha256="sha-104",
        metadata={"status": "READY"},
    )
    dest = PublishDestination(
        destination_type="google_docs",
        update_doc_id="ghost-id-9999",
        update_mode="replace",
    )
    ctx = PublishContext(run_id="run-104")

    result = publisher.publish(artifact, dest, ctx)
    assert not result.is_success
    assert result.status == "FAILED"
    assert any("ghost-id-9999" in d or "404" in d for d in result.diagnostics)


def test_simulated_api_errors():
    fake = FakeGoogleDocsAdapter()
    publisher = GoogleDocsPublisher(adapter=fake)

    artifact = PublicationArtifact(
        title="Error Test Doc",
        content="Content",
        format="md",
        source_run_id="run-105",
        authorized_sha256="sha-105",
        metadata={"status": "READY"},
    )
    dest = PublishDestination(destination_type="google_docs")
    ctx = PublishContext(run_id="run-105")

    # 1. Permission error
    fake.simulate_permission_error = True
    res_perm = publisher.publish(artifact, dest, ctx)
    assert not res_perm.is_success
    assert any("permission" in d.lower() for d in res_perm.diagnostics)

    # 2. Network error
    fake.simulate_permission_error = False
    fake.simulate_network_error = True
    res_net = publisher.publish(artifact, dest, ctx)
    assert not res_net.is_success
    assert any("timed out" in d.lower() or "connection" in d.lower() for d in res_net.diagnostics)


def test_auth_status_and_logout(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_CREDENTIALS_DIR", str(tmp_path / "creds"))

    status = get_auth_status()
    assert status["authenticated"] is False
    assert "message" in status

    # Simulate token creation
    token_p = get_token_path()
    token_p.write_text('{"token": "fake-token"}', encoding="utf-8")
    assert token_p.is_file()

    # Logout should remove the file
    removed = revoke_and_logout()
    assert removed is True
    assert not token_p.exists()
