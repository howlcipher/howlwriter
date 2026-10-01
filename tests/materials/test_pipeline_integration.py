import json

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.cli.main import main
from howlwriter.domain.source import (
    ORIGIN_ASSIGNMENT_MATERIALS,
    ORIGIN_USER_SUPPLIED,
    Source,
)
from tests.materials.builders import build_package


def _offline(monkeypatch):
    """No live network: every external lookup fails fast."""
    import urllib.error
    import urllib.request

    def boom(*a, **k):
        raise urllib.error.URLError("simulated offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)


def test_pipeline_uses_materials_for_requirements_and_evidence(tmp_path, monkeypatch):
    _offline(monkeypatch)
    pkg = build_package(tmp_path / "pkg")
    result = run_academic_pipeline(
        pkg / "assignment.yaml", deterministic_only=True, cwd=pkg,
        output_dir=tmp_path / "out", materials_exclude=[pkg / "assignment.yaml"],
    )
    reqs = result.spec.requirements
    assert "Discuss identity and device posture" in reqs
    assert any("cites" in r.lower() or "cite" in r.lower() for r in reqs)
    origins = {s.origin for s in result.sources}
    assert origins == {ORIGIN_ASSIGNMENT_MATERIALS}
    assert result.report.source_origin_counts[ORIGIN_ASSIGNMENT_MATERIALS] >= 2
    assert result.report.researcher_provider == "local_sources"
    ledger = result.materials_ledger
    assert ledger is not None
    names = {r.name for r in ledger.records}
    assert "lab-artifact.pcap" in names
    # instructions/rubric text never becomes a source
    source_material_ids = {s.material_id for s in result.sources}
    for r in ledger.records:
        if r.role.value in ("INSTRUCTIONS", "RUBRIC", "AUXILIARY"):
            assert r.material_id not in source_material_ids
    assert result.report.materials_summary["by_status"].get("REQUIRES_EXTERNAL_INSPECTION") == 1
    assert "Assignment Materials:" in result.report.render_text()


def test_precedence_local_materials_before_user_sources(tmp_path, monkeypatch):
    _offline(monkeypatch)
    pkg = build_package(tmp_path / "pkg", with_pdf=False)
    manual = Source(id="X", title="Manual Zero Trust Source", authors=["A"],
                    retrieved_text="zero trust architecture microsegmentation identity " * 5)
    result = run_academic_pipeline(
        pkg / "assignment.yaml", deterministic_only=True, cwd=pkg, existing_sources=[manual],
        output_dir=tmp_path / "out", materials_exclude=[pkg / "assignment.yaml"],
    )
    origins = [s.origin for s in result.sources]
    assert origins[:2] == [ORIGIN_ASSIGNMENT_MATERIALS] * 2
    assert origins[-1] == ORIGIN_USER_SUPPLIED or ORIGIN_USER_SUPPLIED in origins


def test_no_materials_dir_leaves_behaviour_unchanged(tmp_path, monkeypatch):
    _offline(monkeypatch)
    spec = {"title": "T", "topic": "zero trust architecture", "target_words": 600}
    result = run_academic_pipeline(spec, deterministic_only=True, output_dir=tmp_path / "out")
    assert result.materials_ledger is None
    assert result.report.materials_summary is None


def test_offline_research_failure_is_visible_in_report(tmp_path, monkeypatch):
    _offline(monkeypatch)
    spec = {"title": "T", "topic": "zero trust architecture", "target_words": 600}
    result = run_academic_pipeline(spec, deterministic_only=True, output_dir=tmp_path / "out")
    rd = result.report.research_diagnostics
    assert rd and rd["providers"]["crossref"]["failed"] >= 1
    assert rd["failures"][0]["category"] == "network"
    assert "FAILED" in result.report.render_text()
    assert result.report.researcher_provider == "none"


def test_cli_materials_dir_writes_ledger(tmp_path, monkeypatch, capsys):
    _offline(monkeypatch)
    pkg = build_package(tmp_path / "pkg", with_pdf=False)
    out = tmp_path / "out"
    rc = main(["paper", str(pkg / "assignment.yaml"), "--materials-dir", str(pkg),
               "--deterministic", "--output-dir", str(out), "--save-artifacts"])
    assert rc == 0
    ledger_path = out / "zero-trust-architecture.materials.json"
    data = json.loads(ledger_path.read_text())
    assert str(tmp_path) not in ledger_path.read_text()
    assert data["counts"]["total"] == 5  # assignment.yaml excluded
    assert "Assignment Materials:" in capsys.readouterr().out
    # existing ledger is not silently clobbered without --overwrite
    ledger_path.write_text("sentinel")
    main(["paper", str(pkg / "assignment.yaml"), "--materials-dir", str(pkg), "--deterministic",
          "--output-dir", str(out), "--save-artifacts", "--overwrite"])
    assert ledger_path.read_text() != "sentinel"
