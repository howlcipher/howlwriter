"""The private registry, incremental rebuild, and the raw-text guarantee."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from howlwriter.domain.voice import VOICE_PROFILE_VERSION, VoiceOverrides
from howlwriter.voice.corpus.build import build_voice
from howlwriter.voice.corpus.store import (
    OVERRIDES_FILE,
    PROFILE_FILE,
    BuildRecord,
    SourceRecord,
    VoiceStore,
    validate_name,
    voices_root,
)
from tests.voice.corpus.conftest import synthetic_prose

REAL_SENTENCE = (
    "The rollback took eleven minutes, which was longer than the incident that "
    "caused it, and nobody had touched the runbook since the migration."
)


# --- naming and location ----------------------------------------------

def test_valid_names_are_normalized():
    assert validate_name("Jane") == "jane"
    assert validate_name("  jane_doe  ") == "jane_doe"
    assert validate_name("alex-2") == "alex-2"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "with space", "", "-leading", "x" * 65, "É"])
def test_names_that_could_escape_the_root_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_name(bad)


def test_voices_live_under_the_existing_user_data_root(monkeypatch):
    monkeypatch.delenv("HOWLWRITER_VOICES_DIR", raising=False)
    assert voices_root() == Path.home() / ".howlwriter" / "voices"


def test_the_environment_can_relocate_the_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("HOWLWRITER_VOICES_DIR", str(tmp_path / "elsewhere"))
    assert voices_root() == (tmp_path / "elsewhere").resolve()


def test_a_personal_voice_is_stored_outside_the_repository(store_root, build_corpus):
    outcome = build_voice("subject", [build_corpus(12)], store_root=store_root,
                          deterministic_only=True)
    repository = Path(__file__).resolve().parents[3]
    assert repository not in outcome.directory.parents
    assert outcome.directory.is_relative_to(store_root)


# --- atomicity ---------------------------------------------------------

def test_a_failed_build_leaves_the_previous_profile_untouched(store_root, build_corpus):
    corpus = build_corpus(12)
    first = build_voice("subject", [corpus], store_root=store_root, deterministic_only=True)
    original = (first.directory / PROFILE_FILE).read_text(encoding="utf-8")

    store = VoiceStore("subject", root=store_root)
    with pytest.raises(RuntimeError):
        with store.stage() as staged:
            staged.write_build(BuildRecord(status="mid-flight"))
            raise RuntimeError("provider exploded halfway through")

    assert store.exists()
    assert (store.directory / PROFILE_FILE).read_text(encoding="utf-8") == original


def test_an_abandoned_build_leaves_no_temporary_directory(store_root):
    store = VoiceStore("subject", root=store_root)
    with pytest.raises(RuntimeError):
        with store.stage() as staged:
            staged.write_build(BuildRecord())
            raise RuntimeError("stop")
    assert list(store_root.iterdir()) == []


def test_committing_without_a_profile_is_refused(store_root):
    store = VoiceStore("subject", root=store_root)
    with store.stage() as staged:
        staged.write_build(BuildRecord())
        with pytest.raises(RuntimeError, match="no profile.json"):
            staged.commit()


def test_replacement_is_atomic_and_leaves_no_scratch_directories(store_root, build_corpus):
    corpus = build_corpus(12)
    build_voice("subject", [corpus], store_root=store_root, deterministic_only=True)
    build_voice("subject", [corpus], store_root=store_root, deterministic_only=True)
    assert [p.name for p in store_root.iterdir()] == ["subject"]


# --- the raw-text guarantee -------------------------------------------

def test_no_corpus_prose_is_written_to_the_voice_directory(store_root, corpus_dir):
    """The promise the whole privacy model rests on."""
    for index in range(12):
        (corpus_dir / f"doc{index}.md").write_text(
            f"# Note {index}\n\n{REAL_SENTENCE}\n\n{synthetic_prose(index)}\n",
            encoding="utf-8",
        )
    outcome = build_voice("subject", [corpus_dir], store_root=store_root,
                          deterministic_only=True)

    for path in outcome.directory.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
            assert "rollback took eleven minutes" not in content, path.name
            assert "since the migration" not in content, path.name


def test_the_profile_contains_no_long_strings_at_all(store_root, build_corpus):
    outcome = build_voice("subject", [build_corpus(12)], store_root=store_root,
                          deterministic_only=True)
    profile = json.loads((outcome.directory / PROFILE_FILE).read_text(encoding="utf-8"))

    def strings(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in ("warnings", "sufficiency_warnings", "notes", "reason"):
                    yield from strings(value)
        elif isinstance(node, list):
            for item in node:
                yield from strings(item)
        elif isinstance(node, str):
            yield node

    for value in strings(profile):
        assert len(value.split()) <= 12, value


def test_a_corpus_built_profile_holds_no_examples_or_phrase_bank(store_root, build_corpus):
    outcome = build_voice("subject", [build_corpus(12)], store_root=store_root,
                          deterministic_only=True)
    assert outcome.profile.representative_examples == []
    assert outcome.profile.preferred_phrases == []
    assert outcome.profile.disliked_phrases == []
    assert outcome.profile.generated_from == "corpus_build"
    assert outcome.profile.version == VOICE_PROFILE_VERSION


def test_temporary_extraction_leaves_nothing_behind_on_failure(store_root, corpus_dir, monkeypatch):
    for index in range(12):
        (corpus_dir / f"doc{index}.md").write_text(synthetic_prose(index), encoding="utf-8")

    from howlwriter.voice.corpus import build as build_module

    def explode(*args, **kwargs):
        raise RuntimeError("aggregation failed")

    monkeypatch.setattr(build_module, "aggregate", explode)
    with pytest.raises(RuntimeError):
        build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)

    assert not (store_root / "subject").exists()
    assert list(store_root.iterdir()) == []


def test_the_feature_cache_holds_vectors_not_prose(store_root, corpus_dir):
    for index in range(12):
        (corpus_dir / f"doc{index}.md").write_text(
            f"{REAL_SENTENCE}\n\n{synthetic_prose(index)}", encoding="utf-8"
        )
    outcome = build_voice("subject", [corpus_dir], store_root=store_root,
                          deterministic_only=True)
    cache = json.loads((outcome.directory / "features.json").read_text(encoding="utf-8"))
    serialized = json.dumps(cache)
    assert "rollback" not in serialized
    for entry in cache["documents"].values():
        assert set(entry) <= {
            "content_hash", "features", "context", "classification", "reused",
            "model_traits",
        }
        assert all(isinstance(v, (int, float)) for v in entry["features"].values())
        # Cached trait labels are short vocabulary values, never prose.
        for value in (entry.get("model_traits") or {}).values():
            assert len(str(value).split()) <= 3, value


# --- source metadata ---------------------------------------------------

def test_source_metadata_records_what_a_rebuild_needs_and_nothing_more(store_root, build_corpus):
    outcome = build_voice("subject", [build_corpus(12)], store_root=store_root,
                          deterministic_only=True)
    store = VoiceStore("subject", root=store_root)
    sources = store.load_sources()
    assert sources
    for record in sources.values():
        assert isinstance(record, SourceRecord)
        assert record.path
        # Paths and hashes are needed to detect change; content is not stored.
        assert not hasattr(record, "text")
    assert outcome.report.unique_canonical_files > 0


def test_inspection_summaries_never_contain_a_filename(store_root, corpus_dir):
    for index in range(12):
        (corpus_dir / f"secret_project_{index}.md").write_text(
            synthetic_prose(index), encoding="utf-8"
        )
    outcome = build_voice("subject", [corpus_dir], store_root=store_root,
                          deterministic_only=True)
    summary = outcome.profile.corpus_summary
    assert "secret_project" not in json.dumps(summary.to_dict())


# --- incremental rebuild ----------------------------------------------

def test_rebuild_picks_up_an_added_file(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    first = build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    (corpus_dir / "extra.md").write_text(synthetic_prose(900, paragraphs=8), encoding="utf-8")
    second = build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    assert second.report.candidate_prose_files == first.report.candidate_prose_files + 1


def test_rebuild_notices_a_changed_file(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    before = VoiceStore("subject", root=store_root).load_sources()
    target = str((corpus_dir / "doc03.md").resolve())
    original_hash = before[target].content_hash

    (corpus_dir / "doc03.md").write_text(synthetic_prose(555, paragraphs=9), encoding="utf-8")
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    after = VoiceStore("subject", root=store_root).load_sources()
    assert after[target].content_hash != original_hash


def test_rebuild_drops_a_removed_file(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    target = str((corpus_dir / "doc03.md").resolve())
    (corpus_dir / "doc03.md").unlink()
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    assert target not in VoiceStore("subject", root=store_root).load_sources()


def test_unchanged_files_reuse_their_cached_features(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    outcome = build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    cache = json.loads((outcome.directory / "features.json").read_text(encoding="utf-8"))
    reused = sum(1 for entry in cache["documents"].values() if entry.get("reused"))
    assert reused == len(cache["documents"])
    assert reused > 0


def test_no_cache_forces_a_full_recompute(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    outcome = build_voice("subject", [corpus_dir], store_root=store_root,
                          deterministic_only=True, reuse_cache=False)
    cache = json.loads((outcome.directory / "features.json").read_text(encoding="utf-8"))
    assert all(not entry.get("reused") for entry in cache["documents"].values())


def test_the_split_survives_a_rebuild(store_root, corpus_dir, build_corpus):
    build_corpus(20)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    before = {k: v.split for k, v in VoiceStore("subject", root=store_root).load_sources().items()}

    (corpus_dir / "new.md").write_text(synthetic_prose(777, paragraphs=7), encoding="utf-8")
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    after = VoiceStore("subject", root=store_root).load_sources()

    for key, side in before.items():
        if key in after and side:
            assert after[key].split == side, key


def test_stored_roots_let_rebuild_run_without_arguments(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    assert VoiceStore("subject", root=store_root).load_roots() == [str(corpus_dir)]


# --- overrides ---------------------------------------------------------

def test_overrides_survive_a_rebuild_verbatim(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)

    store = VoiceStore("subject", root=store_root)
    authored = (
        "# my own comment, which must survive\n"
        "preserve:\n  - long flowing sentences\n"
        "avoid:\n  - overly polished conclusions\n"
        "traits:\n  directness: high\n"
        'notes: "keep the roughness"\n'
    )
    (store.directory / OVERRIDES_FILE).write_text(authored, encoding="utf-8")

    outcome = build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)

    assert (store.directory / OVERRIDES_FILE).read_text(encoding="utf-8") == authored
    assert outcome.profile.overrides.preserve == ["long flowing sentences"]
    assert outcome.profile.overrides.avoid == ["overly polished conclusions"]
    assert outcome.profile.overrides.traits == {"directness": "high"}


def test_a_user_override_beats_the_generated_trait(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    store = VoiceStore("subject", root=store_root)
    (store.directory / OVERRIDES_FILE).write_text(
        "preserve: []\navoid: []\ntraits:\n  sentence_length: very_long\nnotes: \"\"\n",
        encoding="utf-8",
    )
    outcome = build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    resolved = outcome.profile.effective_trait("sentence_length")
    assert resolved.value == "very_long"
    assert resolved.source == "user"


def test_generated_traits_stay_separate_from_overrides(store_root, corpus_dir, build_corpus):
    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    store = VoiceStore("subject", root=store_root)
    (store.directory / OVERRIDES_FILE).write_text(
        "preserve: []\navoid: []\ntraits:\n  sentence_length: very_long\nnotes: \"\"\n",
        encoding="utf-8",
    )
    outcome = build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)
    # The generated observation is still recorded; the override sits beside it.
    assert outcome.profile.traits["sentence_length"].source == "deterministic"
    assert outcome.profile.overrides.traits["sentence_length"] == "very_long"


def test_a_malformed_overrides_file_is_surfaced_not_swallowed(store_root, build_corpus):
    outcome = build_voice("subject", [build_corpus(12)], store_root=store_root,
                          deterministic_only=True)
    (outcome.directory / OVERRIDES_FILE).write_text("preserve: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid YAML"):
        VoiceStore("subject", root=store_root).load_overrides()


def test_a_first_build_writes_a_commented_overrides_template(store_root, build_corpus):
    outcome = build_voice("subject", [build_corpus(12)], store_root=store_root,
                          deterministic_only=True)
    content = (outcome.directory / OVERRIDES_FILE).read_text(encoding="utf-8")
    assert "User overrides for the 'subject' voice" in content
    assert VoiceStore("subject", root=store_root).load_overrides() == VoiceOverrides()


# --- listing and removal ----------------------------------------------

def test_listing_and_removal(store_root, build_corpus):
    corpus = build_corpus(12)
    build_voice("one", [corpus], store_root=store_root, deterministic_only=True)
    build_voice("two", [corpus], store_root=store_root, deterministic_only=True)
    assert VoiceStore.list_names(store_root) == ["one", "two"]

    assert VoiceStore("one", root=store_root).delete()
    assert VoiceStore.list_names(store_root) == ["two"]
    assert not VoiceStore("one", root=store_root).delete()


def test_loading_a_missing_voice_explains_how_to_build_one(store_root):
    with pytest.raises(FileNotFoundError, match="voice build"):
        VoiceStore("nobody", root=store_root).load_profile()


# --- run records -------------------------------------------------------

def test_a_build_writes_a_privacy_safe_run_record(store_root, corpus_dir, monkeypatch, tmp_path):
    """Voice builds join the same local ledger, carrying counts only."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(runs))
    for index in range(12):
        (corpus_dir / f"doc{index}.md").write_text(
            f"{REAL_SENTENCE}\n\n{synthetic_prose(index)}", encoding="utf-8"
        )
    build_voice("subject", [corpus_dir], store_root=store_root, deterministic_only=True)

    written = list(runs.glob("*.json"))
    assert written, "a voice build should leave a run record"
    record = json.loads(written[0].read_text(encoding="utf-8"))

    assert record["command"] == "voice build"
    assert record["metadata"]["voice_name"] == "subject"
    assert record["metadata"]["included_documents"] > 0
    assert record["metadata"]["training_words"] > 0

    # No prose, no path, no filename anywhere in the record.
    serialized = json.dumps(record)
    assert "rollback took eleven minutes" not in serialized
    assert str(corpus_dir) not in serialized
    assert "doc03" not in serialized


