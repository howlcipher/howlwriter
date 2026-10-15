"""The drive scanner: read-only, resumable, incremental, honest about failure."""

from __future__ import annotations

import errno
import hashlib
import json
from pathlib import Path
import stat
import subprocess

import pytest

from howlwriter.voice.identity import analysis as analysis_module
from howlwriter.voice.identity import privacy
from howlwriter.voice.identity import scanner as scanner_module
from howlwriter.voice.identity.scanner import MountUnavailableError, scan
from howlwriter.voice.identity.store import IdentityStore

from tests.voice.identity.conftest import author_a


def _snapshot(root: Path) -> dict[str, tuple[str, float, int]]:
    out = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            info = path.stat()
            out[str(path)] = (
                hashlib.sha256(data).hexdigest(),
                info.st_mtime,
                stat.S_IMODE(info.st_mode),
            )
    return out


def test_scan_never_modifies_the_source(env, drive):
    before = _snapshot(drive)
    scan("william", sources=[str(drive)])
    scan("william")
    assert _snapshot(drive) == before
    assert sorted(p.name for p in drive.iterdir()) == ["Shared with Me", "school"]


def test_first_scan_inventories_and_classifies(env, drive):
    report = scan("william", sources=[str(drive)]).report
    assert report["files_inventoried"] == 24
    assert report["extracted_documents"] == 24
    assert report["exclusions"] == ["gemini gems", "retroarchsaves", "shared drives"]
    inventory = IdentityStore("william").load_inventory()
    shared = [
        e for e in inventory["entries"].values() if e["relative_path"].startswith("Shared with Me/")
    ]
    assert shared and all(e["ownership"] == "shared_with_me" for e in shared)
    assert all(e["proposal"]["authorship"] == "THIRD_PARTY" for e in shared)


def test_private_files_are_owner_only(env, drive):
    scan("william", sources=[str(drive)])
    directory = IdentityStore("william").directory
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name


def test_inventory_holds_no_document_text(env, drive):
    scan("william", sources=[str(drive)])
    raw = (IdentityStore("william").directory / "inventory.json").read_text(encoding="utf-8")
    assert "appears to confirm" not in raw
    assert "Click the blue button" not in raw


def test_rescan_reads_nothing_when_nothing_changed(env, drive):
    scan("william", sources=[str(drive)])
    report = scan("william").report
    assert report["read_this_scan"] == 0


def test_modified_added_removed_and_renamed_files_are_detected(env, drive):
    scan("william", sources=[str(drive)])
    (drive / "school" / "lab00.md").write_text(author_a(500), encoding="utf-8")
    (drive / "school" / "new.md").write_text(author_a(600), encoding="utf-8")
    (drive / "school" / "lab01.md").unlink()
    (drive / "school" / "lab02.md").rename(drive / "school" / "renamed.md")
    outcome = scan("william")
    changes = {e["relative_path"]: e.get("change") for e in outcome.inventory["entries"].values()}
    assert changes["school/lab00.md"] == "modified"
    assert changes["school/new.md"] == "added"
    assert changes["school/lab01.md"] == "removed"
    assert changes["school/renamed.md"] == "renamed"
    assert outcome.report["renamed_since_last_scan"] == 1
    renamed = next(
        e
        for e in outcome.inventory["entries"].values()
        if e["relative_path"] == "school/renamed.md"
    )
    assert "school/lab02.md" in renamed["previous_paths"]


def test_unavailable_mount_raises_and_leaves_inventory(env, drive, tmp_path):
    scan("william", sources=[str(drive)])
    path = IdentityStore("william").directory / "inventory.json"
    before = path.read_text(encoding="utf-8")
    moved = tmp_path / "unmounted"
    drive.rename(moved)
    with pytest.raises(MountUnavailableError):
        scan("william")
    assert path.read_text(encoding="utf-8") == before


