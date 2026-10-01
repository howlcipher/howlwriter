import json
import os

import pytest

from howlwriter.materials import ExtractionStatus, MaterialRole, scan_materials
from howlwriter.materials import scan as scan_mod
from tests.materials.builders import ZT, build_package, make_pdf


def _by_path(scan):
    return {r.path: r for r in scan.ledger.records}


def test_inventory_lists_every_file_with_roles(tmp_path):
    build_package(tmp_path / "pkg")
    scan = scan_materials(tmp_path / "pkg", exclude=[tmp_path / "pkg" / "assignment.yaml"])
    recs = _by_path(scan)
    assert set(recs) == {
        "instructions.txt", "grading-rubric.md", "lecture-notes.md",
        "reference-document.docx", "reference-paper.pdf", "lab-artifact.pcap",
    }
    assert recs["instructions.txt"].role == MaterialRole.INSTRUCTIONS
    assert recs["grading-rubric.md"].role == MaterialRole.RUBRIC
    assert recs["instructions.txt"].role_source == "heuristic"
    assert recs["lecture-notes.md"].role == MaterialRole.REFERENCE
    assert all(r.sha256 and len(r.sha256) == 64 for r in recs.values())


def test_requirements_are_not_evidence(tmp_path):
    build_package(tmp_path / "pkg")
    recs = _by_path(scan_materials(tmp_path / "pkg"))
    for name in ("instructions.txt", "grading-rubric.md"):
        assert recs[name].may_be_requirements is True
        assert recs[name].may_be_evidence is False
        assert recs[name].evidence_depth is None


def test_docx_and_pdf_yield_full_text_evidence(tmp_path):
    pytest.importorskip("pypdf")
    build_package(tmp_path / "pkg")
    scan = scan_materials(tmp_path / "pkg")
    recs = _by_path(scan)
    for name in ("reference-document.docx", "reference-paper.pdf", "lecture-notes.md"):
        r = recs[name]
        assert r.extraction_status == ExtractionStatus.OK, (name, r.warnings)
        assert r.may_be_evidence and r.evidence_depth == "FULL_TEXT"
        assert "microsegmentation" in scan.texts[r.material_id].lower()


def test_pcap_is_inventoried_but_never_evidence(tmp_path):
    build_package(tmp_path / "pkg")
    scan = scan_materials(tmp_path / "pkg")
    pcap = _by_path(scan)["lab-artifact.pcap"]
    assert pcap.extraction_status == ExtractionStatus.REQUIRES_EXTERNAL_INSPECTION
    assert pcap.role == MaterialRole.AUXILIARY
    assert not pcap.text_extracted and not pcap.may_be_evidence and not pcap.may_be_requirements
    assert pcap.material_id not in scan.texts
    assert pcap.warnings


def test_explicit_override_beats_heuristic(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    (root / "rubric-notes.txt").write_text("This is background reading about topics. " * 10)
    heuristic = _by_path(scan_materials(root))["rubric-notes.txt"]
    assert heuristic.role == MaterialRole.RUBRIC and heuristic.role_source == "heuristic"
    forced = _by_path(scan_materials(root, overrides={"rubric-notes.txt": "reference"}))["rubric-notes.txt"]
    assert forced.role == MaterialRole.REFERENCE and forced.role_source == "explicit"
    assert forced.may_be_evidence and not forced.may_be_requirements


def test_invalid_override_role_is_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("x" * 50)
    with pytest.raises(ValueError, match="invalid material role"):
        scan_materials(tmp_path, overrides={"a.txt": "bogus"})


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret outside content " * 10)
    root = tmp_path / "m"
    root.mkdir()
    os.symlink(outside, root / "link.txt")
    os.symlink(tmp_path, root / "dirlink")
    scan = scan_materials(root)
    recs = _by_path(scan)
    assert recs["link.txt"].extraction_status == ExtractionStatus.SKIPPED_SYMLINK
    assert recs["dirlink"].extraction_status == ExtractionStatus.SKIPPED_SYMLINK
    assert not scan.texts


def test_ledger_has_no_absolute_paths_and_is_deterministic(tmp_path):
    build_package(tmp_path / "pkg")
    a = scan_materials(tmp_path / "pkg").ledger.to_json()
    b = scan_materials(tmp_path / "pkg").ledger.to_json()
    assert a == b
    assert str(tmp_path) not in a
    data = json.loads(a)
    assert data["schema"] == "howlwriter.materials/v1"
    assert data["counts"]["total"] == len(data["records"])


def test_size_limit_marks_file_instead_of_dropping_it(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "MAX_MATERIAL_BYTES", 100)
    (tmp_path / "big.txt").write_text("a" * 500)
    rec = _by_path(scan_materials(tmp_path))["big.txt"]
    assert rec.extraction_status == ExtractionStatus.SKIPPED_TOO_LARGE
    assert not rec.text_extracted and not rec.may_be_evidence


def test_truncation_downgrades_depth_to_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "MAX_TEXT_CHARS", 100)
    (tmp_path / "long.txt").write_text(ZT * 5)
    scan = scan_materials(tmp_path)
    rec = _by_path(scan)["long.txt"]
    assert rec.truncated and rec.evidence_depth == "PARTIAL_TEXT"
    assert len(scan.texts[rec.material_id]) == 100


def test_scanned_pdf_is_not_evidence(tmp_path):
    pytest.importorskip("pypdf")
    make_pdf(tmp_path / "scan.pdf", "tiny")
    rec = _by_path(scan_materials(tmp_path))["scan.pdf"]
    assert rec.extraction_status == ExtractionStatus.SCANNED_NO_TEXT
    assert not rec.may_be_evidence


def test_zip_bomb_guard_refuses_oversized_docx(tmp_path, monkeypatch):
    import zipfile

    monkeypatch.setattr(scan_mod, "MAX_ZIP_UNCOMPRESSED_BYTES", 1000)
    with zipfile.ZipFile(tmp_path / "bomb.docx", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "<a/>" + " " * 100_000)
    rec = _by_path(scan_materials(tmp_path))["bomb.docx"]
    assert rec.extraction_status == ExtractionStatus.FAILED
    assert not rec.may_be_evidence


def test_hidden_directories_are_reported_not_scanned(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x" * 100)
    (tmp_path / "ok.txt").write_text("hello world " * 10)
    scan = scan_materials(tmp_path)
    assert set(_by_path(scan)) == {"ok.txt"}
    assert any(".git" in w for w in scan.ledger.warnings)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_materials(tmp_path / "nope")
