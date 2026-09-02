"""Discovery, canonicalization, and safe extraction."""

from __future__ import annotations

from pathlib import Path
import zipfile

from howlwriter.voice.corpus.discovery import (
    canonicalize_roots,
    classify_suffix,
    discover,
)
from howlwriter.voice.corpus.extract import (
    STATUS_OK,
    STATUS_SCANNED,
    STATUS_UNAVAILABLE,
    STATUS_UNSUPPORTED,
    extract,
)
from howlwriter.voice.corpus.extract.docx import extract_docx
from howlwriter.voice.corpus.extract.html import extract_html
from howlwriter.voice.corpus.extract.odt import extract_odt
from howlwriter.voice.corpus.extract.pdf import pypdf_available
from howlwriter.voice.corpus.extract.plain import extract_plain
from howlwriter.voice.corpus.extract.rtf import extract_rtf
from tests.voice.corpus.conftest import make_docx, make_odt, synthetic_prose

import pytest


# --- discovery ---------------------------------------------------------

def test_discovery_walks_recursively(corpus_dir: Path):
    (corpus_dir / "a").mkdir()
    (corpus_dir / "a" / "b").mkdir()
    (corpus_dir / "top.md").write_text(synthetic_prose(1), encoding="utf-8")
    (corpus_dir / "a" / "mid.md").write_text(synthetic_prose(2), encoding="utf-8")
    (corpus_dir / "a" / "b" / "deep.md").write_text(synthetic_prose(3), encoding="utf-8")

    result = discover([corpus_dir], recursive=True)
    names = {f.path.name for f in result.candidates}
    assert names == {"top.md", "mid.md", "deep.md"}


def test_discovery_can_stay_shallow(corpus_dir: Path):
    (corpus_dir / "a").mkdir()
    (corpus_dir / "top.md").write_text(synthetic_prose(1), encoding="utf-8")
    (corpus_dir / "a" / "deep.md").write_text(synthetic_prose(2), encoding="utf-8")

    result = discover([corpus_dir], recursive=False)
    assert {f.path.name for f in result.candidates} == {"top.md"}


def test_overlapping_roots_are_collapsed_before_reading(corpus_dir: Path):
    """A root nested inside another must not make its files count twice."""
    inner = corpus_dir / "inner"
    inner.mkdir()
    (inner / "paper.md").write_text(synthetic_prose(4), encoding="utf-8")

    result = discover([corpus_dir, inner, corpus_dir], recursive=True)

    assert result.roots_supplied == 3
    assert result.roots_after_canonicalization == 1
    assert len(result.candidates) == 1


def test_canonicalize_roots_drops_nested_and_duplicate_roots(tmp_path: Path):
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()

    kept, unreadable = canonicalize_roots([outer, inner, outer, other])

    assert set(kept) == {outer.resolve(), other.resolve()}
    assert unreadable == []


def test_canonicalize_roots_reports_missing_root(tmp_path: Path):
    kept, unreadable = canonicalize_roots([tmp_path / "nope"])
    assert kept == []
    assert unreadable == [str(tmp_path / "nope")]


def test_symlinked_duplicate_path_counts_once(corpus_dir: Path):
    real = corpus_dir / "real"
    real.mkdir()
    (real / "essay.md").write_text(synthetic_prose(5), encoding="utf-8")
    link = corpus_dir / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable here")

    result = discover([real, link], recursive=True)
    assert len(result.candidates) == 1


def test_source_code_and_binaries_are_excluded_with_reasons(corpus_dir: Path):
    (corpus_dir / "script.py").write_text("def main():\n    return 1\n" * 60, encoding="utf-8")
    (corpus_dir / "tool.exe").write_bytes(b"MZ" + b"\x00" * 2000)
    (corpus_dir / "data.csv").write_text("a,b\n1,2\n" * 200, encoding="utf-8")
    (corpus_dir / "deck.pptx").write_bytes(b"PK" + b"\x00" * 2000)
    (corpus_dir / "server.log").write_text("INFO x\n" * 400, encoding="utf-8")
    (corpus_dir / "real.md").write_text(synthetic_prose(6), encoding="utf-8")

    result = discover([corpus_dir])
    reasons = {f.path.name: f.reason for f in result.excluded}

    assert [f.path.name for f in result.candidates] == ["real.md"]
    assert reasons["script.py"] == "source_code"
    assert reasons["tool.exe"] == "binary_or_executable"
    assert reasons["data.csv"] == "structured_data"
    assert reasons["deck.pptx"] == "slide_deck"
    assert reasons["server.log"] == "machine_generated_log"


def test_tiny_and_enormous_files_are_excluded_with_a_stated_reason(corpus_dir: Path):
    (corpus_dir / "stub.md").write_text("hi", encoding="utf-8")
    result = discover([corpus_dir])
    assert {f.reason for f in result.excluded} == {"too_small"}


def test_classify_suffix_covers_prose_and_unknown():
    assert classify_suffix(".docx") == ("candidate", "")
    assert classify_suffix(".pdf") == ("candidate", "")
    assert classify_suffix(".go")[1] == "source_code"
    assert classify_suffix("")[1] == "no_extension"
    assert classify_suffix(".xyz")[1] == "unsupported_format"


# --- extraction --------------------------------------------------------

def test_docx_extraction_keeps_headings_and_lists(tmp_path: Path):
    path = make_docx(tmp_path / "paper.docx", [
        ("h1", "Introduction"),
        ("p", "The measurement boundary matters more than the throughput number."),
        ("li", "First observation"),
        ("p", "A second paragraph continues the argument."),
    ])
    result = extract_docx(path)

    assert result.ok and result.parser == "docx"
    assert "# Introduction" in result.text
    assert "- First observation" in result.text
    assert "measurement boundary" in result.text


