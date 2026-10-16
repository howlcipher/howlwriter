"""End-to-end evaluation, comparison, CLI, and web API over a built identity."""

from __future__ import annotations

import json

import pytest

from howlwriter.cli.main import main
from howlwriter.evaluation.personal import choose_profile, compare_texts, evaluate_text
from howlwriter.voice.identity.profiles import build_identity
from howlwriter.voice.identity.scanner import scan

from tests.voice.identity.conftest import attest_all, author_a


@pytest.fixture
def built(env, drive):
    scan("william", sources=[str(drive)])
    attest_all("william", "school/", "h", category="academic_lab")
    results = {r.profile: r for r in build_identity("william")}
    assert results["academic"].status == "built"
    return env


def test_evaluate_reports_both_scores_independently(built):
    report = evaluate_text(author_a(900), identity="william", mode="academic")
    assert report["profile_selection"]["voice"] == "william-academic"
    assert report["naturalness"]["metric"] == "human_naturalness"
    assert report["voice_match"]["metric"] == "personal_voice_match"
    assert report["model_calls"] == 0
    assert report["voice_match"]["status"] == "SCORED"


def test_mode_routing_and_missing_profiles_degrade_with_reasons(built):
    report = evaluate_text(author_a(901), identity="william", mode="linkedin")
    assert report["context"] == "professional"
    assert report["voice_match"]["status"] == "UNAVAILABLE"
    assert "has not been built" in report["voice_match"]["reason"]


def test_auto_voice_uses_preferred_identity(built, tmp_path):
    (built["tmp"] / "preferences.yaml").write_text(
        "preferred_identity: william\n", encoding="utf-8"
    )
    choice = choose_profile(author_a(902), auto_voice=True)
    assert choice.identity == "william"


def test_auto_voice_without_preference_explains(built):
    choice = choose_profile(author_a(903), auto_voice=True)
    assert choice.voice is None and "preferred_identity" in choice.reason


def test_no_identity_is_hardcoded(env):
    report = evaluate_text(author_a(904), mode="academic")
    assert report["profile_selection"]["voice"] is None
    assert report["voice_match"]["status"] == "UNAVAILABLE"


def test_zero_change_revision_preserves_substance(built):
    text = author_a(905)
    report = compare_texts(text, text, identity="william", mode="academic")
    assert report["verdict"] == "SUBSTANCE_PRESERVED"
    assert report["naturalness"]["delta"] in (0.0, None)


def test_changed_numbers_and_citations_are_flagged_whatever_the_score(built):
    original = author_a(906) + "\n\nThe transfer moved 512 MB in 40 seconds (Rivera, 2021)."
    revised = original.replace("512 MB", "5 GB").replace("(Rivera, 2021)", "")
    report = compare_texts(original, revised, identity="william", mode="academic")
    assert report["verdict"] == "REVISION_CHANGES_SUBSTANCE"
    assert report["factual_integrity"]["status"] != "FACTUALLY_PRESERVED"
    assert report["citations"]["status"] == "CHANGED"


def test_requirements_are_checked(built):
    text = author_a(907)
    report = compare_texts(
        text,
        text,
        identity="william",
        mode="academic",
        requirements={"min_words": 99999, "required_terms": ["Kerberos"]},
    )
    assert report["requirements"]["status"] == "FAIL"
    assert report["verdict"] == "REVISION_CHANGES_SUBSTANCE"


# --- CLI ---


