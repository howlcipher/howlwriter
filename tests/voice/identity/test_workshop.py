"""Voice Workshop: local prompts, verbatim private samples, bounded evidence."""

from __future__ import annotations

import json
import stat

import pytest

from howlwriter.cli.main import main
from howlwriter.voice.corpus.store import VoiceStore
from howlwriter.voice.identity import workshop as ws
from howlwriter.voice.identity.profiles import build_identity, load_calibration
from howlwriter.voice.identity.scanner import scan
from howlwriter.voice.identity.store import IdentityStore

from tests.voice.identity.conftest import attest_all

ANSWERS = [
    "honestly the rollout went fine but the alert thresholds were too tight so we tuned them twice.",
    "I would check the agent logs first, then the network path, then whether the token expired.",
    "We picked the queue because retries are cheap there; the cost is a few seconds of delay.",
    "The migration is blocked on a firewall change. I asked the network team and expect it Thursday.",
    "This script rotates the keys nightly. Run it by hand only after a revoke, and check the audit log.",
    "The outage came from a full disk on the collector. We added an alert at eighty percent "
    "and a cleanup job.",
    "I can't take the dashboard rewrite this sprint; the incident follow-ups come first, sorry.",
    "Short version: the parser choked on a malformed header, so I made it skip and log instead of crash.",
    "My take is that the second design is simpler to operate, even if the first is a bit faster on paper.",
    "Reviewing this change, I'd split the config loading out so the tests stop needing a real file.",
    "The lab showed that encrypted traffic hides payloads but not timing, which still leaks a lot.",
    "Next week I'll finish the runbook and walk the on-call folks through the new escalation path.",
]


@pytest.fixture
def workshop(env):
    return ws.Workshop("tester")


_SUBJECTS = iter(f"subject {i}" for i in range(10_000))


def _answer(workshop, text, *, context=None, subject=None, approve=True, self_written=True):
    prompt = workshop.next_prompt(context=context, subject=subject or next(_SUBJECTS))
    return workshop.add(
        prompt_id=prompt.prompt_id,
        subject=prompt.subject,
        text=text,
        self_written=self_written,
        approve=approve,
    )


def test_prompts_are_local_varied_and_not_repeated(workshop):
    seen = []
    for index in range(6):
        prompt = workshop.next_prompt(context="technical")
        seen.append(prompt.prompt_id)
        workshop.add(
            prompt_id=prompt.prompt_id,
            subject=prompt.subject,
            text=f"answer {index} " * 5,
            self_written=True,
        )
    assert len(set(seen)) == 6  # never repeated, short then paragraph prompts
    assert all(p.startswith("tec-") for p in seen)
    with pytest.raises(ValueError, match="choose a new subject"):
        workshop.next_prompt(context="technical")


def test_user_subject_is_used(workshop):
    prompt = workshop.next_prompt(context="professional", subject="the billing migration")
    assert "the billing migration" in prompt.text


def test_gap_order_prefers_profiles_without_documents(workshop):
    assert workshop.next_prompt().context in ("academic", "professional", "technical")
    assert workshop.gap_order()[-1] == "casual"


def test_answer_is_stored_verbatim_and_privately(workshop):
    text = "teh fix worked  but i didnt test the edge case yet"
    sample = _answer(workshop, text, context="technical", approve=False)
    stored = workshop.samples()[sample.sample_id]
    assert stored.text == text  # no correction of spelling, spacing or case
    assert stored.prompt_text and stored.prompt_text not in stored.text
    path = workshop.directory / ws.SAMPLES_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stored.status == ws.STATUS_PENDING


def test_approval_requires_a_self_written_answer(workshop):
    sample = _answer(
        workshop, ANSWERS[0], context="professional", approve=False, self_written=False
    )
    with pytest.raises(ValueError, match="wrote yourself"):
        workshop.approve(sample.sample_id)


def test_approved_samples_get_a_fixed_side(workshop):
    sample = _answer(workshop, ANSWERS[1], context="technical")
    side = sample.side
    assert side in ("train", "calibration")
    workshop.exclude(sample.sample_id)
    again = workshop.approve(sample.sample_id)
    assert again.side == side