def test_denied_read_is_native_unavailable_not_a_crash(env, tmp_path, monkeypatch):
    root = tmp_path / "drive"
    root.mkdir()
    (root / "Native Doc").write_text("x" * 97, encoding="utf-8")
    (root / "LICENSE").write_text("plain small file " * 5, encoding="utf-8")
    real = Path.read_bytes

    def fake(self):
        if self.name == "Native Doc":
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", fake)
    report = scan("william", sources=[str(root)]).report
    assert report["statuses"] == {"native_unavailable": 1, "nonprose_excluded": 1}
    assert report["coverage"]["complete"] is False


def test_transient_errors_are_retried(env, tmp_path, monkeypatch):
    root = tmp_path / "drive"
    root.mkdir()
    (root / "doc.md").write_text(author_a(1), encoding="utf-8")
    calls = {"n": 0}
    real = Path.read_bytes
    monkeypatch.setattr(scanner_module, "RETRY_BACKOFF_SECONDS", 0.0)

    def flaky(self):
        if self.name == "doc.md" and calls["n"] < 2:
            calls["n"] += 1
            raise OSError(errno.EIO, "Input/output error")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    report = scan("william", sources=[str(root)]).report
    assert report["extracted_documents"] == 1 and calls["n"] == 2


def test_file_changing_during_read_is_recorded(env, tmp_path, monkeypatch):
    root = tmp_path / "drive"
    root.mkdir()
    target = root / "doc.md"
    target.write_text(author_a(2), encoding="utf-8")
    real = Path.read_bytes

    def growing(self):
        data = real(self)
        if self.name == "doc.md":
            with open(self, "a", encoding="utf-8") as handle:
                handle.write(" more")
        return data

    monkeypatch.setattr(Path, "read_bytes", growing)
    report = scan("william", sources=[str(root)]).report
    assert report["statuses"].get("changed_during_read") == 1


def test_size_limits_and_unsupported_formats(env, tmp_path, monkeypatch):
    root = tmp_path / "drive"
    root.mkdir()
    (root / "tiny.md").write_text("hi", encoding="utf-8")
    (root / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 2000)
    (root / "big.md").write_text("word " * 700, encoding="utf-8")
    (root / "photo.jpg").write_bytes(b"\xff\xd8" + b"0" * 2000)
    monkeypatch.setattr(scanner_module, "MAX_FILE_BYTES", 2500)
    statuses = scan("william", sources=[str(root)]).report["statuses"]
    assert statuses == {
        "too_small": 1,
        "unsupported_format": 1,
        "too_large": 1,
        "nonprose_excluded": 1,
    }


def test_credentials_are_excluded_before_any_measurement(env, tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    (root / "notes.txt").write_text(
        "account notes\npassword: hunter2\n" + author_a(3), encoding="utf-8"
    )
    scan("william", sources=[str(root)])
    entry = next(iter(IdentityStore("william").load_inventory()["entries"].values()))
    assert entry["status"] == "sensitive_excluded"
    assert "derived" not in entry and "fingerprint" not in entry


def test_one_bad_document_does_not_abort_the_scan(env, drive, monkeypatch):
    real = analysis_module.analyze

    def sometimes_broken(**kwargs):
        if kwargs["relative_path"].endswith("lab03.md"):
            raise ValueError("synthetic parser failure")
        return real(**kwargs)

    monkeypatch.setattr(scanner_module.analysis, "analyze", sometimes_broken)
    report = scan("william", sources=[str(drive)]).report
    assert report["statuses"]["analysis_failed"] == 1
    assert report["extracted_documents"] == 23


def test_interrupted_scan_resumes_from_checkpoint(env, drive, monkeypatch):
    monkeypatch.setattr(scanner_module, "CHECKPOINT_EVERY", 5)
    real = analysis_module.analyze
    seen = {"n": 0}

    def crash_late(**kwargs):
        seen["n"] += 1
        if seen["n"] > 12:
            raise KeyboardInterrupt
        return real(**kwargs)

    monkeypatch.setattr(scanner_module.analysis, "analyze", crash_late)
    monkeypatch.setattr(scanner_module, "ThreadPoolExecutor", _SerialExecutor)
    with pytest.raises(KeyboardInterrupt):
        scan("william", sources=[str(drive)])
    monkeypatch.setattr(scanner_module.analysis, "analyze", real)
    report = scan("william").report
    assert report["read_this_scan"] < 24
    assert report["extracted_documents"] == 24


class _SerialExecutor:
    def __init__(self, max_workers=1):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, items):
        for item in items:
            yield fn(item)


