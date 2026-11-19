"""Which files the document and publish endpoints may touch."""

import os

import pytest
from fastapi.testclient import TestClient

from howlwriter.web.app import create_app


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


@pytest.fixture
def client(home):
    return TestClient(create_app(), base_url="http://127.0.0.1:8765")


def _open(client, path):
    return client.post("/api/documents/open", json={"path": str(path)})


def _save(client, path, content="hello"):
    return client.post("/api/documents/save", json={"path": str(path), "content": content})


def _refused(res):
    assert res.status_code == 403, res.text
    assert res.json()["code"] == "path_not_allowed"
    assert res.json()["detail"]


def test_normal_markdown_opens_and_saves(client, home):
    doc = home / "notes" / "a.MD"
    doc.parent.mkdir()
    doc.write_text("# T\n\nbody", encoding="utf-8")
    assert _open(client, doc).status_code == 200
    assert _save(client, doc, "new").status_code == 200
    assert doc.read_text() == "new"
    assert _save(client, home / "notes" / "fresh.txt").status_code == 200


def test_tilde_is_expanded(client, home):
    (home / "a.md").write_text("x", encoding="utf-8")
    assert client.post("/api/documents/open", json={"path": "~/a.md"}).status_code == 200


def test_missing_file_in_allowed_place_is_404(client, home):
    assert _open(client, home / "missing.md").status_code == 404


def test_open_inside_dot_directories_is_refused(client, home):
    for rel in (".ssh/id.txt", ".config/x.md", ".local/share/x.md", "proj/.hidden/x.md", ".notes.md"):
        target = home / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("secret", encoding="utf-8")
        _refused(_open(client, target))
        _refused(_save(client, target))
    _refused(_open(client, home / ".ssh" / "missing.md"))


def test_private_howlwriter_folder_is_refused(client, home):
    private = home / ".howlwriter" / "voice"
    private.mkdir(parents=True)
    (private / "p.md").write_text("private", encoding="utf-8")
    _refused(_open(client, private / "p.md"))
    _refused(_save(client, private / "p.md"))
    # A dotless alias that resolves into it is caught on the resolved path.
    (home / "alias").symlink_to(home / ".howlwriter")
    _refused(_open(client, home / "alias" / "voice" / "p.md"))


def test_dotdot_cannot_hide_a_dot_directory(client, home):
    (home / ".ssh").mkdir()
    (home / "x.md").write_text("x", encoding="utf-8")
    _refused(_open(client, f"{home}/.ssh/../x.md"))
    _refused(_open(client, f"{home}/.ssh/x.md"))


def test_other_suffixes_are_refused(client, home):
    for name in ("x.desktop", "x.sh", "x", "x.md.exe", "x.docx"):
        _refused(_save(client, home / name))
    (home / "x.py").write_text("print()", encoding="utf-8")
    _refused(_open(client, home / "x.py"))


def test_symlinks_are_refused(client, home):
    real = home / "real.md"
    real.write_text("real", encoding="utf-8")
    (home / "link.md").symlink_to(real)
    _refused(_open(client, home / "link.md"))
    _refused(_save(client, home / "link.md"))
    assert real.read_text() == "real"


def test_file_inside_a_symlinked_directory_is_allowed(client, home):
    real_dir = home / "real_dir"
    real_dir.mkdir()
    (real_dir / "a.md").write_text("hi", encoding="utf-8")
    (home / "link_dir").symlink_to(real_dir)
    assert _open(client, home / "link_dir" / "a.md").status_code == 200
    assert _save(client, home / "link_dir" / "b.md").status_code == 200
    assert (real_dir / "b.md").read_text() == "hello"


def test_symlink_to_other_suffix_or_dot_directory_is_refused(client, home):
    (home / "target.sh").write_text("echo", encoding="utf-8")
    (home / "notes.md").symlink_to(home / "target.sh")
    _refused(_open(client, home / "notes.md"))
    (home / ".ssh").mkdir()
    (home / ".ssh" / "k.md").write_text("k", encoding="utf-8")
    (home / "k.md").symlink_to(home / ".ssh" / "k.md")
    _refused(_open(client, home / "k.md"))
    # A symlinked directory into a dot-directory is refused on the resolved path.
    (home / "viadir").symlink_to(home / ".ssh")
    _refused(_open(client, home / "viadir" / "k.md"))


def test_save_does_not_create_directories_and_needs_a_regular_file(client, home):
    _refused(_save(client, home / "nope" / "x.md"))
    assert not (home / "nope").exists()
    (home / "dir.md").mkdir()
    _refused(_save(client, home / "dir.md"))
    _refused(_open(client, home / "dir.md"))


def test_fifo_is_refused(client, home):
    fifo = home / "pipe.md"
    os.mkfifo(fifo)
    _refused(_open(client, fifo))


def test_stats_does_not_touch_the_filesystem(client, home):
    res = client.post("/api/documents/stats", json={"path": "/etc/passwd", "content": "a b"})
    assert res.status_code == 200


def test_publish_applies_the_same_location_rules(client, home, monkeypatch):
    (home / ".ssh").mkdir()
    (home / ".ssh" / "n.md").write_text("x", encoding="utf-8")
    (home / "n.json").write_text("{}", encoding="utf-8")
    (home / "n.csv").write_text("a", encoding="utf-8")
    (home / "real.md").write_text("x", encoding="utf-8")
    (home / "link.md").symlink_to(home / "real.md")
    for name in (".ssh/n.md", "n.json", "n.csv", "link.md"):
        res = client.post("/api/publish", json={"file_path": str(home / name), "destination": "local"})
        _refused(res)
    res = client.post("/api/publish", json={"file_path": str(home / "absent.md"), "destination": "local"})
    assert res.status_code == 404