def test_duplicates_and_repeated_prompts_count_once(workshop):
    first = _answer(workshop, ANSWERS[2], context="technical", subject="queues")
    dup = workshop.add(
        prompt_id=first.prompt_id,
        subject="queues",
        text=ANSWERS[2],
        self_written=True,
        approve=True,
    )
    assert dup.duplicate_of == first.sample_id
    counted = {s.sample_id for s in workshop.counted("professional")}
    assert first.sample_id in counted and dup.sample_id not in counted
    workshop.exclude(first.sample_id)
    # With the first answer excluded, the identical later answer is the only
    # copy left, so it now counts -- once.
    assert {s.sample_id for s in workshop.counted("professional")} == {dup.sample_id}


def test_excluding_an_answer_lets_a_later_answer_to_the_same_prompt_count(workshop):
    first = _answer(workshop, ANSWERS[3], context="professional", subject="the migration")
    second = workshop.add(
        prompt_id=first.prompt_id,
        subject="the migration",
        text=ANSWERS[4],
        self_written=True,
        approve=True,
    )
    assert {s.sample_id for s in workshop.counted("professional")} == {first.sample_id}
    workshop.exclude(first.sample_id)
    assert {s.sample_id for s in workshop.counted("professional")} == {second.sample_id}


def test_casual_answers_never_feed_formal_profiles(workshop):
    _answer(
        workshop, "saw the movie last night, the ending was a mess but i liked it", context="casual"
    )
    assert workshop.counted("academic") == [] and workshop.counted("professional") == []


def test_remove_deletes_text_and_reclassify_moves_context(workshop):
    sample = _answer(workshop, ANSWERS[5], context="technical")
    workshop.reclassify(sample.sample_id, "academic")
    assert workshop.samples()[sample.sample_id].context == "academic"
    workshop.remove(sample.sample_id)
    removed = workshop.samples()[sample.sample_id]
    assert removed.text == "" and removed.status == ws.STATUS_REMOVED
    assert ANSWERS[5] not in (workshop.directory / ws.SAMPLES_FILE).read_text(encoding="utf-8")


def test_preferred_revision_is_kept_apart_from_evidence(workshop, tmp_path):
    sample = _answer(workshop, ANSWERS[6], context="professional")
    workshop.set_preferred_revision(sample.sample_id, "A POLISHED VERSION")
    bundles = workshop.bundles("professional", document_words=0)
    text = "".join(path.read_text(encoding="utf-8") for path, _, _ in bundles)
    assert "A POLISHED VERSION" not in text
    assert workshop.samples()[sample.sample_id].text == ANSWERS[6]


def test_bundles_respect_sides_and_the_document_cap(workshop):
    for text in ANSWERS:
        _answer(workshop, text, context="professional")
    counted = workshop.counted("professional")
    bundles = workshop.bundles("professional", document_words=300)
    train_words = sum(w for _, side, w in bundles if side == "train")
    assert train_words <= 300 * ws.MAX_WORKSHOP_SHARE / (1 - ws.MAX_WORKSHOP_SHARE)
    calibration_ids = {s.sample_id for s in counted if s.side == "calibration"}
    train_text = "".join(p.read_text(encoding="utf-8") for p, side, _ in bundles if side == "train")
    for sample in counted:
        if sample.sample_id in calibration_ids:
            assert sample.text not in train_text
    for path, _, _ in bundles:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_coverage_reports_evidence_not_percentages(workshop):
    _answer(workshop, ANSWERS[7], context="technical")
    coverage = workshop.coverage()
    blob = json.dumps(coverage)
    assert "%" not in blob.replace("25%", "")
    professional = coverage["profiles"]["professional"]
    assert professional["workshop_samples"] == 1 and professional["sufficiency"] == "insufficient"
    assert "no attested documents in this context" in professional["gaps"]