def test_a_failing_run_record_never_breaks_a_build(store_root, build_corpus, monkeypatch):
    from howlwriter.diagnostic import run_record as run_record_module

    def explode(self, *args, **kwargs):
        raise OSError("runs directory is read-only")

    monkeypatch.setattr(run_record_module.RunRecord, "save", explode)
    outcome = build_voice("subject", [build_corpus(12)], store_root=store_root,
                          deterministic_only=True)
    assert outcome.profile.traits


def test_the_corpus_counts_reconcile(store_root, corpus_dir):
    """included + holdout + excluded + held must account for every candidate.

    A held-for-review document is neither used nor rejected, so leaving it out
    of the summary made the reported numbers quietly fail to add up.
    """
    from tests.voice.corpus.conftest import synthetic_prose as prose

    for index in range(10):
        (corpus_dir / f"good{index}.md").write_text(prose(index, 6), encoding="utf-8")
    # A document addressed entirely to a reader: held, not excluded.
    for index in range(2):
        (corpus_dir / f"guide{index}.md").write_text(
            ("You should check your logs before you escalate. You will find that your "
             "alert routing is wrong. You need to verify your channel membership, and "
             "you must confirm your on-call schedule is current. You can then close "
             "your ticket once you have confirmed your fix works as you expect.\n\n") * 4,
            encoding="utf-8",
        )
    # A document that is not prose at all: excluded.
    (corpus_dir / "notprose.md").write_text("Too short.", encoding="utf-8")

    outcome = build_voice("subject", [corpus_dir], store_root=store_root,
                          deterministic_only=True)
    summary = outcome.profile.corpus_summary

    accounted = (
        summary.included_documents
        + summary.holdout_documents
        + summary.excluded_documents
        + summary.held_for_review_documents
    )
    assert accounted == summary.candidate_prose_files, (
        f"{accounted} accounted for, {summary.candidate_prose_files} candidates"
    )
    assert summary.held_for_review_documents >= 1


