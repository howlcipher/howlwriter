"""Tests for standard local output management, safe filenames, and collisions."""

from pathlib import Path
import pytest

from howlwriter.output.naming import (
    OutputCollisionError,
    PathTraversalError,
    safe_filename,
    sanitize_filename_base,
)
from howlwriter.output.manager import LocalOutputManager


def test_sanitize_filename_base():
    assert sanitize_filename_base("Simple Title") == "simple-title"
    assert sanitize_filename_base("AI & Society: Ethical / Legal Issues!") == "ai-society-ethical-legal-issues"
    assert sanitize_filename_base("   ") == "artifact"
    assert sanitize_filename_base("---") == "artifact"
    assert sanitize_filename_base("..hidden..") == "hidden"


def test_safe_filename():
    assert safe_filename("Cybersecurity", ".md") == "cybersecurity.md"
    assert safe_filename("Research Paper", "docx") == "research-paper.docx"

    # Preserves extension and truncates base if too long
    long_title = "a" * 300
    fname = safe_filename(long_title, ".pdf", max_length=50)
    assert len(fname) == 54  # 50 base + 4 (.pdf)
    assert fname.endswith(".pdf")


def test_safe_filename_path_traversal():
    with pytest.raises(PathTraversalError):
        safe_filename("../escape", ".md")

    with pytest.raises(PathTraversalError):
        safe_filename("foo/bar", ".md")

    with pytest.raises(PathTraversalError):
        safe_filename("/etc/passwd", ".txt")

    with pytest.raises(PathTraversalError):
        safe_filename("foo\\bar", ".txt")


def test_output_manager_write_and_collision(tmp_path: Path):
    out_dir = tmp_path / "custom_output"
    mgr = LocalOutputManager(output_dir=out_dir)

    # First write creates directory and file
    deliv = mgr.write_deliverable(
        content="# Hello World",
        format_extension=".md",
        title_or_slug="Test Document",
    )
    p = Path(deliv.path)
    assert p.is_file()
    assert p.read_text(encoding="utf-8") == "# Hello World"
    assert deliv.format == "md"
    assert deliv.size_bytes > 0
    assert deliv.sha256 is not None

    # Writing again without overwrite raises OutputCollisionError
    with pytest.raises(OutputCollisionError):
        mgr.write_deliverable(
            content="# Colliding Content",
            format_extension=".md",
            title_or_slug="Test Document",
            overwrite=False,
        )

    # Writing with overwrite=True succeeds
    deliv2 = mgr.write_deliverable(
        content="# Updated Content",
        format_extension=".md",
        title_or_slug="Test Document",
        overwrite=True,
    )
    assert Path(deliv2.path).read_text(encoding="utf-8") == "# Updated Content"


def test_output_manager_save_binary(tmp_path: Path):
    mgr = LocalOutputManager(output_dir=tmp_path)
    content = b"\x50\x4b\x03\x04fake docx binary"
    deliv = mgr.write_deliverable(
        content=content,
        format_extension=".docx",
        title_or_slug="sample",
    )
    p = Path(deliv.path)
    assert p.is_file()
    assert p.read_bytes() == content
    assert deliv.format == "docx"
    assert deliv.size_bytes == len(content)


def test_output_manifest_creation(tmp_path: Path):
    mgr = LocalOutputManager(output_dir=tmp_path)
    d1 = mgr.write_deliverable(
        content="Content 1",
        format_extension=".md",
        title_or_slug="doc1",
    )
    d2 = mgr.write_deliverable(
        content=b"Binary 2",
        format_extension=".bin",
        title_or_slug="doc2",
    )

    manifest_path = mgr.write_manifest(
        run_id="run-12345",
        title="My Assignment",
        authorized_artifact_hash="hash-abc",
        deliverables=[d1, d2],
        manifest_filename="custom_manifest.json",
    )
    assert manifest_path.is_file()
    text = manifest_path.read_text()
    assert '"run_id": "run-12345"' in text
    assert '"title": "My Assignment"' in text
    assert '"authorized_artifact_hash": "hash-abc"' in text


def test_output_gitkeep_and_gitignore():
    """Verify repo git hygiene rules for output directory."""
    root = Path(__file__).parent.parent.parent
    gitkeep = root / "output" / ".gitkeep"
    assert gitkeep.is_file(), "output/.gitkeep must exist and be tracked"

    gitignore_path = root / ".gitignore"
    if gitignore_path.is_file():
        content = gitignore_path.read_text()
        assert "output/*" in content
        assert "!output/.gitkeep" in content
