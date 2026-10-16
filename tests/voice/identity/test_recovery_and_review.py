"""Legacy corpus recovery, worksheet answers, families, and grouped review."""

from __future__ import annotations

import hashlib
import json

import pytest

from howlwriter.voice.corpus.build import build_voice
from howlwriter.voice.corpus.split import assign_split
from howlwriter.voice.corpus.store import VoiceStore
from howlwriter.voice.identity import review, worksheet
from howlwriter.voice.identity.families import (
    assign_families,
    assignment_key,
    base_name,
    series_key,
)
from howlwriter.voice.identity.legacy import reconcile
from howlwriter.voice.identity.profiles import build_identity, select_sources
from howlwriter.voice.identity.scanner import scan
from howlwriter.voice.identity.store import IdentityStore, source_path_of

from tests.voice.identity.conftest import attest_all, author_a


def synthetic_worksheet(answers: int, seed: int = 0) -> str:
    """A publisher-style worksheet: running header per page, numbered prompts, answers."""
    import random

    rng = random.Random(seed)
    pages = []
    for page in range(1, 7):
        lines = ["Conducting Synthetic Investigations (4e)", "Jordan Student, Course 700"]
        for prompt in range(2):
            n = page * 2 + prompt
            lines.append(f"{n}. Make a screen capture showing the configured sensor and the")
            lines.append("resulting alert in the console window.")
            for answer in range(answers):
                lines.append(
                    f"In my capture {n}.{answer} the alert fired after rule reload "
                    f"{rng.randint(2, 99)}, which suggests the "
                    f"{rng.choice(['parser', 'sensor', 'queue'])} was not watching the interface."
                )
        lines.append(f"Page {page}")
        pages.append("\n".join(lines))
    return "\n\n".join(pages)


# --- worksheet segmentation ---


def test_worksheet_answers_are_separated_from_publisher_text():
    text = synthetic_worksheet(answers=2)
    result = worksheet.segment(text)
    assert result.is_worksheet
    assert 0 < result.answer_share < 0.65
    answers = worksheet.extract_answers(text)
    assert "Make a screen capture" not in answers
    assert "Conducting Synthetic Investigations" not in answers
    assert "Page 3" not in answers
    assert "In my capture" in answers


def test_ordinary_prose_is_never_treated_as_a_worksheet():
    text = author_a(5)
    assert not worksheet.segment(text).is_worksheet
    assert worksheet.extract_answers(text) == ""


def test_scanner_proposes_answers_only_for_worksheets(env, tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    (root / "Lab One (4e) - Jordan Student.txt").write_text(
        synthetic_worksheet(answers=3), encoding="utf-8"
    )
    (root / "Lab Two (4e) - Jordan Student.txt").write_text(
        synthetic_worksheet(answers=0, seed=1), encoding="utf-8"
    )
    scan("william", sources=[str(root)])
    entries = {
        e["source_path"]: e for e in IdentityStore("william").load_inventory()["entries"].values()
    }
    rich, poor = (
        entries["Lab One (4e) - Jordan Student.txt"],
        entries["Lab Two (4e) - Jordan Student.txt"],
    )
    assert rich["worksheet"] and rich["proposal"]["proposed_extraction"] == "worksheet_answers"
    assert rich["proposal"]["authorship"] == "MIXED_AUTHORSHIP" and rich["proposal"]["needs_review"]
    assert rich["eligible_words"] < rich["words"]
    assert poor["proposal"]["needs_review"] is False


def test_attested_worksheet_contributes_only_its_answer_lines(env, tmp_path):
    root = tmp_path / "drive"
    (root / "school").mkdir(parents=True)
    for index in range(10):
        (root / "school" / f"lab{index:02d}.md").write_text(author_a(index), encoding="utf-8")
    (root / "school" / "Lab One (4e) - Jordan Student.txt").write_text(
        synthetic_worksheet(answers=3), encoding="utf-8"
    )
    scan("william", sources=[str(root)])
    store = IdentityStore("william")
    attest_all("william", "school/lab", "h", category="academic_lab")
    sheet_id = next(k for k, e in store.load_inventory()["entries"].items() if e.get("worksheet"))
    with pytest.raises(ValueError):
        review.attest(store, sheet_id, "h", use_proposed_extraction=True)  # extraction needs MIXED
    decision = review.attest(store, sheet_id, "m", use_proposed_extraction=True)
    assert decision.extraction == "worksheet_answers"
    config = store.load_config()
    choices, _ = select_sources(
        config,
        store.load_inventory()["entries"],
        store.load_decisions(),
        config.profiles["academic"],
    )
    sheet = next(c for c in choices if c.doc_id == sheet_id)
    filtered = sheet.selection.text_filter(synthetic_worksheet(answers=3))
    assert "Make a screen capture" not in filtered
    results = {r.profile: r for r in build_identity("william", profiles=["academic"])}
    assert results["academic"].status == "built"


def test_unknown_extraction_is_rejected(env, drive):
    scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    doc_id = next(iter(store.load_inventory()["entries"]))
    with pytest.raises(ValueError):
        review.attest(store, doc_id, "m", extraction="magic")
    with pytest.raises(ValueError):
        review.attest(store, doc_id, "m", extraction="worksheet_answers", include_paragraphs="1")


# --- families and holdout integrity ---


@pytest.mark.parametrize(
    "left, right",
    [
        ("papers/Report-draft.docx", "papers/Report-final.docx"),
        ("papers/Report v2.docx", "papers/Report.docx"),
        ("x/Paper2_Project Proposal.docx", "y/Paper 2 _ Project Submission.docx"),
    ],
)
def test_family_links(left, right):
    assert base_name(left) == base_name(right) or assignment_key(left) == assignment_key(right)


def test_series_key_groups_publisher_worksheets():
    assert series_key("Lab A (4e) - Jordan Student.pdf") == series_key(
        "Lab B (4e) - Jordan Student.pdf"
    )


def test_families_keep_revisions_on_one_side_of_the_split():
    docs = [(f"k{i}", f"fp{i}", "academic") for i in range(30)]
    groups = {f"k{i}": "family:A" for i in range(0, 30, 3)}
    split = assign_split(docs, groups=groups)
    sides = {split.side_of(k) for k in groups}
    assert len(sides) == 1


def test_assign_families_links_near_duplicates(env, tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    text = author_a(21)
    (root / "Essay.md").write_text(text, encoding="utf-8")
    (root / "Essay edited.md").write_text(
        text.replace("Lab Report", "Lab Report (edited)"), encoding="utf-8"
    )
    (root / "Other.md").write_text(author_a(77), encoding="utf-8")
    scan("william", sources=[str(root)])
    entries = IdentityStore("william").load_inventory()["entries"]
    families = assign_families(entries)
    by_name = {e["source_path"]: families[k] for k, e in entries.items() if k in families}
    assert by_name["Essay.md"] == by_name["Essay edited.md"] != by_name["Other.md"]


def test_colon_names_keep_their_full_path():
    assert (
        source_path_of("Lab: B7 - Packet Review") == "Lab: B7 - Packet Review"
    )
    assert source_path_of("1:Lab: B7") == "Lab: B7"
    assert source_path_of({"source_path": "a: b", "relative_path": "0:a: b"}) == "a: b"


# --- legacy reconciliation ---


def _legacy_hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir())}


