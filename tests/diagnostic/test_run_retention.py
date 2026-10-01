import os
from datetime import datetime, timezone

import pytest

from howlwriter.cli.main import main
from howlwriter.diagnostic.retention import execute_prune, plan_prune

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _runs(tmp_path, ids):
    d = tmp_path / "runs"
    d.mkdir(exist_ok=True)
    for rid in ids:
        (d / f"{rid}.json").write_text("{}")
        (d / f"{rid}.provenance.json").write_text("{}")
    return d


IDS = [
    "hw-20260101-000000-aaaaaa",  # old
    "hw-20260601-000000-bbbbbb",  # ~4 months
    "hw-20260920-000000-cccccc",  # recent
    "hw-20260930-000000-dddddd",  # recent
]


def test_requires_a_criterion(tmp_path):
    with pytest.raises(ValueError):
        plan_prune(_runs(tmp_path, IDS))


def test_older_than_selects_old_runs_with_sidecars_deterministically(tmp_path):
    d = _runs(tmp_path, IDS)
    plan = plan_prune(d, older_than_days=90, now=NOW)
    assert [c.run_id for c in plan.candidates] == IDS[:2]
    assert sorted(plan.candidates[0].files) == sorted([f"{IDS[0]}.json", f"{IDS[0]}.provenance.json"])
    assert plan.total_runs == 4 and plan.kept_runs == 2
    assert plan == plan_prune(d, older_than_days=90, now=NOW)


def test_keep_latest(tmp_path):
    plan = plan_prune(_runs(tmp_path, IDS), keep_latest=1, now=NOW)
    assert [c.run_id for c in plan.candidates] == IDS[:3]


def test_both_criteria_must_hold(tmp_path):
    plan = plan_prune(_runs(tmp_path, IDS), older_than_days=90, keep_latest=3, now=NOW)
    assert [c.run_id for c in plan.candidates] == [IDS[0]]


def test_unrelated_files_and_symlinks_are_never_touched(tmp_path):
    d = _runs(tmp_path, IDS[:1])
    (d / "notes.json").write_text("{}")
    (d / "hw-bad.json").write_text("{}")
    (d / "subdir").mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("keep")
    os.symlink(victim, d / "hw-20260101-000000-eeeeee.json")
    plan = plan_prune(d, older_than_days=1, now=NOW)
    assert "hw-20260101-000000-eeeeee.json" in plan.skipped
    removed = execute_prune(plan)
    assert victim.read_text() == "keep"
    assert (d / "notes.json").exists() and (d / "hw-bad.json").exists() and (d / "subdir").exists()
    assert sorted(removed) == sorted(plan.candidates[0].files)


def test_execute_revalidates_paths(tmp_path):
    d = _runs(tmp_path, IDS[:1])
    plan = plan_prune(d, older_than_days=1, now=NOW)
    plan.candidates[0].files.append("../victim.json")
    (tmp_path / "victim.json").write_text("keep")
    execute_prune(plan)
    assert (tmp_path / "victim.json").exists()


def test_cli_dry_run_default_then_yes(tmp_path, monkeypatch, capsys):
    d = _runs(tmp_path, IDS[:1])
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(d))
    assert main(["runs", "prune", "--older-than-days", "30"]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert (d / f"{IDS[0]}.json").exists()
    assert main(["runs", "prune", "--older-than-days", "30", "--dry-run"]) == 0
    assert (d / f"{IDS[0]}.json").exists()
    assert main(["runs", "prune", "--older-than-days", "30", "--yes"]) == 0
    assert not (d / f"{IDS[0]}.json").exists()
    assert not (d / f"{IDS[0]}.provenance.json").exists()


def test_cli_rejects_missing_criterion_and_conflicts(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(_runs(tmp_path, IDS)))
    assert main(["runs", "prune"]) == 2
    assert main(["runs", "prune", "--keep-latest", "1", "--dry-run", "--yes"]) == 2
    assert main(["runs", "prune", "--keep-latest", "-1"]) == 2
