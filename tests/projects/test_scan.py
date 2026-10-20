"""Inventory, classification, isolation, incremental rescans, interruption and recovery."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from howlwriter.projects import models as m
from howlwriter.projects.scan import Extractors, scan_project, set_category
from howlwriter.projects.workspace import ProjectWorkspace

from tests.projects.conftest import FakeOcr, Off, line
from tests.projects.fixtures import make_pcap, make_png


def _extractors(**kwargs) -> Extractors:
    kwargs.setdefault("ocr", FakeOcr())
    kwargs.setdefault("transcriber", Off())
    return Extractors(**kwargs)


def _scan(workspace, **kwargs):
    extractors = kwargs.pop("extractors", None) or _extractors()
    try:
        return scan_project(workspace, extractors=extractors, **kwargs)
    finally:
        extractors.close()


def test_inventory_and_classification(lab_folder):
    pytest.importorskip("pypdf")
    workspace = ProjectWorkspace.create(lab_folder)
    report = _scan(workspace)
    sources = {s.path: s for s in workspace.load_sources().values()}
    assert sources["materials/Lab 03 instructions.pdf"].category == m.INSTRUCTIONS
    assert sources["materials/tls-reference.docx"].category == m.REFERENCE
    assert sources["evidence/suricata-eve.log"].category == m.EXPERIMENTAL
    assert sources["draft notes.md"].category == m.USER_DRAFT
    assert report.files == 4 and report.failed == 0
    assert all(s.status == "extracted" for s in sources.values())


def test_workspace_is_private_and_outside_the_folder(lab_folder, private_dirs):
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    assert private_dirs in workspace.directory.parents
    assert stat.S_IMODE(workspace.directory.stat().st_mode) == 0o700
    for name in ("project.json", "sources.json", "evidence.json", "requirements.json"):
        assert stat.S_IMODE((workspace.directory / name).stat().st_mode) == 0o600
    assert not any(p.name.endswith(".json") for p in lab_folder.rglob("*"))


def test_workspace_refused_inside_a_git_worktree(tmp_path, monkeypatch, lab_folder):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("HOWLWRITER_PROJECTS_DIR", str(repo / "projects"))
    with pytest.raises(Exception, match="Git worktree"):
        ProjectWorkspace.create(lab_folder)


def test_source_files_are_never_modified(lab_folder):
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in lab_folder.rglob("*") if p.is_file()}
    _scan(ProjectWorkspace.create(lab_folder))
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in lab_folder.rglob("*") if p.is_file()}
    assert before == after


def test_symlinks_hidden_files_and_excluded_directories_are_not_entered(tmp_path, lab_folder, monkeypatch):
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("must never be read", encoding="utf-8")
    (lab_folder / "link-to-secret.txt").symlink_to(outside)
    (lab_folder / "link-dir").symlink_to(tmp_path, target_is_directory=True)
    (lab_folder / ".hidden.txt").write_text("hidden", encoding="utf-8")
    barred = lab_folder / "Shared Drives" / "deep"
    barred.mkdir(parents=True)
    (barred / "never.txt").write_text("never", encoding="utf-8")
    workspace = ProjectWorkspace.create(lab_folder)
    meta = workspace.load_meta()
    meta["exclusions"] = ["shared drives"]
    workspace.save_meta(meta)
    report = _scan(workspace)
    paths = {s.path for s in workspace.load_sources().values()}
    assert not any("secret" in p or "never" in p or "hidden" in p for p in paths)
    assert report.skipped["symlink"] == 2
    assert report.skipped["excluded_directory"] == 1
    evidence_text = " ".join(e.excerpt for e in workspace.load_evidence().values())
    assert "must never be read" not in evidence_text


def test_project_inherits_identity_exclusions(lab_folder, private_dirs):
    from howlwriter.voice.identity.exclusions import ExclusionPolicy
    from howlwriter.voice.identity.store import IdentityConfig, IdentityStore

    store = IdentityStore("tester")
    config = IdentityConfig.default("tester")
    config.exclusions = ExclusionPolicy(required=("gemini gems",))
    store.save_config(config)
    workspace = ProjectWorkspace.create(lab_folder)
    assert "gemini gems" in workspace.load_meta()["exclusions"]


def test_malformed_files_fail_alone(lab_folder):
    (lab_folder / "materials" / "broken.pdf").write_bytes(b"%PDF-1.4 this is not a pdf")
    (lab_folder / "evidence" / "corrupt.pcap").write_bytes(b"\x00\x01garbage" * 10)
    (lab_folder / "materials" / "broken.docx").write_bytes(b"PK\x03\x04 not a zip")
    workspace = ProjectWorkspace.create(lab_folder)
    report = _scan(workspace)
    sources = {s.path: s for s in workspace.load_sources().values()}
    assert sources["materials/broken.pdf"].status == "failed"
    assert sources["evidence/corrupt.pcap"].status == "failed"
    assert sources["materials/broken.docx"].status == "failed"
    assert sources["materials/tls-reference.docx"].status == "extracted"
    assert report.failed == 3
    assert not [e for e in workspace.load_evidence().values() if e.source_path.startswith("materials/broken")]


def test_size_limit_skips_without_reading(lab_folder, monkeypatch):
    from howlwriter.projects import scan as scan_module

    monkeypatch.setitem(scan_module.SIZE_LIMITS, "data", 10)
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    record = next(s for s in workspace.load_sources().values() if s.path.endswith(".log"))
    assert record.status == "skipped" and "limit" in record.status_reason and record.evidence_count == 0


def test_duplicates_are_extracted_once(lab_folder):
    (lab_folder / "copy").mkdir()
    (lab_folder / "copy" / "same.docx").write_bytes(
        (lab_folder / "materials" / "tls-reference.docx").read_bytes()
    )
    workspace = ProjectWorkspace.create(lab_folder)
    report = _scan(workspace)
    assert report.duplicates == 1
    pair = {s.path: s for s in workspace.load_sources().values() if s.path.endswith(".docx")}
    duplicates = [s for s in pair.values() if s.status == "duplicate"]
    assert len(duplicates) == 1
    original = next(p for p in pair if p != duplicates[0].path)
    assert original in duplicates[0].status_reason and pair[original].status == "extracted"
    assert not [e for e in workspace.load_evidence().values() if e.source_path == duplicates[0].path]


class CountingExtractors(Extractors):
    def __init__(self, **kwargs) -> None:
        super().__init__(ocr=FakeOcr(), transcriber=Off(), **kwargs)
        self.reads: list[str] = []

    def run(self, workspace, path, relative, suffix, sha):
        self.reads.append(relative)
        return super().run(workspace, path, relative, suffix, sha)


def test_incremental_rescan_reads_only_changed_files(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)
    first = CountingExtractors()
    _scan(workspace, extractors=first)
    assert len(first.reads) == 4
    evidence_before = set(workspace.load_evidence())
    second = CountingExtractors()
    report = _scan(workspace, extractors=second)
    assert second.reads == [] and report.unchanged == 4
    assert set(workspace.load_evidence()) == evidence_before

    notes = lab_folder / "draft notes.md"
    notes.write_text("# My notes\n\nNow with the TLS 1.3 comparison first.\n", encoding="utf-8")
    os.utime(notes, (notes.stat().st_atime, notes.stat().st_mtime + 5))
    (lab_folder / "evidence" / "suricata-eve.log").unlink()
    third = CountingExtractors()
    report = _scan(workspace, extractors=third)
    assert third.reads == ["draft notes.md"]
    assert report.removed == 1
    assert not [e for e in workspace.load_evidence().values() if e.source_path.endswith(".log")]


def test_user_category_survives_rescans(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    set_category(workspace, "draft notes.md", m.REFERENCE)
    _scan(workspace, force=True)
    record = next(s for s in workspace.load_sources().values() if s.path == "draft notes.md")
    assert record.category == m.REFERENCE and record.category_source == "user"
    assert all(
        e.category == m.REFERENCE
        for e in workspace.load_evidence().values()
        if e.source_path == "draft notes.md"
    )
    with pytest.raises(ValueError):
        set_category(workspace, "draft notes.md", "not-a-category")
    with pytest.raises(ValueError, match="category source"):
        set_category(workspace, "draft notes.md", m.REFERENCE, by="someone")


@pytest.mark.parametrize("by", m.MANUAL_CATEGORY_SOURCES)
def test_every_manual_category_survives_rescans_with_its_actor(lab_folder, by):
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    set_category(workspace, "draft notes.md", m.REFERENCE, by=by)
    _scan(workspace, force=True)
    record = next(s for s in workspace.load_sources().values() if s.path == "draft notes.md")
    assert (record.category, record.category_source) == (m.REFERENCE, by)
    assert record.category_reason == m.CATEGORY_REASONS[by]


def test_data_lines_are_directly_observed_only_in_experimental_evidence(lab_folder):
    # A table someone wrote (a scoring sheet, a reference's figures) states things; it does not
    # become a direct observation because it was parsed. The same lines in the user's own
    # experimental log are what they measured.
    (lab_folder / "materials" / "ratings.csv").write_text("device,rating\nrouter,high\n", encoding="utf-8")
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)

    def statuses(path):
        return {e.status for e in workspace.load_evidence().values() if e.source_path == path}

    log = "evidence/suricata-eve.log"
    set_category(workspace, log, m.EXPERIMENTAL)
    assert statuses(log) == {m.DIRECTLY_OBSERVED}
    set_category(workspace, "materials/ratings.csv", m.REFERENCE)
    assert statuses("materials/ratings.csv") == {m.EXTRACTED}

    set_category(workspace, log, m.USER_DRAFT)
    assert statuses(log) == {m.EXTRACTED}
    _scan(workspace, force=True)
    assert statuses(log) == {m.EXTRACTED} and statuses("materials/ratings.csv") == {m.EXTRACTED}
    set_category(workspace, log, m.EXPERIMENTAL)
    assert statuses(log) == {m.DIRECTLY_OBSERVED}


def test_interrupted_scan_resumes_without_redoing_completed_files(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)
    first = CountingExtractors()
    calls = {"n": 0}

    def stop_after_two() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    report = _scan(workspace, extractors=first, should_stop=stop_after_two)
    assert report.interrupted and len(first.reads) == 2
    assert workspace.load_meta()["scan_state"]["status"] == "interrupted"
    saved = {s.path for s in workspace.load_sources().values()}
    assert saved == set(first.reads)
    # A new session (new objects) resumes from the checkpoint.
    resumed = CountingExtractors()
    report = _scan(ProjectWorkspace(workspace.project_id), extractors=resumed)
    assert not report.interrupted
    assert sorted(resumed.reads) == sorted(
        {
            "materials/Lab 03 instructions.pdf",
            "materials/tls-reference.docx",
            "evidence/suricata-eve.log",
            "draft notes.md",
        }
        - set(first.reads)
    )


def test_screenshots_and_captures_are_categorised(lab_folder):
    pytest.importorskip("dpkt")
    make_png(lab_folder / "evidence" / "alerts.png")
    make_png(lab_folder / "materials" / "scoring matrix.png")
    make_pcap(lab_folder / "evidence" / "tls13.pcap")
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    sources = {s.path: s for s in workspace.load_sources().values()}
    assert sources["evidence/alerts.png"].category == m.SCREENSHOT
    assert sources["materials/scoring matrix.png"].category == m.RUBRIC
    assert sources["evidence/tls13.pcap"].category == m.PACKET_CAPTURE


def test_resolve_source_refuses_paths_outside_the_root(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)
    with pytest.raises(ValueError):
        workspace.resolve_source("../../etc/passwd")
    assert (
        workspace.resolve_source("materials/tls-reference.docx")
        == (lab_folder / "materials" / "tls-reference.docx").resolve()
    )


def test_invalid_project_ids_are_refused():
    for bad in ("../x", "", "A B", "x" * 80):
        with pytest.raises(ValueError):
            ProjectWorkspace(bad)


def test_project_root_must_be_a_directory(tmp_path):
    with pytest.raises(ValueError):
        ProjectWorkspace.create(tmp_path / "missing")
    path = tmp_path / "file.txt"
    path.write_text("x")
    with pytest.raises(ValueError):
        ProjectWorkspace.create(path)


def test_scan_reports_unavailable_root(lab_folder, tmp_path):
    workspace = ProjectWorkspace.create(lab_folder)
    meta = workspace.load_meta()
    meta["root"] = str(tmp_path / "gone")
    workspace.save_meta(meta)
    with pytest.raises(FileNotFoundError):
        _scan(workspace)


def test_unsupported_files_are_inventoried_not_read(lab_folder):
    (lab_folder / "materials" / "tool.exe").write_bytes(b"MZ" + bytes(100))
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    record = next(s for s in workspace.load_sources().values() if s.path.endswith("tool.exe"))
    assert record.category == m.UNKNOWN and record.status == "skipped" and record.evidence_count == 0


def test_project_list(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)
    assert ProjectWorkspace.list_projects() == [workspace.project_id]
    assert Path(workspace.load_meta()["root"]) == lab_folder.resolve()


def test_browser_profiles_and_caches_are_never_entered(lab_folder):
    profile = lab_folder / "work" / "browser-profile"
    (profile / "Default" / "Code Cache").mkdir(parents=True)
    (profile / "Local State").write_text("{}", encoding="utf-8")
    (profile / "Default" / "Cookies").write_bytes(b"SQLite format 3\x00 session=abc")
    (profile / "Default" / "notes.txt").write_text("inside a profile", encoding="utf-8")
    (lab_folder / "work" / "Cache").mkdir()
    (lab_folder / "work" / "Cache" / "data_1").write_bytes(b"cached")
    workspace = ProjectWorkspace.create(lab_folder)
    report = _scan(workspace)
    assert not [s for s in workspace.load_sources().values() if s.path.startswith("work/")]
    assert report.skipped["browser_profile_or_cache"] == 2


def test_enabling_an_extraction_step_reprocesses_only_affected_files(lab_folder):
    make_png(lab_folder / "evidence" / "alerts.png")
    workspace = ProjectWorkspace.create(lab_folder)
    without_ocr = CountingExtractors()
    without_ocr._ocr = Off()
    _scan(workspace, extractors=without_ocr)
    assert next(s for s in workspace.load_sources().values() if s.path.endswith(".png")).status == "partial"
    with_ocr = CountingExtractors()
    report = _scan(workspace, extractors=with_ocr)
    assert with_ocr.reads == ["evidence/alerts.png"] and report.unchanged == 4


def test_only_reextracts_the_named_file(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    again = CountingExtractors()
    report = _scan(workspace, extractors=again, force=True, only={"draft notes.md"})
    assert again.reads == ["draft notes.md"] and report.removed == 0
    assert len([s for s in workspace.load_sources().values() if s.present]) == 4


def test_rules_scripts_subtitles_and_secrets(lab_folder):
    (lab_folder / "evidence" / "local.rules").write_text(
        'alert tls any any -> any any (msg:"SNI lab"; tls.sni; content:"lab.example.test"; sid:1000001;)\n',
        encoding="utf-8",
    )
    (lab_folder / "materials" / "genca.sh").write_text(
        "#!/bin/sh\nopenssl req -x509 -new\n", encoding="utf-8"
    )
    (lab_folder / "materials" / "overview.srt").write_text(
        "1\n00:00:03,200 --> 00:00:07,900\nStart the capture on the sensor.\n\n"
        "2\n00:01:03,000 --> 00:01:04,500\nTwo alerts fire.\n",
        encoding="utf-8",
    )
    (lab_folder / "evidence" / "server.pem").write_text(
        "-----BEGIN PRIVATE KEY-----\nAAAA\n", encoding="utf-8"
    )
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    sources = {s.path: s for s in workspace.load_sources().values()}
    # A rule file is the student's work product, not an observation that anything ran.
    assert sources["evidence/local.rules"].category == m.OUTPUT_DOCUMENT
    assert sources["materials/genca.sh"].category == m.REFERENCE
    srt = [e for e in workspace.load_evidence().values() if e.source_path == "materials/overview.srt"]
    assert [e.location for e in srt] == ["00:03–00:07", "01:03–01:04"]
    pem = sources["evidence/server.pem"]
    assert pem.status == "skipped" and "never read" in pem.status_reason and pem.sha256 == ""
    assert "PRIVATE KEY" not in (workspace.directory / "evidence.json").read_text()


def test_files_skipped_for_lack_of_an_adapter_are_retried(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    sources = workspace.load_sources()
    record = next(s for s in sources.values() if s.path.endswith(".log"))
    record.status, record.status_reason, record.evidence_count = "skipped", "no adapter for .log", 0
    workspace.save_sources(sources)
    again = CountingExtractors()
    _scan(workspace, extractors=again)
    assert again.reads == ["evidence/suricata-eve.log"]


def test_keyboard_interrupt_is_recorded_and_resumable(lab_folder):
    workspace = ProjectWorkspace.create(lab_folder)

    class Interrupting(CountingExtractors):
        def run(self, *args):
            if len(self.reads) == 2:
                raise KeyboardInterrupt
            return super().run(*args)

    with pytest.raises(KeyboardInterrupt):
        _scan(workspace, extractors=Interrupting())
    assert workspace.load_meta()["scan_state"]["status"] == "interrupted"
    resumed = CountingExtractors()
    _scan(workspace, extractors=resumed)
    assert len(resumed.reads) == 2 and workspace.load_meta()["scan_state"]["status"] == "complete"


def test_unchanged_duplicates_are_not_reread_but_promoted_when_the_original_goes(lab_folder):
    (lab_folder / "copy").mkdir()
    original = (lab_folder / "materials" / "tls-reference.docx").read_bytes()
    (lab_folder / "copy" / "same.docx").write_bytes(original)
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    again = CountingExtractors()
    report = _scan(workspace, extractors=again)
    assert report.new_or_changed == 0 and report.unchanged == 5
    (lab_folder / "copy" / "same.docx").unlink()  # the extracted copy (sorted first) is deleted
    third = CountingExtractors()
    _scan(workspace, extractors=third)
    assert third.reads == ["materials/tls-reference.docx"]
    survivor = next(s for s in workspace.load_sources().values() if s.path.endswith("tls-reference.docx"))
    assert survivor.status == "extracted"


def test_rendered_pages_and_video_frames_are_not_observations(lab_folder):
    for folder in ("output/rendered_pdf", "work/video_frames", "evidence"):
        (lab_folder / folder).mkdir(parents=True, exist_ok=True)
    make_png(lab_folder / "output" / "rendered_pdf" / "page_03.png")
    make_png(lab_folder / "work" / "video_frames" / "overview-0170.png", 65, 33)
    make_png(lab_folder / "evidence" / "report-shot.png", 66, 34)
    make_png(lab_folder / "evidence" / "alerts.png", 67, 35)
    ocr = FakeOcr({"report-shot.png": [line("Lab 3 report | Page 4 of 13")],
                   "alerts.png": [line("alert sid 1000001")]})
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace, extractors=_extractors(ocr=ocr))
    sources = {s.path: s for s in workspace.load_sources().values()}
    assert sources["output/rendered_pdf/page_03.png"].category == m.OUTPUT_DOCUMENT
    assert sources["work/video_frames/overview-0170.png"].category == m.MULTIMEDIA
    assert sources["evidence/report-shot.png"].category == m.OUTPUT_DOCUMENT
    assert sources["evidence/alerts.png"].category == m.SCREENSHOT


def test_new_classification_rules_apply_without_reextraction(lab_folder):
    make_png(lab_folder / "evidence" / "report-shot.png")
    ocr = FakeOcr({"report-shot.png": [line("Report | Page 2 of 9")]})
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace, extractors=_extractors(ocr=ocr))
    sources = workspace.load_sources()
    record = next(s for s in sources.values() if s.path.endswith("report-shot.png"))
    record.category, record.metadata["classifier"] = m.SCREENSHOT, 1  # as an older version left it
    workspace.save_sources(sources)
    again = CountingExtractors()
    again._ocr = ocr
    _scan(workspace, extractors=again)
    assert again.reads == []
    record = next(s for s in workspace.load_sources().values() if s.path.endswith("report-shot.png"))
    assert record.category == m.OUTPUT_DOCUMENT


def test_frame_dumps_page_renders_tooling_and_working_files_are_not_observations(lab_folder):
    (lab_folder / "output" / "audit").mkdir(parents=True)
    make_png(lab_folder / "output" / "audit" / "overview-0001.png", 61, 31)
    make_png(lab_folder / "output" / "audit" / "google-page08.png", 62, 32)
    (lab_folder / "output" / "audit" / "build_sections.py").write_text("print('x')\n", encoding="utf-8")
    (lab_folder / "output" / "audit" / "verified.json").write_text('{"ok": true}\n', encoding="utf-8")
    (lab_folder / "evidence" / "server-02.log").write_text("TLS handshake complete\n", encoding="utf-8")
    workspace = ProjectWorkspace.create(lab_folder)
    _scan(workspace)
    sources = {s.path: s for s in workspace.load_sources().values()}
    assert sources["output/audit/overview-0001.png"].category == m.MULTIMEDIA
    assert sources["output/audit/google-page08.png"].category == m.OUTPUT_DOCUMENT
    assert sources["output/audit/build_sections.py"].category == m.OUTPUT_DOCUMENT
    assert sources["output/audit/verified.json"].category == m.OUTPUT_DOCUMENT
    assert sources["evidence/server-02.log"].category == m.EXPERIMENTAL