def test_docx_extraction_never_opens_an_office_application(tmp_path: Path, monkeypatch):
    """A document must be inert data: no subprocess, no macro execution."""
    import subprocess

    def explode(*args, **kwargs):
        raise AssertionError("extraction must never spawn a process")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "call", explode)

    path = make_docx(tmp_path / "macro.docx", [("p", "Body text that is long enough to read.")])
    # A real macro-enabled document also carries a vbaProject part; adding one
    # proves the extractor ignores it rather than reacting to it.
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("word/vbaProject.bin", b"\x00\x01macro payload")

    result = extract_docx(path)
    assert result.ok
    assert "macro payload" not in result.text


def test_docx_with_no_body_part_fails_honestly(tmp_path: Path):
    path = tmp_path / "broken.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("something/else.xml", "<x/>")
    result = extract_docx(path)
    assert not result.ok
    assert "word/document.xml" in result.reason


def test_not_a_zip_fails_honestly(tmp_path: Path):
    path = tmp_path / "fake.docx"
    path.write_bytes(b"this is not a zip archive at all")
    result = extract_docx(path)
    assert not result.ok
    assert "docx archive" in result.reason


def test_odt_extraction(tmp_path: Path):
    path = make_odt(tmp_path / "note.odt", [
        "The deployment boundary held under load.",
        "The second paragraph adds a qualification.",
    ])
    result = extract_odt(path)
    assert result.ok and result.parser == "odt"
    assert "deployment boundary" in result.text
    assert "qualification" in result.text


def test_plain_text_and_markdown(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nA sentence about latency and ownership.\n", encoding="utf-8")
    result = extract_plain(path)
    assert result.ok
    assert "latency and ownership" in result.text


def test_binary_disguised_as_text_is_rejected(tmp_path: Path):
    path = tmp_path / "notreally.txt"
    path.write_bytes(b"\x00\x01\x02binary\x00payload" * 50)
    result = extract_plain(path)
    assert not result.ok
    assert "binary" in result.reason


def test_html_extraction_drops_script_and_style(tmp_path: Path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><style>body{color:red}</style></head><body>"
        "<script>alert('should never appear')</script>"
        "<h2>Findings</h2><p>The retention threshold was wrong.</p>"
        "<ul><li>One item</li></ul></body></html>",
        encoding="utf-8",
    )
    result = extract_html(path)
    assert result.ok
    assert "should never appear" not in result.text
    assert "color:red" not in result.text
    assert "## Findings" in result.text
    assert "retention threshold" in result.text
    assert "- One item" in result.text


def test_rtf_extraction_strips_control_words(tmp_path: Path):
    path = tmp_path / "memo.rtf"
    path.write_text(
        r"{\rtf1\ansi\deff0{\fonttbl{\f0 Times;}}"
        r"\f0\fs24 The rollback took eleven minutes.\par "
        r"That was longer than the incident itself.\par}",
        encoding="utf-8",
    )
    result = extract_rtf(path)
    assert result.ok
    assert "rollback took eleven minutes" in result.text
    assert "fonttbl" not in result.text
    assert "\\par" not in result.text


def test_legacy_doc_is_reported_as_unsupported(tmp_path: Path):
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 1000)
    result = extract(path)
    assert result.status == STATUS_UNSUPPORTED
    assert ".docx" in result.reason


def test_unreadable_file_is_reported_as_unavailable_not_failed(tmp_path: Path, monkeypatch):
    """A cloud placeholder the filesystem refuses is a distinct, reported state."""
    path = tmp_path / "placeholder.md"
    path.write_text(synthetic_prose(7), encoding="utf-8")

    original = Path.read_bytes

    def deny(self, *args, **kwargs):
        if self.name == "placeholder.md":
            raise PermissionError(1, "Operation not permitted")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", deny)
    result = extract(path)
    assert result.status == STATUS_UNAVAILABLE
    assert "denied read access" in result.reason


@pytest.mark.skipif(not pypdf_available(), reason="pypdf (the corpus extra) is not installed")
def test_scanned_pdf_is_skipped_gracefully(tmp_path: Path, monkeypatch):
    """An image-only PDF is reported as scanned. OCR is never attempted."""
    import pypdf

    from howlwriter.voice.corpus.extract import pdf as pdf_module

    class _Page:
        def extract_text(self):
            return "   "

    class _Reader:
        is_encrypted = False
        pages = [_Page(), _Page()]

        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(pypdf, "PdfReader", _Reader)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.7\n" + b"\x00" * 1000)

    result = pdf_module.extract_pdf(path)
    assert result.status == STATUS_SCANNED
    assert "OCR is deliberately not attempted" in result.reason


@pytest.mark.skipif(not pypdf_available(), reason="pypdf (the corpus extra) is not installed")
def test_pdf_with_text_layer_extracts(tmp_path: Path, monkeypatch):
    import pypdf

    from howlwriter.voice.corpus.extract import pdf as pdf_module

    body = synthetic_prose(8, paragraphs=3)

    class _Page:
        def extract_text(self):
            return body

    class _Reader:
        is_encrypted = False
        pages = [_Page()]

        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(pypdf, "PdfReader", _Reader)
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\n" + b"\x00" * 1000)

    result = pdf_module.extract_pdf(path)
    assert result.status == STATUS_OK
    assert body.split(".")[0] in result.text


def test_pdf_without_the_extra_reports_unavailable(tmp_path: Path, monkeypatch):
    """Missing the optional dependency degrades truthfully, it does not crash."""
    import builtins

    from howlwriter.voice.corpus.extract import pdf as pdf_module

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7\n" + b"\x00" * 1000)

    result = pdf_module.extract_pdf(path)
    assert result.status == STATUS_UNAVAILABLE
    assert "howlwriter[corpus]" in result.reason
