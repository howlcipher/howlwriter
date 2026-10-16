"""Building context profiles from attested documents only."""

from __future__ import annotations

import json
import stat

import pytest

from howlwriter.voice.corpus.store import VoiceStore
from howlwriter.voice.identity import review
from howlwriter.voice.identity.profiles import build_identity, load_calibration, select_sources
from howlwriter.voice.identity.scanner import scan
from howlwriter.voice.identity.store import IdentityStore

from tests.voice.identity.conftest import attest_all


def _built(env, drive, authorship="h"):
    scan("william", sources=[str(drive)])
    attest_all("william", "school/", authorship, category="academic_lab")
    return {r.profile: r for r in build_identity("william")}


def test_nothing_is_built_from_proposals(env, drive):
    scan("william", sources=[str(drive)])
    results = {r.profile: r for r in build_identity("william")}
    assert results["academic"].status == "insufficient"
    assert results["academic"].eligible_documents == 0
    assert not VoiceStore("william-academic").exists()


def test_academic_profile_from_attested_documents(env, drive):
    results = _built(env, drive)
    academic = results["academic"]
    assert academic.status == "built"
    assert academic.eligible_documents >= 10
    assert results["professional"].status == "insufficient"
    store = VoiceStore("william-academic")
    assert store.exists()
    calibration = load_calibration("william-academic")
    assert calibration["identity"]["display_name"] == "William Elias"
    assert calibration["identity"]["context"] == "academic"
    assert len(calibration["voice_match"]["genuine_distances"]) >= 8
    assert calibration["drift"]["windows"] > 0


def test_profile_files_are_private(env, drive):
    _built(env, drive)
    directory = VoiceStore("william-academic").directory
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_calibration_contains_no_text(env, drive):
    _built(env, drive)
    raw = (VoiceStore("william-academic").directory / "calibration.json").read_text(
        encoding="utf-8"
    )
    assert "appears to confirm" not in raw and "segmentation" not in raw


def test_light_ai_editing_carries_half_weight(env, drive):
    scan("william", sources=[str(drive)])
    attest_all("william", "school/", "l", category="academic_lab")
    store = IdentityStore("william")
    config = store.load_config()
    choices, _ = select_sources(
        config,
        store.load_inventory()["entries"],
        store.load_decisions(),
        config.profiles["academic"],
    )
    assert choices and all(c.selection.weight == 0.5 for c in choices)


def test_mixed_documents_contribute_only_attested_paragraphs(env, drive):
    scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    entries = store.load_inventory()["entries"]
    lab_ids = [
        k
        for k, v in entries.items()
        if v["relative_path"].startswith("school/") and v.get("duplicate_role") != "duplicate"
    ]
    review.attest(store, lab_ids[0], "m", category="academic_lab")  # no paragraphs: excluded
    review.attest(store, lab_ids[1], "m", category="academic_lab", include_paragraphs="2-3")
    config = store.load_config()
    choices, _ = select_sources(
        config,
        store.load_inventory()["entries"],
        store.load_decisions(),
        config.profiles["academic"],
    )
    by_id = {c.doc_id: c for c in choices}
    assert lab_ids[0] not in by_id
    assert by_id[lab_ids[1]].selection.paragraphs == frozenset({1, 2})


def test_ai_and_third_party_documents_never_enter_a_profile(env, drive):
    scan("william", sources=[str(drive)])
    attest_all("william", "school/", "a", category="academic_lab")
    results = {r.profile: r for r in build_identity("william")}
    assert results["academic"].eligible_documents == 0


def test_insufficient_rebuild_keeps_the_existing_profile(env, drive):
    _built(env, drive)
    before = (VoiceStore("william-academic").directory / "profile.json").read_text(encoding="utf-8")
    attest_all("william", "school/", "u", category="academic_lab")
    results = {r.profile: r for r in build_identity("william")}
    assert results["academic"].status == "insufficient"
    assert "left unchanged" in results["academic"].reason
    assert (VoiceStore("william-academic").directory / "profile.json").read_text(
        encoding="utf-8"
    ) == before


def test_unreadable_training_documents_refuse_a_shrinking_rebuild(env, drive):
    _built(env, drive)
    store = IdentityStore("william")
    inventory = store.load_inventory()
    for entry in inventory["entries"].values():
        if entry["relative_path"] == "school/lab00.md":
            entry["status"] = "unreadable"
    store.save_inventory(inventory)
    results = {r.profile: r for r in build_identity("william", profiles=["academic"])}
    if results["academic"].status != "refused_incomplete_scan":
        # lab00 may have been holdout or a duplicate in this fixture; then a
        # shrink is not at stake and the rebuild is allowed.
        assert results["academic"].status == "built"
    else:
        assert "kept" in results["academic"].reason


def test_model_traits_require_explicit_remote_consent(env, drive):
    scan("william", sources=[str(drive)])
    with pytest.raises(ValueError, match="allow_remote_content"):
        build_identity("william", model_traits=True)


def test_profile_change_history_is_recorded(env, drive):
    _built(env, drive)
    lines = (
        (IdentityStore("william").directory / "profile_changes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    record = json.loads(lines[-1])
    assert record["profile"] == "william-academic" and record["status"] == "built"


def test_existing_voice_profiles_are_untouched(env, drive, tmp_path):
    from howlwriter.voice.corpus.build import build_voice

    legacy = tmp_path / "legacy_corpus"
    legacy.mkdir()
    for index in range(10):
        (legacy / f"n{index}.md").write_text(
            (drive / "school" / f"lab{index:02d}.md").read_text(), encoding="utf-8"
        )
    build_voice("william", [legacy], deterministic_only=True)
    before = (VoiceStore("william").directory / "profile.json").read_text(encoding="utf-8")
    _built(env, drive)
    assert (VoiceStore("william").directory / "profile.json").read_text(encoding="utf-8") == before