def test_duplicates_are_grouped(env, tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    text = author_a(7)
    (root / "essay.md").write_text(text, encoding="utf-8")
    (root / "essay copy.md").write_text(text, encoding="utf-8")
    report = scan("william", sources=[str(root)]).report
    assert report["duplicates"] == 1


def test_ledger_refuses_an_unignored_location_inside_a_worktree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("HOWLWRITER_IDENTITIES_DIR", str(repo / "private_stuff"))
    with pytest.raises(privacy.PrivateLocationError):
        IdentityStore("william").ensure()
    (repo / ".gitignore").write_text("private_stuff/\n", encoding="utf-8")
    IdentityStore("william").ensure()  # ignored: allowed


def test_multiple_sources_are_namespaced(env, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "a.md").write_text(author_a(11), encoding="utf-8")
    (second / "a.md").write_text(author_a(12), encoding="utf-8")
    entries = scan("william", sources=[str(first), str(second)]).inventory["entries"].values()
    assert sorted(e["relative_path"] for e in entries) == ["0:a.md", "1:a.md"]


def test_scan_report_contains_no_file_names(env, drive):
    scan("william", sources=[str(drive)])
    report = json.dumps(IdentityStore("william").load_scan_report())
    assert "lab0" not in report and "guide" not in report


class _FakeRequest:
    def __init__(self, value):
        self.value = value

    def execute(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _FakeDrive:
    """Just enough of the Drive v3 surface for the fallback."""

    def __init__(self, text: str):
        self.text = text
        self.queries: list[str] = []
        self.writes = 0

    def files(self):
        return self

    def revisions(self):
        return _FakeRevisions()

    def list(self, q, **kwargs):
        self.queries.append(q)
        if "Doc Title" in q:
            return _FakeRequest(
                {
                    "files": [
                        {
                            "id": "abc",
                            "name": "Doc Title",
                            "modifiedTime": "2026-02-01T00:00:00Z",
                            "ownedByMe": True,
                        }
                    ]
                }
            )
        return _FakeRequest({"files": []})

    def export(self, fileId, mimeType):
        assert mimeType == "text/plain"
        return _FakeRequest(self.text.encode("utf-8"))


class _FakeRevisions:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "revisions": [
                    {"id": "1", "modifiedTime": "2026-01-01T00:00:00Z"},
                    {"id": "2", "modifiedTime": "2026-01-15T00:00:00Z"},
                ]
            }
        )


def test_google_api_fallback_is_opt_in_and_reads_only(env, tmp_path, monkeypatch):
    root = tmp_path / "drive"
    root.mkdir()
    (root / "Doc Title").write_text("x" * 97, encoding="utf-8")
    (root / "Another Doc").write_text("x" * 97, encoding="utf-8")
    real = Path.read_bytes

    def denied(self):
        if self.parent == root:
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", denied)
    fake = _FakeDrive(author_a(77))

    report = scan("william", sources=[str(root)]).report
    assert report["native_cloud_unavailable"] == 2 and "google_api" not in report

    report = scan("william", google_api=True, google_service_factory=lambda: fake).report
    assert report["google_api"]["exported"] == 1
    assert report["google_api"]["not_found_or_ambiguous"] == 1
    assert all("trashed = false" in q for q in fake.queries)
    entry = next(
        e
        for e in IdentityStore("william").load_inventory()["entries"].values()
        if e["relative_path"] == "Doc Title"
    )
    assert entry["status"] == "extracted" and entry["parser"] == "google_drive_api_export"
    assert entry["provenance"]["revision_count"] == 2


def test_google_api_without_token_refuses_clearly(env, tmp_path, monkeypatch):
    from howlwriter.voice.identity import google_fallback

    monkeypatch.setenv("HOWLWRITER_CREDENTIALS_DIR", str(tmp_path / "creds"))
    with pytest.raises(google_fallback.GoogleFallbackUnavailable):
        google_fallback.drive_service()
