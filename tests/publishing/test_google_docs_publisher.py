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
from tests.fakes.google_docs import FakeGoogleDocsAdapter
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
        authorized_sha256="",
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
        authorized_sha256="",
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
        authorized_sha256="",
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
        authorized_sha256="",
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
        authorized_sha256="",
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

    # Logout should remove the file (the network call is faked; never contact Google)
    from howlwriter.publishing.google import auth as gauth

    monkeypatch.setattr(gauth, "_revoke_remote", lambda token: (True, "ok"))
    result = revoke_and_logout()
    assert result.remote_revoked is True
    assert result.local_deleted is True
    assert not token_p.exists()


def _write_token(tmp_path, monkeypatch, payload):
    import json

    monkeypatch.setenv("HOWLWRITER_CREDENTIALS_DIR", str(tmp_path / "creds"))
    token_p = get_token_path()
    token_p.write_text(json.dumps(payload), encoding="utf-8")
    return token_p


def test_logout_prefers_refresh_token_and_posts_form_body(tmp_path, monkeypatch):
    from howlwriter.publishing.google import auth as gauth

    token_p = _write_token(tmp_path, monkeypatch, {"token": "access-x", "refresh_token": "refresh-y"})
    seen = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["data"] = req.data
        seen["timeout"] = timeout
        return Resp()

    monkeypatch.setattr(gauth.urllib.request, "urlopen", fake_urlopen)
    result = revoke_and_logout()
    assert result.remote_revoked and result.local_deleted
    assert seen["url"] == "https://oauth2.googleapis.com/revoke"  # token not in the URL
    assert seen["data"] == b"token=refresh-y"
    assert seen["timeout"]
    assert not token_p.exists()


def test_logout_http_400_and_exception_are_reported(tmp_path, monkeypatch):
    import urllib.error

    from howlwriter.publishing.google import auth as gauth

    token_p = _write_token(tmp_path, monkeypatch, {"token": "access-x"})

    def bad(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)

    monkeypatch.setattr(gauth.urllib.request, "urlopen", bad)
    result = revoke_and_logout()
    assert not result.remote_revoked and result.local_deleted
    assert "400" in result.detail
    assert not token_p.exists()

    token_p = _write_token(tmp_path, monkeypatch, {"token": "access-x"})

    def boom(req, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(gauth.urllib.request, "urlopen", boom)
    result = revoke_and_logout()
    assert not result.remote_revoked and result.local_deleted
    assert "TimeoutError" in result.detail


def test_cli_logout_messages_and_exit_codes(tmp_path, monkeypatch, capsys):
    import argparse

    from howlwriter.cli.commands import google as gcli
    from howlwriter.publishing.google.auth import LogoutResult

    _write_token(tmp_path, monkeypatch, {"token": "t"})
    monkeypatch.setattr(gcli, "revoke_and_logout", lambda: LogoutResult(True, True, "ok"))
    assert gcli.run_logout(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "confirmed" in out and "myaccount.google.com" not in out

    monkeypatch.setattr(gcli, "revoke_and_logout", lambda: LogoutResult(False, True, "HTTP 400"))
    assert gcli.run_logout(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "NOT revoked" in out and "https://myaccount.google.com/permissions" in out

    monkeypatch.setattr(gcli, "revoke_and_logout", lambda: LogoutResult(False, False, "denied"))
    assert gcli.run_logout(argparse.Namespace()) == 1


def test_save_credentials_is_private(tmp_path, monkeypatch):
    import stat

    from howlwriter.publishing.google.auth import save_credentials

    monkeypatch.setenv("HOWLWRITER_CREDENTIALS_DIR", str(tmp_path / "creds"))

    class C:
        def to_json(self):
            return '{"token": "x"}'

    save_credentials(C())
    assert stat.S_IMODE(get_token_path().stat().st_mode) == 0o600
    assert get_token_path().read_text(encoding="utf-8") == '{"token": "x"}'


def test_client_config_env_expands_user(tmp_path, monkeypatch):
    from howlwriter.publishing.google.auth import get_client_secrets_path

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HOWLWRITER_CREDENTIALS_DIR", str(tmp_path / "creds"))
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOWLWRITER_GOOGLE_CLIENT_CONFIG", "~/x.json")
    assert get_client_secrets_path() == (tmp_path / "x.json").resolve()


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _FakeDriveFiles:
    def __init__(self, folders=None, list_error=None):
        self.folders = folders or {}  # id -> name
        self.list_error = list_error
        self.queries = []
        self.created = []
        self.updated = []

    def get(self, fileId, fields):
        def run():
            if fileId in self.folders:
                return {"id": fileId, "mimeType": "application/vnd.google-apps.folder"}
            if fileId == "doc1":
                return {"id": "doc1", "parents": ["root"]}
            raise KeyError("404 not found")

        return _Exec(run)

    def list(self, q, fields):
        def run():
            self.queries.append(q)
            if self.list_error:
                raise self.list_error
            return {"files": []}

        return _Exec(run)

    def create(self, body, fields):
        def run():
            self.created.append(body)
            return {"id": "newfolder"}

        return _Exec(run)

    def update(self, **kw):
        self.updated.append(kw)
        return _Exec(lambda: {"id": kw["fileId"], "parents": [kw["addParents"]]})


class _FakeDrive:
    def __init__(self, **kw):
        self.f = _FakeDriveFiles(**kw)

    def files(self):
        return self.f


def _real_adapter(drive):
    from howlwriter.publishing.google.publisher import _RealGoogleApiAdapter

    return _RealGoogleApiAdapter(docs_service=None, drive_service=drive)


def test_move_to_folder_uses_real_folder_id_without_creating():
    drive = _FakeDrive(folders={"FOLDERID123": "x"})
    _real_adapter(drive).move_to_folder("doc1", "FOLDERID123")
    assert drive.f.created == []
    assert drive.f.updated[0]["addParents"] == "FOLDERID123"


def test_move_to_folder_escapes_name_in_query():
    drive = _FakeDrive()
    _real_adapter(drive).move_to_folder("doc1", "Bob's \\ notes")
    assert "name='Bob\\'s \\\\ notes'" in drive.f.queries[0]
    assert drive.f.created[0]["name"] == "Bob's \\ notes"


def test_move_to_folder_list_error_is_raised_not_swallowed():
    import pytest

    drive = _FakeDrive(list_error=RuntimeError("quota exceeded"))
    with pytest.raises(RuntimeError, match="quota"):
        _real_adapter(drive).move_to_folder("doc1", "Some Name")
    assert drive.f.updated == [] and drive.f.created == []