def test_abstract_trait_labels_are_cached_across_rebuilds(store_root, corpus_dir, build_corpus):
    """An unchanged document must not be sent to a provider twice.

    Trait labels are privacy-safe derived data, so caching them is allowed --
    and without it every rebuild re-ran the whole corpus through a provider to
    arrive at the same answer.
    """
    from howlwriter.integration.howlplane_bridge import (
        HowlPlaneWritingBridge,
        set_howlplane_bridge,
    )
    from howlwriter.voice.corpus.traits import TRAIT_SCHEMA
    from src.control_plane.agent_execution import FakeAgentBackend
    from src.control_plane.role_binding import (
        RoleBinding,
        RoleBindingRegistry,
        RoleDispatcher,
    )

    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(domain="writing", role="voice_analyst", provider="fake")
    )
    set_howlplane_bridge(
        HowlPlaneWritingBridge(dispatcher=RoleDispatcher(binding_registry=registry),
                               registry=registry)
    )

    traits = {name: allowed[0] for name, allowed in TRAIT_SCHEMA.items()}
    payload = json.dumps({str(i): traits for i in range(1, 9)})
    backend = FakeAgentBackend(agent_id="fake", default_stdout=f"```json\n{payload}\n```")

    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, custom_backend=backend)
    first_calls = len(backend.executed_calls)
    assert first_calls > 0, "the first build should reach the provider"

    cache = json.loads(
        (VoiceStore("subject", root=store_root).directory / "features.json").read_text()
    )
    stored = [e for e in cache["documents"].values() if e.get("model_traits")]
    assert stored, "trait labels should be cached"

    # Nothing changed, so the rebuild should reach the provider fewer times.
    backend.executed_calls.clear()
    build_voice("subject", [corpus_dir], store_root=store_root, custom_backend=backend)
    assert len(backend.executed_calls) < first_calls