def test_workshop_only_profile_is_refused_until_sufficient(env, workshop):
    for text in ANSWERS[:4]:
        _answer(workshop, text, context="professional")
    results = {r.profile: r for r in build_identity("tester", profiles=["professional"])}
    assert results["professional"].status == "insufficient"
    assert "Voice Workshop has" in results["professional"].reason


def test_workshop_evidence_joins_a_document_profile_but_not_its_scoring(env, drive):
    scan("william", sources=[str(drive)])
    attest_all("william", "school/", "h", category="academic_lab")
    book = ws.Workshop("william")
    for text in ANSWERS:
        _answer(book, text, context="academic")
    results = {r.profile: r for r in build_identity("william", profiles=["academic"])}
    academic = results["academic"]
    assert academic.status == "built"
    assert academic.workshop_bundles["train"] >= 1
    calibration = load_calibration("william-academic")
    assert calibration["workshop"]["training_words"] == academic.workshop_words
    sources = VoiceStore("william-academic").load_sources()
    bundle_records = [r for r in sources.values() if "/workshop/bundles/" in r.path]
    assert bundle_records and all(r.weight <= ws.WORKSHOP_WEIGHT for r in bundle_records)
    # Scoring evidence stays document-only: genuine calibration documents are
    # the attested documents, not the bundles.
    assert len(calibration["voice_match"]["genuine_distances"]) <= academic.eligible_documents


def test_workshop_cli_round_trip(env, capsys):
    assert (
        main(
            ["voice", "workshop", "--identity", "cli", "prompt", "--context", "technical", "--json"]
        )
        == 0
    )
    prompt = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                "voice",
                "workshop",
                "--identity",
                "cli",
                "answer",
                "--prompt-id",
                prompt["prompt_id"],
                "--subject",
                prompt["subject"],
                "--text",
                ANSWERS[8],
                "--self-written",
                "--approve",
                "--json",
            ]
        )
        == 0
    )
    saved = json.loads(capsys.readouterr().out)
    assert "text" not in saved and saved["status"] == "approved"
    assert main(["voice", "workshop", "--identity", "cli", "list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and "text" not in rows[0]
    assert main(["voice", "workshop", "--identity", "cli", "coverage", "--json"]) == 0
    assert IdentityStore("cli").exists()  # no scan needed to start


def test_workshop_web_api(env):
    from fastapi.testclient import TestClient

    from howlwriter.web.app import create_app

    client = TestClient(create_app())
    prompt = client.post(
        "/api/voice-intel/web/workshop/prompt", json={"context": "academic"}
    ).json()
    saved = client.post(
        "/api/voice-intel/web/workshop/samples",
        json={
            "prompt_id": prompt["prompt_id"],
            "subject": prompt["subject"],
            "text": ANSWERS[10],
            "self_written": True,
            "approve": False,
        },
    ).json()
    assert saved["status"] == "pending" and "text" not in saved
    listing = client.get("/api/voice-intel/web/workshop").json()
    assert listing["local_only"] is True and "text" not in listing["samples"][0]
    with_text = client.get("/api/voice-intel/web/workshop?show_text=true").json()
    assert with_text["samples"][0]["text"] == ANSWERS[10]
    sid = saved["sample_id"]
    assert (
        client.post(f"/api/voice-intel/web/workshop/samples/{sid}/actions/approve").json()["status"]
        == "approved"
    )
    assert (
        client.post(
            f"/api/voice-intel/web/workshop/samples/{sid}/context", json={"context": "casual"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/voice-intel/web/workshop/samples/{sid}/revision", json={"text": "better"}
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/voice-intel/web/workshop/samples/{sid}/actions/nope").status_code == 404
    )
    assert "web" in client.get("/api/voice-intel/identities").json()["identities"]


def test_workshop_data_is_git_ignored():
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    for path in (
        "identities/x/workshop/samples.json",
        ".howlwriter/identities/x/workshop/bundles/a.txt",
    ):
        assert (
            subprocess.run(
                ["git", "-C", str(repo), "check-ignore", "-q", "--no-index", path]
            ).returncode
            == 0
        )
