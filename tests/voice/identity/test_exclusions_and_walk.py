"""Mandatory directory exclusions, symlinks, and root containment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from howlwriter.voice.identity import scanner as scanner_module
from howlwriter.voice.identity.exclusions import (
    WILLIAM_REQUIRED_EXCLUSIONS,
    ExclusionPolicy,
    normalize_component,
)
from howlwriter.voice.identity.scanner import walk

POLICY = ExclusionPolicy(required=WILLIAM_REQUIRED_EXCLUSIONS)


@pytest.mark.parametrize(
    "name",
    [
        "Gemini Gems",
        "gemini gems",
        "GEMINI GEMS",
        "gemini_gems",
        "Gemini-Gems",
        "GeminiGems",
        "  Gemini   Gems ",
        "ＧＥＭＩＮＩ ＧＥＭＳ",
        "RetroArchSaves",
        "retroarchsaves",
        "Retro_Arch_Saves",
        "Shared Drives",
        "shared_drives",
        "SHARED-DRIVES",
    ],
)
def test_required_names_match_case_and_separator_insensitively(name):
    assert POLICY.excludes(name)


@pytest.mark.parametrize(
    "name",
    [
        "My Gemini Gems Notes",
        "gemini gems backup",
        "gems",
        "Gemini",
        "Shared with Me",
        "shared drive",
        "retroarch",
        "RetroArchSaves.docx2",
    ],
)
def test_component_matching_is_exact_not_substring(name):
    assert not POLICY.excludes(name)


def test_normalization_is_modest():
    assert normalize_component("Gemini__Gems") == "gemini gems"
    assert normalize_component("") == ""


def test_path_is_excluded_checks_directories_not_the_file_name():
    assert POLICY.path_is_excluded(["a", "Gemini Gems", "x.md"])
    assert not POLICY.path_is_excluded(["a", "b", "Gemini Gems"])  # a file named like it


def _tree(root: Path) -> None:
    for relative in [
        "keep/a.md",
        "keep/deep/er/still/b.md",
        "Gemini Gems/top.md",
        "x/y/GEMINI_GEMS/z/deep.md",
        "x/RetroArchSaves/save.md",
        "x/y/z/Shared-Drives/team.md",
        "x/node_modules/pkg/readme.md",
        "keep/Gemini Gems.md",
    ]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content " * 50, encoding="utf-8")


def test_walk_skips_excluded_directories_at_every_depth(tmp_path):
    _tree(tmp_path)
    result = walk(tmp_path, POLICY)
    paths = {f.relative_path for f in result.files}
    assert paths == {"keep/a.md", "keep/deep/er/still/b.md", "keep/Gemini Gems.md"}
    assert result.excluded_directories == 4
    assert result.noise_directories == 1


def test_excluded_directories_are_never_listed(tmp_path, monkeypatch):
    _tree(tmp_path)
    listed: list[str] = []
    real_scandir = os.scandir

    def recording_scandir(path):
        listed.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(scanner_module.os, "scandir", recording_scandir)
    walk(tmp_path, POLICY)
    lowered = [p.lower() for p in listed]
    for forbidden in ("gemini gems", "gemini_gems", "retroarchsaves", "shared-drives"):
        assert not any(forbidden in p for p in lowered), forbidden


def test_symlinks_are_never_followed_into_excluded_or_outside(tmp_path):
    root = tmp_path / "root"
    (root / "Gemini Gems").mkdir(parents=True)
    (root / "Gemini Gems" / "secret.md").write_text("x " * 300, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "elsewhere.md").write_text("y " * 300, encoding="utf-8")
    (root / "ok.md").write_text("z " * 300, encoding="utf-8")
    os.symlink(root / "Gemini Gems", root / "innocent_name")
    os.symlink(outside, root / "escape")
    os.symlink(outside / "elsewhere.md", root / "file_link.md")

    result = walk(root, POLICY)
    assert {f.relative_path for f in result.files} == {"ok.md"}
    assert result.symlinks_skipped == 3


def test_walk_survives_unlistable_directories(tmp_path):
    (tmp_path / "locked").mkdir()
    (tmp_path / "locked" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "open.md").write_text("x", encoding="utf-8")
    os.chmod(tmp_path / "locked", 0)
    try:
        if os.access(tmp_path / "locked", os.R_OK):
            pytest.skip("running with privileges that ignore directory permissions")
        result = walk(tmp_path, POLICY)
        assert {f.relative_path for f in result.files} == {"open.md"}
        assert result.unlistable_directories == 1
    finally:
        os.chmod(tmp_path / "locked", 0o700)


def test_policy_round_trips():
    policy = ExclusionPolicy(required=("a",), additional=("b",), prune_noise=False)
    again = ExclusionPolicy.from_dict(policy.to_dict())
    assert again.excludes("A") and again.excludes("B") and not again.is_noise(".git")