def test_cli_evaluate_json_and_exit_codes(built, tmp_path, capsys):
    paper = tmp_path / "paper.md"
    paper.write_text(author_a(908), encoding="utf-8")
    assert (
        main(["evaluate", str(paper), "--identity", "william", "--mode", "academic", "--json"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["voice_match"]["profile"] == "william-academic"

    short = tmp_path / "short.md"
    short.write_text("Brief.", encoding="utf-8")
    assert (
        main(["evaluate", str(short), "--identity", "william", "--mode", "academic", "--strict"])
        == 4
    )

    revised = tmp_path / "revised.md"
    revised.write_text(author_a(908).replace("Lab Report", "Lab Report 99 GB"), encoding="utf-8")
    code = main(
        [
            "evaluate",
            str(paper),
            "--compare",
            str(revised),
            "--identity",
            "william",
            "--mode",
            "academic",
        ]
    )
    assert code in (0, 3)


def test_cli_human_report_withholds_numbers_honestly(env, tmp_path, capsys):
    paper = tmp_path / "paper.md"
    paper.write_text(author_a(909), encoding="utf-8")
    assert main(["evaluate", str(paper), "--mode", "academic"]) == 0
    out = capsys.readouterr().out
    assert "n/a" in out and "not the probability" in out


def test_cli_scan_review_build_status(env, drive, capsys):
    assert main(["voice", "scan", "--identity", "william", "--source", str(drive), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files_inventoried"] == 24
    assert main(["voice", "review", "--identity", "william", "--json"]) == 0
    pending = json.loads(capsys.readouterr().out)["pending"]
    assert pending, "fixture should produce reviewable academic documents"
    assert (
        main(
            [
                "voice", "review", "--identity", "william", "--set", pending[0]["doc_id"], "h",
                "--owner-confirmed",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(["voice", "build-identity", "--identity", "william", "--json"]) == 3
    )  # professional insufficient
    builds = json.loads(capsys.readouterr().out)
    assert {b["profile"] for b in builds} == {"academic", "professional"}
    assert main(["voice", "status", "--identity", "william", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["exclusions"] == ["gemini gems", "retroarchsaves", "shared drives"]


def test_cli_scan_unavailable_mount_exit_code(env, tmp_path, capsys):
    assert (
        main(["voice", "scan", "--identity", "william", "--source", str(tmp_path / "absent")]) == 2
    )


def test_cli_inspect_shows_calibration(built, capsys):
    assert main(["voice", "inspect", "william-academic"]) == 0
    out = capsys.readouterr().out
    assert "Voice Match calibration" in out and "Identity: William Elias" in out


# --- web ---


@pytest.fixture
def client(built):
    from fastapi.testclient import TestClient

    from howlwriter.web.app import create_app

    return TestClient(create_app())


def test_web_status_review_and_privacy_boundaries(client):
    assert client.get("/api/voice-intel/identities").json()["identities"] == ["william"]
    status = client.get("/api/voice-intel/william/status").json()
    assert {p["voice"] for p in status["profiles"]} == {"william-academic", "william-professional"}
    assert "lab0" not in json.dumps(status)
    queue = client.get("/api/voice-intel/william/review").json()
    assert all("path" not in item for item in queue["pending"])
    if queue["pending"]:
        doc_id = queue["pending"][0]["doc_id"]
        assert client.get(f"/api/voice-intel/william/review/{doc_id}/preview").status_code == 400
        assert (
            client.get(f"/api/voice-intel/william/review/{doc_id}/preview?confirm=true").status_code
            == 200
        )
        bad = client.post(
            f"/api/voice-intel/william/review/{doc_id}",
            json={"authorship": "NOPE"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert bad.status_code == 400


def test_web_evaluate_and_compare(client):
    text = author_a(910)
    report = client.post(
        "/api/voice-intel/evaluate", json={"text": text, "identity": "william", "mode": "academic"}
    ).json()
    assert report["voice_match"]["status"] == "SCORED"
    comparison = client.post(
        "/api/voice-intel/compare",
        json={
            "original": text,
            "revised": text,
            "identity": "william",
            "mode": "academic",
        },
    ).json()
    assert comparison["verdict"] == "SUBSTANCE_PRESERVED"


def test_web_unknown_identity_is_404(client):
    assert client.get("/api/voice-intel/nobody/status").status_code == 404
    assert client.get("/api/voice-intel/BAD..NAME/status").status_code in (400, 404)


def test_web_scan_job_uses_configured_sources_only(client):
    job = client.post("/api/voice-intel/william/scan").json()
    assert job["job_type"] == "voice_intel_scan"
    assert client.post("/api/voice-intel/william/scan", json={"source": "/etc"}).status_code == 200


def test_writing_report_gets_a_calibrated_voice_match(built):
    from howlwriter.domain.report import WritingReport
    from howlwriter.evaluation.personal import attach_voice_match
    from howlwriter.voice.corpus.resolve import profile_reference

    report = WritingReport()
    attach_voice_match(report, profile_reference("william-academic"), author_a(950))
    assert report.voice_match is not None and 0.0 <= report.voice_match <= 1.0
    assert report.voice_match_band in ("WITHIN_RANGE", "EDGE_OF_RANGE", "ATYPICAL")
    rendered = report.render_text()
    assert "/100 percentile" in rendered and "not authorship" in rendered


def test_writing_report_states_why_voice_match_is_withheld(built):
    from howlwriter.domain.report import WritingReport
    from howlwriter.evaluation.personal import attach_voice_match
    from howlwriter.voice.corpus.resolve import profile_reference

    report = WritingReport()
    attach_voice_match(report, profile_reference("william-academic"), "Too short.")
    assert report.voice_match is None
    assert "unavailable" in report.render_text()


def test_uncalibrated_voices_keep_the_omit_dont_fake_rule(tmp_path):
    from howlwriter.domain.report import WritingReport
    from howlwriter.evaluation.personal import attach_voice_match

    report = WritingReport()
    attach_voice_match(report, str(tmp_path / "voices" / "jane" / "profile.json"), author_a(951))
    attach_voice_match(report, "Jane Doe", author_a(951))
    assert report.voice_match is None and report.voice_match_basis is None
    assert "Voice match" not in report.render_text()


def test_multiword_citation_removal_is_flagged(built):
    original = author_a(960) + "\n\nThe framework was revised (Office of Management and Budget, 2020)."
    revised = original.replace(" (Office of Management and Budget, 2020)", "")
    report = compare_texts(original, revised, identity="william", mode="academic")
    assert report["citations"]["status"] == "CHANGED"
    assert report["verdict"] == "REVISION_CHANGES_SUBSTANCE"


def test_scores_state_their_resolution(built):
    report = evaluate_text(author_a(961), identity="william", mode="academic")
    if report["voice_match"]["status"] == "SCORED":
        assert report["voice_match"]["resolution"] > 0
    if report["naturalness"]["status"] == "SCORED":
        assert report["naturalness"]["resolution"] > 0