def test_legacy_reconciliation_recovers_sources_without_touching_profiles(env, drive):
    build_voice("william", [drive], deterministic_only=True)
    legacy_dir = VoiceStore("william").directory
    before = _legacy_hashes(legacy_dir)
    (drive / "school" / "lab03.md").rename(drive / "school" / "moved-lab03.md")
    scan("william", sources=[str(drive)])
    payload = reconcile("william")
    assert _legacy_hashes(legacy_dir) == before
    summary = payload["summary"]
    assert summary["historical_sources"] == 16  # legacy discovery skipped "Shared with Me"
    assert summary["matched_by_content"] >= 1  # the moved file
    assert summary["missing"] == 0
    moved = next(s for s in payload["sources"].values() if s["legacy_key"].endswith("lab03.md"))
    assert moved["match"] == "content" and moved["current_path"] == "school/moved-lab03.md"
    ledger = IdentityStore("william").directory / "legacy_reconciliation.json"
    assert ledger.stat().st_mode & 0o077 == 0
    assert "appears to confirm" not in ledger.read_text(encoding="utf-8")


def test_reconciliation_respects_attestations(env, drive):
    build_voice("william", [drive], deterministic_only=True)
    scan("william", sources=[str(drive)])
    attest_all("william", "school/lab0", "h", category="academic_lab")
    payload = reconcile("william")
    confirmed = [s for s in payload["sources"].values() if s["confirmed"]]
    assert confirmed and all(s["recommendation"] == "candidate" for s in confirmed)


# --- grouped review and prioritisation ---


def test_group_decision_requires_the_exact_members(env, drive):
    scan("william", sources=[str(drive)])
    store = IdentityStore("william")
    groups = review.groups(store)
    assert groups
    group = groups[0]
    with pytest.raises(ValueError, match="changed"):
        review.attest_group(store, group.group_id, "h", confirmed_doc_ids=group.doc_ids[:-1])
    decisions = review.attest_group(store, group.group_id, "h", confirmed_doc_ids=group.doc_ids)
    assert len(decisions) == len(group.doc_ids)
    assert all(
        store.load_decisions()[d].authorship == "CONFIRMED_HUMAN_AUTHORED" for d in group.doc_ids
    )


def test_queue_carries_review_assistance_and_prefers_independent_documents(env, drive):
    scan("william", sources=[str(drive)])
    items = review.queue(IdentityStore("william"))
    assert items
    first = items[0]
    for field in ("eligible_words", "revision_history", "value", "family", "recommendation"):
        assert getattr(first, field) not in (None,)
    assert items == sorted(items, key=lambda i: (not i.reopened, -i.value, i.path))
    assert set(review.AUTHORSHIP_DESCRIPTIONS) >= {
        "CONFIRMED_HUMAN_AUTHORED",
        "SUBSTANTIALLY_AI_GENERATED",
    }


def test_cli_group_decision_refuses_without_confirmation(env, drive, capsys):
    from howlwriter.cli.main import main

    scan("william", sources=[str(drive)])
    group = review.groups(IdentityStore("william"))[0]
    assert (
        main(
            ["voice", "review", "--identity", "william", "--group", group.group_id, "--decide", "h"]
        )
        == 1
    )
    assert not IdentityStore("william").load_decisions()
    assert (
        main(
            [
                "voice",
                "review",
                "--identity",
                "william",
                "--group",
                group.group_id,
                "--decide",
                "h",
                "--yes",
            ]
        )
        == 0
    )
    assert len(IdentityStore("william").load_decisions()) == len(group.doc_ids)


def test_cli_legacy_reconcile(env, drive, capsys):
    from howlwriter.cli.main import main

    build_voice("william", [drive], deterministic_only=True)
    scan("william", sources=[str(drive)])
    capsys.readouterr()
    assert main(["voice", "legacy-reconcile", "--identity", "william", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["historical_sources"] == 16