def test_a_changed_document_is_re_analyzed_not_served_from_cache(
    store_root, corpus_dir, build_corpus
):
    from howlwriter.integration.howlplane_bridge import (
        HowlPlaneWritingBridge,
        set_howlplane_bridge,
    )
    from howlwriter.voice.corpus.traits import TRAIT_SCHEMA
    from src.control_plane.agent_execution import FakeAgentBackend
    from src.control_plane.role_binding import (
        RoleBinding,
        RoleBindingRegistry,
        RoleDispatcher,
    )

    registry = RoleBindingRegistry()
    registry.register_binding(
        RoleBinding(domain="writing", role="voice_analyst", provider="fake")
    )
    set_howlplane_bridge(
        HowlPlaneWritingBridge(dispatcher=RoleDispatcher(binding_registry=registry),
                               registry=registry)
    )
    traits = {name: allowed[0] for name, allowed in TRAIT_SCHEMA.items()}
    payload = json.dumps({str(i): traits for i in range(1, 9)})
    backend = FakeAgentBackend(agent_id="fake", default_stdout=f"```json\n{payload}\n```")

    build_corpus(12)
    build_voice("subject", [corpus_dir], store_root=store_root, custom_backend=backend)

    (corpus_dir / "doc03.md").write_text(synthetic_prose(910, paragraphs=9), encoding="utf-8")
    backend.executed_calls.clear()
    build_voice("subject", [corpus_dir], store_root=store_root, custom_backend=backend)
    assert backend.executed_calls, "a changed document must be re-analyzed"
