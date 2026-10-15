"""Voice resolution: names, paths, failures, provenance, automatic selection.

Regression suite for the silent-fallback defect: a spec or outline naming a
registry voice reached a path-only loader, nothing loaded, and provenance
still said a profile was configured.
"""

from __future__ import annotations

import json

import pytest

from howlwriter.cli.main import main
from howlwriter.config.defaults import default_config
from howlwriter.voice.corpus.build import build_voice
from howlwriter.voice.selection import (
    KIND_AUTHOR_LABEL,
    KIND_FILE,
    KIND_REGISTRY,
    VoiceSelectionError,
    apply_selection,
    provenance_record,
    require_loaded,
    resolve_reference,
    select_for_context,
)

from tests.voice.corpus.conftest import synthetic_prose


@pytest.fixture
def registry(tmp_path, monkeypatch):
    root = tmp_path / "voices"
    monkeypatch.setenv("HOWLWRITER_VOICES_DIR", str(root))
    monkeypatch.setenv("HOWLWRITER_IDENTITIES_DIR", str(tmp_path / "identities"))
    monkeypatch.setenv("HOWLWRITER_PREFERENCES_FILE", str(tmp_path / "prefs.yaml"))
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for index in range(10):
        (corpus / f"d{index}.md").write_text(synthetic_prose(index), encoding="utf-8")
    build_voice("jane", [corpus], store_root=root, deterministic_only=True)
    return root


def test_registry_name_resolves(registry):
    selection = resolve_reference("jane")
    assert selection.kind == KIND_REGISTRY and selection.applied == "jane"
    assert selection.config_value.endswith("jane/profile.json")


def test_explicit_path_resolves(registry):
    path = registry / "jane" / "profile.json"
    selection = resolve_reference(str(path))
    assert selection.kind == KIND_FILE and selection.config_value == str(path.resolve())


@pytest.mark.parametrize("value", ["missing-voice", "william_v2", "/nope/profile.json", "x.json"])
def test_missing_explicit_voice_fails_clearly(registry, value):
    with pytest.raises(VoiceSelectionError, match="no personal voice"):
        resolve_reference(value)


def test_corrupt_profile_file_fails_instead_of_writing_generically(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(VoiceSelectionError, match="could not be loaded"):
        resolve_reference(str(bad))


def test_ambiguous_name_is_rejected(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "jane").write_text("{}", encoding="utf-8")
    with pytest.raises(VoiceSelectionError, match="ambiguous"):
        resolve_reference("jane")


def test_free_text_stays_an_author_label(registry):
    selection = resolve_reference("Jane Doe")
    assert selection.kind == KIND_AUTHOR_LABEL and selection.applied is None
    assert selection.to_provenance()["profile_applied"] is False


def test_provenance_records_applied_profile_without_paths(registry):
    config = default_config()
    apply_selection(config, spec_value="jane", spec_source="outline")
    record = provenance_record(config, loaded=True)
    assert record["requested"] == "jane" and record["applied"] == "jane"
    assert record["source"] == "outline" and record["profile_applied"] and record["profile_loaded"]
    assert "path" not in record and "/" not in json.dumps(record)


def test_flag_wins_over_spec(registry):
    config = default_config()
    selection = apply_selection(config, voice="jane", spec_value="Some Label")
    assert selection.source == "flag" and selection.applied == "jane"


def test_require_loaded_blocks_a_profile_that_did_not_load(registry):
    config = default_config()
    apply_selection(config, voice="jane")
    with pytest.raises(VoiceSelectionError, match="did not load"):
        require_loaded(config, None)


def _identity_with_profile(tmp_path, built: bool):
    from howlwriter.voice.identity.store import IdentityConfig, IdentityStore

    store = IdentityStore("ann")
    store.save_config(IdentityConfig.default("ann"))
    if built:
        corpus = tmp_path / "ann_corpus"
        corpus.mkdir()
        for index in range(8):
            (corpus / f"a{index}.md").write_text(synthetic_prose(100 + index), encoding="utf-8")
        build_voice("ann-academic", [corpus], deterministic_only=True)


def test_auto_selection_routes_by_mode(registry, tmp_path):
    _identity_with_profile(tmp_path, built=True)
    config = default_config()
    selection = apply_selection(config, identity="ann", mode="academic")
    assert selection.applied == "ann-academic" and selection.context == "academic"


def test_auto_selection_never_substitutes_a_missing_context(registry, tmp_path):
    _identity_with_profile(tmp_path, built=True)
    with pytest.raises(VoiceSelectionError, match="not been built"):
        select_for_context("professional", identity="ann")
    fallback = select_for_context("professional", identity="ann", allow_generic=True)
    assert fallback.fallback == "generic" and fallback.applied is None


def test_unknown_mode_does_not_inherit_a_profile(registry, tmp_path):
    _identity_with_profile(tmp_path, built=True)
    with pytest.raises(VoiceSelectionError, match="no context profile"):
        apply_selection(default_config(), identity="ann", mode="casual")


def test_auto_voice_without_identity_explains(registry):
    with pytest.raises(VoiceSelectionError, match="preferred_identity"):
        apply_selection(default_config(), auto_voice=True, mode="academic")


# --- commands ---


def test_humanize_with_a_nonexistent_voice_fails_loudly(registry, tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text("A short draft about monitoring.", encoding="utf-8")
    assert main(["humanize", str(draft), "--voice", "nobody", "--deterministic"]) == 1
    assert "no personal voice named 'nobody'" in capsys.readouterr().err


def test_humanize_with_a_valid_voice_still_works(registry, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text("A short draft about monitoring the network.", encoding="utf-8")
    assert main(["humanize", str(draft), "--voice", "jane", "--deterministic"]) == 0


def test_paper_spec_naming_a_missing_voice_is_refused(registry, tmp_path, capsys):
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        "title: T\ntopic: monitoring\ntarget_words: 300\nvoice_profile: william_v2\n",
        encoding="utf-8",
    )
    code = main(["paper", str(spec), "--deterministic"])
    assert code == 1
    assert "no personal voice named 'william_v2'" in capsys.readouterr().err


def test_howl_provenance_names_the_applied_voice(registry, tmp_path):
    from howlwriter.pipeline.howl import run_howl_pipeline

    draft = tmp_path / "draft.md"
    draft.write_text("A short draft about monitoring the network carefully.", encoding="utf-8")
    config = default_config()
    apply_selection(config, voice="jane")
    result = run_howl_pipeline(str(draft), config, deterministic_only=True)
    record = result.provenance.voice_profile
    assert record["applied"] == "jane" and record["profile_applied"] is True


def test_web_academic_route_rejects_a_missing_spec_voice(registry):
    from fastapi.testclient import TestClient

    from howlwriter.web.app import create_app

    client = TestClient(create_app())
    response = client.post(
        "/api/academic/generate",
        json={
            "spec": {
                "title": "T",
                "topic": "monitoring",
                "target_words": 300,
                "voice_profile": "william_v2",
            },
            "deterministic_only": True,
        },
    )
    assert response.status_code == 400
    assert "william_v2" in response.json()["error"]


def test_evaluate_with_a_nonexistent_voice_fails(registry, tmp_path, capsys):
    draft = tmp_path / "d.md"
    draft.write_text("text " * 50, encoding="utf-8")
    assert main(["evaluate", str(draft), "--voice", "nobody"]) == 1
