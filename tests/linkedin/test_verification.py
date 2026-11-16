"""Verification service, report, verifier and publish gate against a scripted HowlProof.

The scripted program is a mock: these tests prove HowlWriter's handling of each
HowlProof outcome. Real HowlProof behavior is covered in test_howlproof_contract.py.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources

import pytest

from howlwriter.cli.main import main
from howlwriter.linkedin.howlproof import VERDICTS
from howlwriter.linkedin.models import ArtifactRef, LifecycleState
from howlwriter.linkedin.service import OperationRefused, QueueService
from howlwriter.linkedin.verification import (
    BLOCKED,
    CONTRACT_FILENAME,
    DEFAULT_CONTRACT,
    ELIGIBLE,
    HOWLPROOF_ROOT,
    ReportVerifier,
    VerificationGate,
    VerificationService,
    derive_outcome,
    report_problems,
)
from tests.linkedin.helpers import ref_for
from tests.linkedin.proof_fakes import FakeHowlProof, check
from tests.linkedin.test_content_checks import png

S = LifecycleState
TEXT = "Shipping small changes every day keeps reviews short.\n\nWhat has worked for your team?"


@pytest.fixture
def store(tmp_path):
    from howlwriter.linkedin.store import QueueStore

    queue_store = QueueStore(tmp_path / "repo")
    queue_store.initialize({CONTRACT_FILENAME: DEFAULT_CONTRACT})
    return queue_store


@pytest.fixture
def fake():
    return FakeHowlProof()


@pytest.fixture
def verification(store, clock, fake):
    return VerificationService(store, fake.adapter(), clock)


def draft(service, text: str = TEXT, **kwargs):
    return service.add_draft(title="A post", text=text, actor="tester", **kwargs)


def reload(store, post):
    return store.load_post(post.id)


def rewrite_report(store, post, mutate) -> ArtifactRef:
    """Edit the attached report and re-point the reference at the edited bytes (a forgery attempt)."""
    ref = reload(store, post).verification_ref
    path = store.artifact_file(ref.path)
    report = json.loads(path.read_text(encoding="utf-8"))
    mutate(report)
    payload = json.dumps(report).encode()
    path.write_bytes(payload)
    return ArtifactRef(ref.path, hashlib.sha256(payload).hexdigest(), ref.content_fingerprint)


# Eligible path


def test_clean_post_gets_a_report_and_a_reference(store, service, verification, fake):
    post = draft(service)
    result = verification.verify(post.id, actor="tester")

    assert result.eligible and result.attached
    report = result.report
    assert report["verdict"] == "CONDITIONALLY_PROVEN" == report["howlproof"]["verdict"]
    assert report["outcome"]["status"] == ELIGIBLE and report["outcome"]["human_approval_required"] is True
    assert report["post_id"] == post.id and report["content_fingerprint"] == post.computed_fingerprint()
    assert report["created_at"] == "2026-11-16T12:00:00Z"
    assert report["tools"]["howlproof"]["version"] == "0.0.0-fake"
    assert report["howlproof"]["contract"]["sha256"] == hashlib.sha256(DEFAULT_CONTRACT.encode()).hexdigest()
    assert report["howlproof"]["bundle_path"].startswith(HOWLPROOF_ROOT + "/hp-")
    assert {f["path"] for f in report["package"]["files"]} == {"post.txt", "post.json"}

    stored = reload(store, post)
    ref = stored.verification_ref
    payload = store.artifact_file(ref.path).read_bytes()
    assert ref.path == result.report_path and hashlib.sha256(payload).hexdigest() == ref.sha256
    assert json.loads(payload) == report
    assert stored.state is S.DRAFT, "verification never changes the lifecycle state on success"
    assert stored.approval_ref is None, "verification never approves"
    assert stored.history[-1].action == "verification_attached"
    assert ReportVerifier(store).problems("verification", stored, ref) == []


def test_report_matches_the_published_schema(store, service, verification, fake):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        resources.files("howlwriter.schemas")
        .joinpath("howlwriter.linkedin_verification.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    (store.root / "media" / "chart.png").write_bytes(png(1200, 627))
    digest = hashlib.sha256(png(1200, 627)).hexdigest()
    from howlwriter.linkedin.models import MediaRef

    fake.acquisitions = {"https://example.com/a": {}}
    with_everything = draft(
        service,
        TEXT + "\nhttps://example.com/a",
        urls=["https://example.com/a"],
        media=[MediaRef("media/chart.png", digest, "A bar chart of weekly build time")],
    )
    first = verification.verify(with_everything.id, actor="tester", allow_network=True).report
    fake.exit_code = 2
    second = verification.verify(draft(service, "Another clean post.").id, actor="tester").report
    for report in (first, second):
        assert list(validator.iter_errors(report)) == []
        assert report_problems(report) == []
    assert first["media"][0]["width"] == 1200 and first["links"]["results"][0]["status"] == "REACHABLE"
    assert report_problems({**first, "verdict": "APPROVED"}) and report_problems([])


@pytest.mark.parametrize("verdict", VERDICTS)
def test_howlproof_verdict_is_preserved_and_decides_eligibility(store, service, verification, fake, verdict):
    fake.verdict = verdict
    fake.rationale = [f"scripted reason for {verdict}"]
    post = draft(service)
    result = verification.verify(post.id, actor="tester")

    assert result.report["verdict"] == verdict, "the verdict is never rewritten"
    expected = verdict in ("PROVEN", "CONDITIONALLY_PROVEN", "REQUIRES_HUMAN")
    assert result.eligible is expected
    assert (reload(store, post).verification_ref is not None) is expected
    if not expected:
        assert any(verdict in blocker for blocker in result.report["outcome"]["blockers"])
    elif verdict != "PROVEN":
        limitations = result.report["outcome"]["limitations"]
        assert f"HowlProof {verdict}: scripted reason for {verdict}" in limitations


def test_proven_still_requires_human_approval_and_cannot_be_approved_here(store, service, verification, fake):
    fake.verdict = "PROVEN"
    fake.checks = [check("secrets.scan")]
    post = draft(service)
    result = verification.verify(post.id, actor="tester")
    assert result.report["verdict"] == "PROVEN"
    assert result.report["outcome"]["human_approval_required"] is True
    assert result.report["outcome"]["limitations"], "standing limitations are always listed"

    verification.queue.submit_for_review(post.id, actor="tester")
    with pytest.raises(OperationRefused, match="not accepted here"):
        verification.queue.approve(post.id, ref_for(post), actor="tester")
    assert reload(store, post).state is S.READY_FOR_REVIEW


# Blocking paths: no fabricated verdict


def blocked(result, store, post, fragment: str):
    outcome = result.report["outcome"]
    assert not result.eligible and outcome["status"] == BLOCKED
    assert any(fragment in blocker for blocker in outcome["blockers"]), outcome["blockers"]
    assert reload(store, post).verification_ref is None
    return result.report


def test_missing_howlproof_blocks_with_no_verdict(store, service, clock):
    from howlwriter.linkedin.howlproof import HowlProofAdapter

    post = draft(service)
    result = VerificationService(store, HowlProofAdapter(None), clock).verify(post.id, actor="tester")
    report = blocked(result, store, post, "HowlProof did not run")
    assert report["verdict"] is None and report["howlproof"]["executed"] is False
    assert report["howlproof"]["checks"] == [], "no HowlProof check is reported as done"
    assert [r["status"] for r in report["preflight"] if r["id"] == "content.format"] == ["PASSED"]


def test_missing_contract_blocks(store, service, verification, fake):
    (store.root / CONTRACT_FILENAME).unlink()
    post = draft(service)
    report = blocked(verification.verify(post.id, actor="tester"), store, post, CONTRACT_FILENAME)
    assert report["verdict"] is None and fake.commands("evaluate") == []


@pytest.mark.parametrize("code", [2, 3, 4])
def test_howlproof_error_exits_block_with_no_verdict(store, service, verification, fake, code):
    fake.verdict = "INSUFFICIENT_EVIDENCE" if code == 4 else "PROVEN"
    fake.exit_code = code
    post = draft(service)
    fragment = "(exit 4)" if code == 4 else f"HowlProof exited {code}"
    report = blocked(verification.verify(post.id, actor="tester"), store, post, fragment)
    assert report["verdict"] is None and report["howlproof"]["exit_code"] == code


def test_timeout_blocks(store, service, verification, fake):
    fake.raises = TimeoutError("no result after 300 seconds")
    post = draft(service)
    report = blocked(verification.verify(post.id, actor="tester"), store, post, "timed out")
    assert report["verdict"] is None


def test_required_secret_scan_must_have_run_and_passed(store, service, verification, fake):
    fake.verdict = "PROVEN"
    fake.checks = [check("docs.claims.absolutes")]
    post = draft(service)
    blocked(verification.verify(post.id, actor="tester"), store, post, "secrets.scan is absent")

    fake.checks = [check("secrets.scan", "UNAVAILABLE", "could not run")]
    other = draft(service, "A second clean post.")
    blocked(verification.verify(other.id, actor="tester"), store, other, "secrets.scan is UNAVAILABLE")


def test_errored_howlproof_check_blocks_even_under_an_approvable_verdict(store, service, verification, fake):
    fake.checks = [check("secrets.scan"), check("research.claims.bundle", "ERROR", "invalid claim bundle")]
    post = draft(service)
    report = blocked(
        verification.verify(post.id, actor="tester"),
        store,
        post,
        "research.claims.bundle errored",
    )
    assert report["verdict"] == "CONDITIONALLY_PROVEN", "the HowlProof verdict is recorded as given"


def test_howlproof_run_on_a_different_file_set_blocks(store, service, verification, fake):
    fake.tree_digest = "9" * 64
    post = draft(service)
    blocked(verification.verify(post.id, actor="tester"), store, post, "different file set")


def test_bundle_that_fails_its_own_integrity_index_blocks(store, service, verification, fake):
    fake.verdict = "PROVEN"
    fake.corrupt_bundle = True
    post = draft(service)
    report = blocked(verification.verify(post.id, actor="tester"), store, post, "integrity check")
    assert report["verdict"] is None and report["howlproof"]["verdict_unusable"] == "PROVEN"


def test_deterministic_blocker_stops_a_proven_post_without_rewriting_the_verdict(
    store,
    service,
    verification,
    fake,
):
    fake.verdict = "PROVEN"
    fake.checks = [check("secrets.scan")]
    post = draft(service, "We cut build time by 40% using the box at 10.1.2.3.")
    report = blocked(verification.verify(post.id, actor="tester"), store, post, "claims.coverage")
    assert report["verdict"] == "PROVEN"
    assert any("privacy.patterns" in blocker for blocker in report["outcome"]["blockers"])


def test_check_fault_blocks(store, service, verification, monkeypatch):
    from howlwriter.linkedin import content_checks

    def boom(post):
        raise RuntimeError("fault")

    monkeypatch.setattr(content_checks, "check_privacy", boom)
    post = draft(service)
    report = blocked(verification.verify(post.id, actor="tester"), store, post, "privacy.patterns errored")
    assert [r["status"] for r in report["preflight"] if r["id"] == "privacy.patterns"] == ["ERROR"]


# Only executed checks are reported as done


def test_links_are_not_contacted_without_opt_in_and_are_reported_as_not_executed(
    store,
    service,
    verification,
    fake,
):
    post = draft(service, TEXT + "\nhttps://example.com/a", urls=["https://example.com/a"])
    result = verification.verify(post.id, actor="tester")
    assert fake.commands("acquire") == []
    record = next(r for r in result.report["preflight"] if r["id"] == "links.reachability")
    assert record["status"] == "NOT_EXECUTED"
    assert result.report["links"]["results"][0]["status"] == "NOT_CHECKED"
    assert any(
        "links.reachability was not executed" in item for item in result.report["outcome"]["limitations"]
    )
    assert result.eligible, "an unexecuted optional check is a recorded limitation for the approver"


def test_link_results_come_from_howlproof_acquire(store, service, verification, fake):
    urls = [
        "https://example.com/ok",
        "https://example.com/moved",
        "https://example.com/pdf",
        "https://example.com/gone",
    ]
    fake.acquisitions = {
        urls[0]: {},
        urls[1]: {
            "observed_url": "https://other.example.net/landing",
            "redirects": ["https://other.example.net/landing"],
        },
        urls[2]: "content type 'application/pdf' is not an accepted text type",
        urls[3]: f"{urls[3]} returned status 404",
    }
    post = draft(service, TEXT + "\n" + "\n".join(urls), urls=urls)
    result = verification.verify(post.id, actor="tester", allow_network=True)

    assert [argv[-1] for argv in fake.commands("acquire")] == urls
    statuses = [row["status"] for row in result.report["links"]["results"]]
    assert statuses == ["REACHABLE", "REACHABLE", "UNCONFIRMED", "BROKEN"]
    record = next(r for r in result.report["preflight"] if r["id"] == "links.reachability")
    found = {f["code"] for f in record["findings"]}
    assert {"LINK_REDIRECTS_ELSEWHERE", "LINK_UNCONFIRMED", "LINK_BROKEN", "LINK_NOT_EVIDENCE"} <= found
    assert "does not show that the page supports the post" in record["limitation"]
    assert record["method"] == "howlproof acquire"
    assert not result.eligible and any("was not found" in b for b in result.report["outcome"]["blockers"])
    assert [e["role"] for e in result.report["evidence"]] == ["link_acquisition", "link_acquisition"]


# Claims


def write_claims(store, post_id: str, text: str = "Build time fell by 40%") -> None:
    root = store.root / "claims" / post_id
    (root / "evidence").mkdir(parents=True)
    evidence = json.dumps({"id": "e1", "text": "", "facts": {}}).encode()
    (root / "evidence" / "e1.json").write_bytes(evidence)
    bundle = {
        "schema": "howl.claim_bundle/v1",
        "candidate": {"candidate_id": post_id},
        "authorship": {"kind": "EXTERNAL_AUTHORED"},
        "claims": [{"claim_id": "c1", "text": text, "category": "TECHNICAL", "evidence_refs": ["e1"]}],
        "evidence": [
            {
                "id": "e1",
                "path": "evidence/e1.json",
                "sha256": hashlib.sha256(evidence).hexdigest(),
                "source_ref": "https://example.com/source",
            }
        ],
    }
    (root / "claims.json").write_text(json.dumps(bundle), encoding="utf-8")


def claim_check(status: str, claim_status: str, evidence_status: str) -> dict:
    detail = {
        "claim_id": "c1",
        "claim_status": claim_status,
        "explanation": "scripted",
        "assurance": {"evidence_status": evidence_status},
    }
    return check("research.claims.c001", status, "" if status == "VERIFIED" else "scripted", detail)


def test_declared_claims_are_packaged_and_their_real_status_is_reported(store, service, verification, fake):
    post = draft(
        service,
        "We cut build time by 40%. https://example.com/source",
        urls=["https://example.com/source"],
    )
    write_claims(store, post.id)
    fake.checks = [check("secrets.scan"), claim_check("UNAVAILABLE", "INCONCLUSIVE", "UNRESOLVED")]
    result = verification.verify(post.id, actor="tester")

    assert result.eligible
    report = result.report
    assert {"claims.json", "evidence/e1.json"} <= {f["path"] for f in report["package"]["files"]}
    assert [e["path"] for e in report["evidence"]] == [
        f"claims/{post.id}/claims.json",
        f"claims/{post.id}/evidence/e1.json",
    ]
    assert report["claims"] == [
        {
            "claim_id": "c1",
            "check_id": "research.claims.c001",
            "check_status": "UNAVAILABLE",
            "claim_status": "INCONCLUSIVE",
            "evidence_status": "UNRESOLVED",
            "explanation": "scripted",
        }
    ]
    assert any("claim c1 is INCONCLUSIVE, not supported" in item for item in report["outcome"]["limitations"])
    assert report["links"]["results"][0]["cited_by_claims"] == ["c1"]


def test_supported_claim_without_a_verified_source_is_flagged(store, service, verification, fake):
    post = draft(service, "We cut build time by 40%.")
    write_claims(store, post.id)
    fake.verdict = "PROVEN"
    fake.checks = [check("secrets.scan"), claim_check("VERIFIED", "SUPPORTED", "DETERMINISTIC_CHECK_ONLY")]
    limitations = verification.verify(post.id, actor="tester").report["outcome"]["limitations"]
    assert any(
        "DETERMINISTIC_CHECK_ONLY" in item and "not verified against an acquired source" in item
        for item in limitations
    )


def test_unsafe_claims_directory_content_blocks(store, service, verification, fake, tmp_path):
    post = draft(service)
    root = store.root / "claims" / post.id
    root.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    (root / "post.txt").write_text("override attempt", encoding="utf-8")
    report = blocked(verification.verify(post.id, actor="tester"), store, post, "not a regular file")
    assert any("reserved name" in blocker for blocker in report["outcome"]["blockers"])
    assert {f["path"] for f in report["package"]["files"]} == {"post.txt", "post.json"}


# Lifecycle effects


def scheduled(store, clock, verification, text: str = TEXT):
    """A scheduled post whose verification is a real report from the scripted run."""
    from tests.linkedin.helpers import AcceptAllVerifier

    trusting = QueueService(store, clock, verifier=AcceptAllVerifier())
    post = trusting.add_draft(title="Scheduled", text=text, actor="tester", scheduled_date="2026-11-20")
    assert verification.verify(post.id, actor="tester").eligible
    trusting.submit_for_review(post.id, actor="tester")
    trusting.approve(post.id, ref_for(post), actor="tester")
    return trusting.schedule(post.id, actor="tester")


def test_blocked_verification_removes_an_earlier_report_from_a_draft(store, service, verification, fake):
    post = draft(service)
    assert verification.verify(post.id, actor="tester").eligible
    fake.verdict = "REJECT"
    result = verification.verify(post.id, actor="tester")
    stored = reload(store, post)
    assert not result.eligible and stored.verification_ref is None and stored.state is S.DRAFT
    assert stored.history[-1].action == "verification_blocked"
    assert result.report_path in stored.history[-1].detail


def test_revalidation_of_a_scheduled_post_keeps_its_approval(store, clock, verification, fake):
    post = scheduled(store, clock, verification)
    first = reload(store, post).verification_ref
    clock.advance(days=3)
    result = verification.verify(post.id, actor="tester")
    stored = reload(store, post)
    assert result.eligible and stored.state is S.SCHEDULED and stored.approval_ref is not None
    assert stored.verification_ref != first and stored.history[-1].action == "verification_refreshed"


@pytest.mark.parametrize("change", ["reject", "weaker"])
def test_failed_or_weaker_revalidation_withdraws_a_scheduled_post(store, clock, verification, fake, change):
    post = scheduled(store, clock, verification)
    fake.verdict = "REJECT" if change == "reject" else "REQUIRES_HUMAN"
    result = verification.verify(post.id, actor="tester")
    stored = reload(store, post)
    assert not result.eligible and not result.attached
    assert stored.state is S.DRAFT and stored.approval_ref is None and stored.verification_ref is None
    assert stored.history[-1].action == "verification_blocked"
    assert "\n" not in stored.history[-1].detail
    if change == "weaker":
        assert result.report["outcome"]["status"] == ELIGIBLE and "weakened" in result.withdrawn_reason
        assert "weakened from CONDITIONALLY_PROVEN to REQUIRES_HUMAN" in stored.history[-1].detail


def test_published_and_archived_posts_cannot_be_verified(store, service, verification, fake):
    post = draft(service)
    service.archive(post.id, actor="tester")
    with pytest.raises(OperationRefused):
        verification.verify(post.id, actor="tester")
    assert fake.commands("evaluate") == []


def test_content_edit_discards_the_verification(store, service, verification):
    post = draft(service)
    verification.verify(post.id, actor="tester")
    service.update_content(post.id, actor="tester", text="Different text entirely.")
    assert reload(store, post).verification_ref is None


# Verifier: forged and stale reports


def test_report_edited_after_attachment_is_rejected(store, service, verification):
    post = draft(service)
    verification.verify(post.id, actor="tester")
    stored = reload(store, post)
    path = store.artifact_file(stored.verification_ref.path)
    path.write_bytes(path.read_bytes().replace(b"CONDITIONALLY_PROVEN", b"PROVEN"))
    assert ReportVerifier(store).problems("verification", stored, stored.verification_ref) == [
        "the verification report was changed after it was attached"
    ]


def test_blocked_report_cannot_be_attached_by_editing_its_outcome(store, service, verification, fake):
    post = draft(service)
    verification.verify(post.id, actor="tester")
    good_ref = reload(store, post).verification_ref
    fake.verdict = "REJECT"
    blocked_path = verification.verify(post.id, actor="tester").report_path

    path = store.artifact_file(blocked_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    report["outcome"] = {**report["outcome"], "status": ELIGIBLE, "blockers": []}
    payload = json.dumps(report).encode()
    path.write_bytes(payload)
    forged = ArtifactRef(blocked_path, hashlib.sha256(payload).hexdigest(), good_ref.content_fingerprint)

    problems = ReportVerifier(store).problems("verification", reload(store, post), forged)
    assert "the report's stated outcome does not follow from its recorded checks" in problems
    with pytest.raises(OperationRefused):
        verification.queue.attach_verification(post.id, forged, actor="attacker")
    assert reload(store, post).verification_ref is None


def test_verdict_upgraded_inside_the_report_is_caught_by_the_sealed_bundle(store, service, verification):
    post = draft(service)
    verification.verify(post.id, actor="tester")

    def upgrade(report):
        report["verdict"] = report["howlproof"]["verdict"] = "PROVEN"
        report["howlproof"]["rationale"] = []
        report["outcome"] = derive_outcome(report)

    forged = rewrite_report(store, post, upgrade)
    assert ReportVerifier(store).problems("verification", reload(store, post), forged) == [
        "the HowlProof bundle records a different verdict than the report"
    ]


@pytest.mark.parametrize("damage", ["edit", "delete", "add", "missing"])
def test_tampered_or_missing_howlproof_bundle_is_rejected(store, service, verification, damage):
    post = draft(service)
    report = verification.verify(post.id, actor="tester").report
    bundle = store.root / report["howlproof"]["bundle_path"]
    if damage == "edit":
        (bundle / "result.json").write_text("{}", encoding="utf-8")
    elif damage == "delete":
        (bundle / "checks.jsonl").unlink()
    elif damage == "add":
        (bundle / "extra.txt").write_text("x", encoding="utf-8")
    else:
        import shutil

        shutil.rmtree(bundle)
    stored = reload(store, post)
    assert ReportVerifier(store).problems("verification", stored, stored.verification_ref)


@pytest.mark.parametrize(
    "path",
    [
        "verification/other-post/report.json",
        "posts/x.json",
        "verification/{id}/../x.json",
        "verification/{id}/a/b.json",
    ],
)
def test_reference_outside_the_posts_own_report_directory_is_rejected(store, service, verification, path):
    post = draft(service)
    verification.verify(post.id, actor="tester")
    stored = reload(store, post)
    ref = ArtifactRef(path.format(id=post.id), stored.verification_ref.sha256, stored.computed_fingerprint())
    problems = ReportVerifier(store).problems("verification", stored, ref)
    assert problems and "must be a file under" in problems[0]


def test_report_of_another_post_or_other_content_is_rejected(store, service, verification):
    first = draft(service)
    second = draft(service, "A different clean post.")
    verification.verify(first.id, actor="tester")
    verification.verify(second.id, actor="tester")
    stolen = reload(store, first).verification_ref
    target = reload(store, second)

    source = store.artifact_file(stolen.path)
    copy = f"verification/{second.id}/copied.json"
    store.artifact_file(copy).write_bytes(source.read_bytes())
    ref = ArtifactRef(copy, stolen.sha256, target.computed_fingerprint())
    problems = ReportVerifier(store).problems("verification", target, ref)
    assert "the verification report belongs to a different post" in problems
    assert "the verification report was made for different content" in problems


def test_claims_or_media_changed_after_verification_invalidate_it(store, service, verification, fake):
    post = draft(service, "We cut build time by 40%.")
    write_claims(store, post.id)
    verification.verify(post.id, actor="tester")
    stored = reload(store, post)
    assert ReportVerifier(store).problems("verification", stored, stored.verification_ref) == []

    (store.root / "claims" / post.id / "evidence" / "e1.json").write_text(
        '{"swapped": true}',
        encoding="utf-8",
    )
    problems = ReportVerifier(store).problems("verification", stored, stored.verification_ref)
    assert problems == [
        "the post's media, claims or evidence files changed since verification; verify the post again",
    ]


def test_verifier_still_refuses_approval_artifacts(store, service, verification):
    post = draft(service)
    assert "not accepted here" in ReportVerifier(store).problems("approval", post, ref_for(post))[0]


# Publish gate


def test_gate_accepts_a_recent_genuine_report_and_blocks_without_one(store, service, verification, clock):
    post = draft(service)
    gate = VerificationGate(store, clock)
    assert gate.blockers(post) == ["no verification report is attached"]
    verification.verify(post.id, actor="tester")
    assert gate.blockers(reload(store, post)) == []


def test_gate_requires_revalidation_after_the_configured_age(store, service, verification, clock):
    post = draft(service)
    verification.verify(post.id, actor="tester")
    stored = reload(store, post)
    gate = VerificationGate(store, clock)
    clock.advance(days=7)
    assert gate.blockers(stored) == []
    clock.advance(minutes=1)
    assert "verify the post again" in gate.blockers(stored)[0]
    clock.set("2026-11-15T12:00:00Z")
    assert "dated in the future" in gate.blockers(stored)[0]


def test_gate_rechecks_evidence_and_the_coordinator_stays_closed_without_an_approval_gate(
    store, clock, verification
):
    from tests.linkedin.helpers import FakeTransport, go_live, make_coordinator

    post = scheduled(store, clock, verification)
    go_live(store)
    clock.set("2026-11-20T13:30:00Z")
    gate = VerificationGate(store, clock)
    assert gate.blockers(reload(store, post)) == []

    report = json.loads(
        store.artifact_file(reload(store, post).verification_ref.path).read_text(encoding="utf-8"),
    )
    (store.root / report["howlproof"]["bundle_path"] / "target.json").write_text("{}", encoding="utf-8")
    transport = FakeTransport()
    outcome = make_coordinator(store, clock, transport, gates=[gate]).run()
    assert transport.calls == [] and outcome.outcome.value == "BLOCKED"
    assert reload(store, post).state is S.SCHEDULED


# Command line


def test_init_writes_the_operator_contract_once(tmp_path, capsys):
    repo = tmp_path / "repo"
    assert main(["linkedin", "--repo", str(repo), "init"]) == 0
    assert (repo / CONTRACT_FILENAME).read_text(encoding="utf-8") == DEFAULT_CONTRACT
    (repo / CONTRACT_FILENAME).write_text("edited by the operator\n", encoding="utf-8")
    assert main(["linkedin", "--repo", str(repo), "init"]) == 0
    assert (repo / CONTRACT_FILENAME).read_text(encoding="utf-8") == "edited by the operator\n"
    capsys.readouterr()


def test_verify_command_without_howlproof_exits_nonzero_and_reports_no_verdict(tmp_path, capsys):
    repo = tmp_path / "repo"
    text = tmp_path / "post.txt"
    text.write_text(TEXT, encoding="utf-8")
    assert main(["linkedin", "--repo", str(repo), "init"]) == 0
    add = ["linkedin", "--repo", str(repo), "add", "--title", "T", "--text-file", str(text), "--json"]
    assert main(add) == 0
    post_id = json.loads(capsys.readouterr().out.split("\n", 3)[-1])["id"]

    absent = str(tmp_path / "no-howlproof")
    code = main(["linkedin", "--repo", str(repo), "verify", post_id, "--howlproof", absent, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1 and payload["eligible"] is False and payload["report"]["verdict"] is None
    assert (repo / payload["report_path"]).is_file()

    assert main(["linkedin", "--repo", str(repo), "verify", post_id, "--howlproof", absent]) == 1
    text_out = capsys.readouterr().out
    assert "HowlProof verdict none" in text_out and "Blocked." in text_out
