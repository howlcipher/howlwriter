"""Human approval boundary: the trusted path works, and every bypass and forgery is refused.

GitHub is not contacted. The workflow identity is a dictionary shaped like the
variables GitHub sets for a run, so these tests prove HowlWriter's decisions for
each identity, not that GitHub sets those variables as documented. HowlProof is
the scripted stand-in from ``proof_fakes``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from importlib import resources
from pathlib import Path

import pytest
import yaml

from howlwriter.cli.main import main
from howlwriter.linkedin import approval as ap
from howlwriter.linkedin.config import ConfigError, parse_config, CONFIG_SCHEMA
from howlwriter.linkedin.models import ArtifactRef, LifecycleState
from howlwriter.linkedin.service import OperationRefused, QueueService
from howlwriter.linkedin.verification import CONTRACT_FILENAME, DEFAULT_CONTRACT, VerificationService
from tests.linkedin.helpers import FakeTransport, go_live, make_coordinator
from tests.linkedin.proof_fakes import FakeHowlProof

S = LifecycleState
KEY = "test-only-approval-key-0123456789-abcdefghijklmnopqrstuvwxyz"
OTHER_KEY = "another-test-only-key-9876543210-zyxwvutsrqponmlkjihgfedcba"
OWNER_ID = "1001"
TEXT = "Shipping small changes every day keeps reviews short.\n\nWhat has worked for your team?"
DUE = "2026-11-20T13:30:00Z"  # 08:30 in America/Detroit on the scheduled day


def actions_env(**changes: str | None) -> dict[str, str]:
    """The environment of a first-attempt manual dispatch of the approval workflow by the owner."""
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR_ID": OWNER_ID,
        "GITHUB_ACTOR": "owner",
        "GITHUB_TRIGGERING_ACTOR": "owner",
        "GITHUB_REPOSITORY": "owner/posts",
        "GITHUB_REPOSITORY_ID": "5005",
        "GITHUB_RUN_ID": "777",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": "owner/posts/.github/workflows/linkedin-approve.yml@refs/heads/main",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "c" * 40,
        ap.KEY_ENV: KEY,
        ap.APPROVER_ENV: OWNER_ID,
    }
    for name, value in changes.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def publish_env(**changes: str | None) -> dict[str, str]:
    """What a publishing run holds: the key and the trusted ID, no approval identity needed."""
    return actions_env(GITHUB_EVENT_NAME="schedule", **changes)


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


@pytest.fixture
def approvals(store, clock):
    return ap.ApprovalService(store, actions_env(), clock)


def ready(service, verification, text: str = TEXT, date: str | None = "2026-11-20"):
    post = service.add_draft(title="A post", text=text, actor="tester", scheduled_date=date)
    assert verification.verify(post.id, actor="tester").eligible
    return service.submit_for_review(post.id, actor="tester")


def approve(approvals, post_id: str):
    review = approvals.review(post_id)
    assert review["approvable"], review["blockers"]
    return approvals.approve(
        post_id,
        fingerprint=review["content_fingerprint"],
        accepted_limitations_digest=review["limitations_digest"],
    )


def approved_and_scheduled(service, verification, approvals):
    post = ready(service, verification)
    approve(approvals, post.id)
    return approvals.queue.schedule(post.id, actor="tester")


def gate_blockers(store, clock, post_id: str, env: dict[str, str] | None = None) -> list[str]:
    trust = ap.TrustSettings.from_environment(publish_env() if env is None else env)
    post = store.load_post(post_id)
    return [reason for gate in ap.publish_gates(store, trust, clock) for reason in gate.blockers(post)]


def record_of(store, post_id: str) -> tuple[Path, dict]:
    path = store.artifact_file(store.load_post(post_id).approval_ref.path)
    return path, json.loads(path.read_text(encoding="utf-8"))


def hand_edit(store, post_id: str, mutate) -> None:
    """Change the post file directly, as someone with write access to the repository could."""
    path = store.post_path(post_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def repoint(store, post_id: str, path: str, payload: bytes) -> None:
    def mutate(data):
        data["approval_ref"] = {
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content_fingerprint": data["content_fingerprint"],
        }

    hand_edit(store, post_id, mutate)


def schema(name: str):
    jsonschema = pytest.importorskip("jsonschema")
    document = json.loads(resources.files("howlwriter.schemas").joinpath(name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(document)
    return jsonschema.Draft202012Validator(document)


# The trusted path


def test_owner_dispatch_records_an_approval_that_names_everything_it_covers(
    store, service, verification, approvals, clock
):
    post = ready(service, verification)
    review = approvals.review(post.id)
    approved = approve(approvals, post.id)
    assert approved.state is S.APPROVED and approved.history[-1].actor == "github:owner#1001"

    path, record = record_of(store, post.id)
    assert path.parent == store.root / "approvals" / post.id
    assert record["content_fingerprint"] == post.computed_fingerprint()
    assert record["verification"]["path"] == post.verification_ref.path
    assert record["verification"]["sha256"] == post.verification_ref.sha256
    assert record["verification"]["verdict"] == "CONDITIONALLY_PROVEN"
    assert record["accepted_limitations"] == review["limitations"] and review["limitations"]
    assert record["actor"] == {"id": OWNER_ID, "login": "owner"}
    assert record["workflow"]["run_id"] == "777" and record["workflow"]["event"] == "workflow_dispatch"
    assert record["schedule"] == {"date": "2026-11-20", "time": None}
    assert record["approved_at"] == "2026-11-16T12:00:00Z"
    assert record["authentication"]["method"] == "hmac-sha256"
    assert KEY not in path.read_text(encoding="utf-8")
    assert ap.approval_record_problems(record) == []

    approvals.queue.schedule(post.id, actor="tester")
    assert gate_blockers(store, clock, post.id) == []


def test_records_match_the_published_schemas(store, service, verification, approvals):
    post = approved_and_scheduled(service, verification, approvals)
    approvals.authorize_schedule(post.id, new_date="2026-11-23")
    directory = store.root / "approvals" / post.id
    files = sorted(directory.iterdir())
    assert len(files) == 2
    for file in files:
        name = (
            "howlwriter.linkedin_schedule_authorization.v1.schema.json"
            if file.name.startswith("schedule-")
            else "howlwriter.linkedin_approval.v1.schema.json"
        )
        errors = list(schema(name).iter_errors(json.loads(file.read_text(encoding="utf-8"))))
        assert not errors, errors


def test_proven_post_is_not_approved_until_the_human_approves(store, service, verification, fake, clock):
    fake.verdict = "PROVEN"
    post = ready(service, verification)
    assert store.load_post(post.id).state is S.READY_FOR_REVIEW
    assert gate_blockers(store, clock, post.id) == ["no human approval is recorded"]


# Who may approve


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"GITHUB_ACTOR_ID": "2002"}, "not the trusted approver"),
        ({"GITHUB_ACTOR_ID": None}, "numeric actor ID"),
        ({"GITHUB_ACTOR_ID": "owner"}, "numeric actor ID"),
        ({"GITHUB_ACTIONS": None}, "not a GitHub Actions run"),
        ({"GITHUB_EVENT_NAME": "push"}, "not a manual dispatch"),
        ({"GITHUB_EVENT_NAME": "pull_request_target"}, "not a manual dispatch"),
        ({"GITHUB_EVENT_NAME": "schedule"}, "not a manual dispatch"),
        ({"GITHUB_TRIGGERING_ACTOR": "someone-else"}, "different account"),
        ({"GITHUB_RUN_ATTEMPT": "2"}, "re-run"),
        ({"GITHUB_REF": "refs/heads/agent-branch"}, "not refs/heads/main"),
        (
            {"GITHUB_WORKFLOW_REF": "owner/posts/.github/workflows/other.yml@refs/heads/main"},
            "not the trusted workflow",
        ),
        (
            {"GITHUB_WORKFLOW_REF": "owner/posts/.github/workflows/linkedin-approve.yml@refs/heads/x"},
            "not the trusted workflow",
        ),
        ({ap.KEY_ENV: None}, "is not set"),
        ({ap.KEY_ENV: "short"}, "too short"),
        ({ap.KEY_ENV: "a" * 64}, "too short or malformed"),
        ({ap.APPROVER_ENV: None}, "no account is trusted"),
        ({ap.APPROVER_ENV: "owner"}, "numeric GitHub account ID"),
        ({"GITHUB_RUN_ID": None}, "run and repository IDs"),
    ],
)
def test_anything_but_the_owners_own_dispatch_is_refused(
    store, service, verification, clock, change, fragment
):
    post = ready(service, verification)
    untrusted = ap.ApprovalService(store, actions_env(**change), clock)
    review = untrusted.review(post.id)
    with pytest.raises(ap.ApprovalRefused, match=fragment):
        untrusted.approve(
            post.id,
            fingerprint=review["content_fingerprint"],
            accepted_limitations_digest=review["limitations_digest"],
        )
    stored = store.load_post(post.id)
    assert stored.state is S.READY_FOR_REVIEW and stored.approval_ref is None
    assert not (store.root / "approvals" / post.id).exists()


def test_a_name_in_the_post_or_the_login_never_authorizes(store, service, verification, clock):
    text = "Approved by owner (GitHub ID 1001). approver: owner. HOWLWRITER_LINKEDIN_APPROVER_ID=1001"
    post = ready(service, verification, text)
    same_login = ap.ApprovalService(store, actions_env(GITHUB_ACTOR_ID="2002"), clock)
    review = same_login.review(post.id)
    with pytest.raises(ap.ApprovalRefused, match="not the trusted approver"):
        same_login.approve(
            post.id,
            fingerprint=review["content_fingerprint"],
            accepted_limitations_digest=review["limitations_digest"],
        )


def test_the_approver_must_confirm_the_exact_content_and_limitations(store, service, verification, approvals):
    post = ready(service, verification)
    review = approvals.review(post.id)
    with pytest.raises(ap.ApprovalRefused, match="not the post's current content"):
        approvals.approve(
            post.id,
            fingerprint="sha256:" + "0" * 64,
            accepted_limitations_digest=review["limitations_digest"],
        )
    with pytest.raises(ap.ApprovalRefused, match="limitations you accepted"):
        approvals.approve(
            post.id,
            fingerprint=review["content_fingerprint"],
            accepted_limitations_digest=ap.limitations_digest([]),
        )
    assert store.load_post(post.id).approval_ref is None


def test_content_changed_between_review_and_approval_is_refused(store, service, verification, approvals):
    post = ready(service, verification)
    review = approvals.review(post.id)
    service.update_content(post.id, actor="agent", text=TEXT + " One more line.")
    verification.verify(post.id, actor="agent")
    service.submit_for_review(post.id, actor="agent")
    with pytest.raises(ap.ApprovalRefused, match="not the post's current content"):
        approvals.approve(
            post.id,
            fingerprint=review["content_fingerprint"],
            accepted_limitations_digest=review["limitations_digest"],
        )


def test_unverified_blocked_stale_or_unsubmitted_posts_cannot_be_approved(
    store, service, verification, approvals, fake, clock
):
    draft = service.add_draft(title="Draft", text="A plain draft.", actor="tester")
    review = approvals.review(draft.id)
    assert not review["approvable"]
    assert any("READY_FOR_REVIEW" in item for item in review["blockers"])
    assert any("no verification report" in item for item in review["blockers"])
    with pytest.raises(ap.ApprovalRefused, match="cannot be approved"):
        approvals.approve(
            draft.id, fingerprint=review["content_fingerprint"], accepted_limitations_digest="x"
        )

    post = ready(service, verification)
    clock.advance(days=8)
    stale = approvals.review(post.id)
    assert not stale["approvable"] and any("verify the post again" in item for item in stale["blockers"])


# Forged and altered records


def test_record_signed_with_another_key_is_rejected_everywhere(
    store, service, verification, approvals, clock
):
    post = ready(service, verification)
    review = approvals.review(post.id)
    forger = ap.ApprovalService(store, actions_env(**{ap.KEY_ENV: OTHER_KEY}), clock)
    forger.approve(
        post.id,
        fingerprint=review["content_fingerprint"],
        accepted_limitations_digest=review["limitations_digest"],
    )
    # The forger's own process accepted its record, so the post file says APPROVED...
    forger.queue.schedule(post.id, actor="forger")
    assert store.load_post(post.id).state is S.SCHEDULED
    # ...but nothing that holds the real key accepts it.
    assert gate_blockers(store, clock, post.id) == [
        "the record was made with a different approval key (rotated or foreign)"
    ]
    go_live(store)
    clock.set(DUE)
    transport = FakeTransport()
    trust = ap.TrustSettings.from_environment(publish_env())
    outcome = make_coordinator(store, clock, transport, gates=ap.publish_gates(store, trust, clock)).run()
    assert outcome.outcome.value == "BLOCKED" and transport.calls == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record["actor"].update(id="2002"),
        lambda record: record.update(content_fingerprint="sha256:" + "0" * 64),
        lambda record: record.update(accepted_limitations=[]),
        lambda record: record["schedule"].update(date="2026-11-18"),
        lambda record: record["verification"].update(verdict="PROVEN"),
        lambda record: record["workflow"].update(run_id="1"),
        lambda record: record.update(approved_at="2026-11-16T12:00:01Z"),
        lambda record: record["authentication"].update(mac="0" * 64),
    ],
)
def test_any_edit_to_a_genuine_record_breaks_its_authentication(
    store, service, verification, approvals, clock, mutate
):
    post = approved_and_scheduled(service, verification, approvals)
    path, record = record_of(store, post.id)
    mutate(record)
    payload = json.dumps(record).encode()
    path.write_bytes(payload)
    assert gate_blockers(store, clock, post.id) == ["approval: the record was changed after it was attached"]
    repoint(store, post.id, store.load_post(post.id).approval_ref.path, payload)
    assert gate_blockers(store, clock, post.id) == [
        "the record's authentication code is wrong: it was forged or changed"
    ]


def test_post_file_edited_to_say_approved_does_not_publish(store, service, verification, clock):
    post = ready(service, verification)
    fabricated = {
        "schema": ap.APPROVAL_SCHEMA,
        "approved_by": "owner",
        "actor": {"id": OWNER_ID, "login": "owner"},
    }
    payload = json.dumps(fabricated).encode()
    target = store.root / "approvals" / post.id / "made-up.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    repoint(store, post.id, f"approvals/{post.id}/made-up.json", payload)
    hand_edit(store, post.id, lambda data: data.update(state="SCHEDULED"))
    assert store.load_post(post.id).state is S.SCHEDULED
    blockers = gate_blockers(store, clock, post.id)
    assert len(blockers) == 1 and "malformed" in blockers[0]

    go_live(store)
    clock.set(DUE)
    transport = FakeTransport()
    trust = ap.TrustSettings.from_environment(publish_env())
    outcome = make_coordinator(store, clock, transport, gates=ap.publish_gates(store, trust, clock)).run()
    assert outcome.outcome.value == "BLOCKED" and transport.calls == []


def test_genuine_approval_cannot_be_moved_to_another_post_or_path(
    store, service, verification, approvals, clock
):
    first = approved_and_scheduled(service, verification, approvals)
    second = ready(service, verification, "A different post about code review habits.", "2026-11-21")
    path, _record = record_of(store, first.id)
    payload = path.read_bytes()

    copied = store.root / "approvals" / second.id / path.name
    copied.parent.mkdir(parents=True)
    copied.write_bytes(payload)
    repoint(store, second.id, f"approvals/{second.id}/{path.name}", payload)
    hand_edit(store, second.id, lambda data: data.update(state="SCHEDULED"))
    blockers = gate_blockers(store, clock, second.id)
    assert "the approval belongs to a different post" in blockers
    assert "the approval was given for different content" in blockers

    for elsewhere in (f"approvals/{first.id}/{path.name}", "approvals/loose.json", f"posts/{second.id}.json"):
        repoint(store, second.id, elsewhere, payload)
        assert "must be a file under" in gate_blockers(store, clock, second.id)[0]


def test_schedule_record_cannot_stand_in_for_an_approval(store, service, verification, approvals, clock):
    post = approved_and_scheduled(service, verification, approvals)
    approvals.authorize_schedule(post.id, new_date="2026-11-23")
    directory = store.root / "approvals" / post.id
    name = next(p.name for p in directory.iterdir() if p.name.startswith("schedule-"))
    payload = (store.root / "approvals" / post.id / name).read_bytes()
    repoint(store, post.id, f"approvals/{post.id}/{name}", payload)
    assert "must be a file under" in gate_blockers(store, clock, post.id)[0]


def test_without_the_key_nothing_is_reported_as_authenticated(store, service, verification, approvals, clock):
    post = approved_and_scheduled(service, verification, approvals)
    blockers = gate_blockers(store, clock, post.id, publish_env(**{ap.KEY_ENV: None}))
    assert len(blockers) == 1 and "cannot be authenticated" in blockers[0]
    wrong_owner = gate_blockers(store, clock, post.id, publish_env(**{ap.APPROVER_ENV: "2002"}))
    assert wrong_owner == ["the record was made for an account that is not the trusted approver"]
    other_repo = gate_blockers(store, clock, post.id, publish_env(GITHUB_REPOSITORY_ID="6006"))
    assert other_repo == ["the record was made in a different repository"]


def test_service_refuses_to_attach_an_approval_the_verifier_rejects(store, service, verification, approvals):
    post = ready(service, verification)
    other = ready(service, verification, "A different post about code review habits.", "2026-11-21")
    approve(approvals, other.id)
    stolen = store.load_post(other.id).approval_ref
    with pytest.raises(OperationRefused):
        approvals.queue.approve(
            post.id,
            ArtifactRef(stolen.path, stolen.sha256, post.computed_fingerprint()),
            actor="agent",
        )
    with pytest.raises(OperationRefused, match="no trusted verifier"):
        QueueService(store).approve(
            post.id, ArtifactRef(stolen.path, stolen.sha256, post.computed_fingerprint()), actor="agent"
        )
    assert store.load_post(post.id).state is S.READY_FOR_REVIEW


# Content changes


def test_editing_through_the_product_discards_the_approval(store, service, verification, approvals):
    post = approved_and_scheduled(service, verification, approvals)
    edited = service.update_content(post.id, actor="agent", text=TEXT + " Edited.")
    assert edited.state is S.DRAFT and edited.approval_ref is None and edited.verification_ref is None


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(text=data["text"] + " Slipped in after approval."),
        lambda data: data.update(urls=["https://example.com/added-later"]),
    ],
)
def test_content_changed_by_hand_after_approval_is_blocked(
    store, service, verification, approvals, clock, change
):
    from howlwriter.linkedin.models import Post

    post = approved_and_scheduled(service, verification, approvals)

    def mutate(data):
        change(data)
        # A careful attacker also updates every stored fingerprint so the file stays consistent.
        fresh = Post.from_dict({**data, "content_fingerprint": "sha256:" + "0" * 64}).computed_fingerprint()
        data["content_fingerprint"] = fresh
        data["approval_ref"]["content_fingerprint"] = fresh
        data["verification_ref"]["content_fingerprint"] = fresh

    hand_edit(store, post.id, mutate)
    blockers = gate_blockers(store, clock, post.id)
    assert "the approval was given for different content" in blockers
    assert "the verification report was made for different content" in blockers


def test_restoring_withdrawn_approved_content_by_hand_is_a_known_limit(
    store, service, verification, approvals, clock
):
    """Documented limit (THREAT_MODEL): withdrawing an approval is repository state, not cryptography.

    Someone with write access can put back the exact content, report and record the
    owner approved. They cannot change the content or the day. Rotating the key is
    the only hard revocation.
    """
    post = approved_and_scheduled(service, verification, approvals)
    before = store.post_path(post.id).read_text(encoding="utf-8")
    service.return_to_draft(post.id, actor="owner")
    assert gate_blockers(store, clock, post.id)[0] == "no verification report is attached"
    store.post_path(post.id).write_text(before, encoding="utf-8")
    assert gate_blockers(store, clock, post.id) == []
    rotated = publish_env(**{ap.KEY_ENV: OTHER_KEY})
    assert "different approval key" in gate_blockers(store, clock, post.id, rotated)[0]


# Schedule changes


def test_schedule_change_keeps_approval_but_needs_its_own_authorization(
    store, service, verification, approvals, clock
):
    post = approved_and_scheduled(service, verification, approvals)
    moved = service.reschedule(post.id, actor="agent", new_date="2026-11-18")
    assert moved.state is S.SCHEDULED and moved.approval_is_current and moved.verification_is_current
    blockers = gate_blockers(store, clock, post.id)
    assert len(blockers) == 1 and "schedule 2026-11-18 default time was not authorized" in blockers[0]

    authorized = approvals.authorize_schedule(post.id, new_date="2026-11-23", new_time="09:00")
    assert authorized.scheduled_date == "2026-11-23" and authorized.scheduled_time == "09:00"
    assert authorized.approval_ref == post.approval_ref
    assert authorized.verification_ref == post.verification_ref
    assert authorized.history[-1].action == "rescheduled"
    assert authorized.history[-1].actor == "github:owner#1001"
    assert gate_blockers(store, clock, post.id) == []

    service.reschedule(post.id, actor="agent", new_date="2026-11-24")
    assert "was not authorized" in gate_blockers(store, clock, post.id)[0]
    service.reschedule(post.id, actor="agent", new_date="2026-11-20", new_time="default")
    assert gate_blockers(store, clock, post.id) == [], "the originally approved slot stays authorized"


def test_schedule_authorization_needs_the_trusted_run_and_a_valid_approval(
    store, service, verification, approvals, clock
):
    post = approved_and_scheduled(service, verification, approvals)
    outsider = ap.ApprovalService(store, actions_env(GITHUB_ACTOR_ID="2002"), clock)
    with pytest.raises(ap.ApprovalRefused, match="not the trusted approver"):
        outsider.authorize_schedule(post.id, new_date="2026-11-23")
    assert store.load_post(post.id).scheduled_date == "2026-11-20"

    unapproved = ready(service, verification, "A different post about code review habits.", "2026-11-21")
    with pytest.raises(ap.ApprovalRefused, match="no approval"):
        approvals.authorize_schedule(unapproved.id, new_date="2026-11-25")
    with pytest.raises(OperationRefused, match="already holds"):
        approvals.authorize_schedule(post.id, new_date="2026-11-21")


def test_forged_or_borrowed_schedule_authorizations_are_ignored(
    store, service, verification, approvals, clock
):
    post = approved_and_scheduled(service, verification, approvals)
    forger = ap.ApprovalService(store, actions_env(**{ap.KEY_ENV: OTHER_KEY}), clock)
    with pytest.raises(ap.ApprovalRefused, match="different approval key"):
        forger.authorize_schedule(post.id, new_date="2026-11-23")

    approvals.authorize_schedule(post.id, new_date="2026-11-23")
    directory = store.root / "approvals" / post.id
    name = next(p.name for p in directory.iterdir() if p.name.startswith("schedule-"))
    record = json.loads((directory / name).read_text(encoding="utf-8"))
    record["schedule"]["date"] = "2026-11-25"
    (directory / "schedule-99999999T000000Z.json").write_text(json.dumps(record), encoding="utf-8")
    forged = ap.sign({k: v for k, v in record.items() if k != "authentication"}, OTHER_KEY.encode())
    (directory / "schedule-99999999T000001Z.json").write_text(json.dumps(forged), encoding="utf-8")
    (directory / "schedule-99999999T000002Z.json").write_text("not json", encoding="utf-8")
    service.reschedule(post.id, actor="agent", new_date="2026-11-25")
    assert "was not authorized" in gate_blockers(store, clock, post.id)[0]


def test_post_approved_without_a_date_needs_the_date_authorized(
    store, service, verification, approvals, clock
):
    post = ready(service, verification, date=None)
    approve(approvals, post.id)
    service.reschedule(post.id, actor="agent", new_date="2026-11-20")
    approvals.queue.schedule(post.id, actor="agent")
    assert "was not authorized" in gate_blockers(store, clock, post.id)[0]
    approvals.authorize_schedule(post.id, new_date=None)
    assert gate_blockers(store, clock, post.id) == []


# Verification refreshed after approval, and age


def test_refreshed_report_with_nothing_new_keeps_the_approval(store, service, verification, approvals, clock):
    post = approved_and_scheduled(service, verification, approvals)
    clock.advance(days=3)
    assert verification.verify(post.id, actor="tester").eligible
    refreshed = store.load_post(post.id)
    assert refreshed.verification_ref != post.verification_ref and refreshed.state is S.SCHEDULED
    assert gate_blockers(store, clock, post.id) == []


def test_refreshed_report_with_a_new_limitation_needs_a_new_approval(
    store, service, verification, approvals, fake, clock
):
    post = approved_and_scheduled(service, verification, approvals)
    scheduled = store.load_post(post.id)
    fake.limitations = fake.limitations + ["a source the post relies on could not be re-read"]
    result = verification.verify(post.id, actor="tester")
    assert not result.eligible and "did not accept" in result.withdrawn_reason
    assert store.load_post(post.id).state is S.DRAFT and store.load_post(post.id).approval_ref is None

    # Someone re-attaches the old approval to the new report by hand: the gate still refuses.
    new_report = store.artifact_file(result.report_path).read_bytes()
    store.save_post(
        replace(
            scheduled,
            verification_ref=ArtifactRef(
                result.report_path, hashlib.sha256(new_report).hexdigest(), scheduled.computed_fingerprint()
            ),
        ),
        expected_revision=store.load_post(post.id).revision,
    )
    blockers = gate_blockers(store, clock, post.id)
    assert len(blockers) == 1 and "the approver never accepted" in blockers[0]


def test_weaker_verdict_reattached_by_hand_needs_a_new_approval(
    store, service, verification, approvals, fake, clock
):
    post = approved_and_scheduled(service, verification, approvals)
    scheduled = store.load_post(post.id)
    fake.verdict = "REQUIRES_HUMAN"
    result = verification.verify(post.id, actor="tester")
    assert not result.eligible
    payload = store.artifact_file(result.report_path).read_bytes()
    store.save_post(
        replace(
            scheduled,
            verification_ref=ArtifactRef(
                result.report_path, hashlib.sha256(payload).hexdigest(), scheduled.computed_fingerprint()
            ),
        ),
        expected_revision=store.load_post(post.id).revision,
    )
    assert "weakened from CONDITIONALLY_PROVEN to REQUIRES_HUMAN" in gate_blockers(store, clock, post.id)[0]


def test_old_approval_expires(store, service, verification, approvals, clock):
    post = approved_and_scheduled(service, verification, approvals)
    clock.advance(days=30)
    assert not any("needs a new approval" in item for item in gate_blockers(store, clock, post.id))
    clock.advance(minutes=1)
    assert any("30 day(s) old (limit 30)" in item for item in gate_blockers(store, clock, post.id))
    clock.set("2026-11-15T12:00:00Z")
    assert any("approval is dated in the future" in item for item in gate_blockers(store, clock, post.id))


def test_approval_age_setting_is_bounded():
    assert parse_config({"schema": CONFIG_SCHEMA}).approval_max_age_days == 30
    for value in (0, 91, "30", True):
        with pytest.raises(ConfigError, match="approval_max_age_days"):
            parse_config({"schema": CONFIG_SCHEMA, "approval_max_age_days": value})


# The publishing run with the real gates (scripted transport: says nothing about LinkedIn)


def test_valid_approval_lets_the_run_reach_the_transport_once(store, service, verification, approvals, clock):
    post = approved_and_scheduled(service, verification, approvals)
    go_live(store)
    clock.set(DUE)
    trust = ap.TrustSettings.from_environment(publish_env())
    gates = ap.publish_gates(store, trust, clock)
    assert [type(gate).__name__ for gate in gates] == ["VerificationGate", "ApprovalGate"]
    transport = FakeTransport()
    outcome = make_coordinator(store, clock, transport, gates=gates).run()
    assert outcome.outcome.value == "PUBLISHED" and transport.calls == [post.id]


def test_run_without_the_key_or_with_an_unauthorized_day_sends_nothing(
    store, service, verification, approvals, clock
):
    post = approved_and_scheduled(service, verification, approvals)
    service.reschedule(post.id, actor="agent", new_date="2026-11-19")
    go_live(store)
    clock.set("2026-11-19T13:30:00Z")
    for env in (publish_env(), publish_env(**{ap.KEY_ENV: None})):
        trust = ap.TrustSettings.from_environment(env)
        transport = FakeTransport()
        outcome = make_coordinator(store, clock, transport, gates=ap.publish_gates(store, trust, clock)).run()
        assert outcome.outcome.value == "BLOCKED" and transport.calls == []
    assert store.load_post(post.id).state is S.SCHEDULED


# Secrets hygiene


def test_the_key_is_never_shown_or_stored(store, service, verification, approvals):
    assert KEY not in repr(approvals.trust) and KEY not in repr(approvals.trust.problems)
    post = approved_and_scheduled(service, verification, approvals)
    approvals.authorize_schedule(post.id, new_date="2026-11-23")
    for file in store.root.rglob("*"):
        if file.is_file():
            assert KEY.encode() not in file.read_bytes(), file
    bad = ap.TrustSettings.from_environment({ap.KEY_ENV: "short-secret"})
    assert bad.key is None and "short-secret" not in " ".join(bad.problems)


# Command line


def cli(repo, capsys, *argv, expect=0):
    code = main(["linkedin", "--repo", str(repo), *argv])
    captured = capsys.readouterr()
    assert code == expect, captured.out + captured.err
    return captured


def test_review_and_approve_commands(store, fake, monkeypatch, capsys):
    """Through the real argument parser and the real clock, with the identity GitHub would supply."""
    for name in actions_env():
        monkeypatch.delenv(name, raising=False)
    queue = QueueService(store)
    post = queue.add_draft(title="A post", text=TEXT, actor="tester")
    assert VerificationService(store, fake.adapter()).verify(post.id, actor="tester").eligible
    queue.submit_for_review(post.id, actor="tester")

    shown = cli(store.root, capsys, "review", post.id).out
    review = json.loads(cli(store.root, capsys, "review", post.id, "--json").out)
    assert review["content_fingerprint"] in shown and review["limitations_digest"] in shown
    assert TEXT in shown and "This command approved nothing." in shown
    assert all(item in shown for item in review["limitations"])
    assert store.load_post(post.id).state is S.READY_FOR_REVIEW
    confirm = (
        "--fingerprint",
        review["content_fingerprint"],
        "--limitations-digest",
        review["limitations_digest"],
    )

    refused = cli(store.root, capsys, "approve", post.id, *confirm, expect=1).err
    assert "not authorized" in refused and store.load_post(post.id).state is S.READY_FOR_REVIEW
    with pytest.raises(SystemExit):
        main(["linkedin", "--repo", str(store.root), "approve", post.id, *confirm, "--actor", "owner"])
    capsys.readouterr()

    for name, value in actions_env(GITHUB_ACTOR_ID="2002").items():
        monkeypatch.setenv(name, value)
    assert "not the trusted approver" in cli(store.root, capsys, "approve", post.id, *confirm, expect=1).err
    wrong = ("--fingerprint", "sha256:" + "0" * 64, "--limitations-digest", review["limitations_digest"])
    monkeypatch.setenv("GITHUB_ACTOR_ID", OWNER_ID)
    assert "current content" in cli(store.root, capsys, "approve", post.id, *wrong, expect=1).err
    assert store.load_post(post.id).state is S.READY_FOR_REVIEW

    assert "approved" in cli(store.root, capsys, "approve", post.id, *confirm).out
    approved = store.load_post(post.id)
    assert approved.state is S.APPROVED and approved.history[-1].actor == "github:owner#1001"
    assert cli(store.root, capsys, "review", post.id, expect=1).out.count("BLOCKER") == 1


def test_review_command_exits_nonzero_for_a_post_that_cannot_be_approved(store, service, capsys):
    post = service.add_draft(title="Draft", text="A plain draft.", actor="tester")
    out = cli(store.root, capsys, "review", post.id, expect=1).out
    assert "BLOCKER" in out and "cannot be approved yet" in out


# The workflow template (static checks only; it has never run on GitHub)


def test_approval_workflow_template_is_narrow():
    path = Path(__file__).resolve().parents[2] / "docs/linkedin-publisher/workflows/linkedin-approve.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow[True] if True in workflow else workflow["on"]  # YAML reads a bare `on` as true
    assert list(triggers) == ["workflow_dispatch"], "no push, pull request or schedule trigger may approve"
    assert workflow["permissions"] == {"contents": "write"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["record"]
    assert "github.run_attempt == 1" in job["if"] and "refs/heads/main" in job["if"]
    assert job["timeout-minutes"] <= 15
    holders = [step for step in job["steps"] if "secrets." in json.dumps(step)]
    assert len(holders) == 1 and "approve" in holders[0]["run"], "only the recording step receives the key"
    for step in job["steps"]:
        assert "${{" not in step.get("run", ""), "inputs reach the shell only through environment variables"
    assert "pull_request" not in text and "secrets.LINKEDIN_APPROVAL_KEY" in text
    import re

    for step in job["steps"]:
        if "uses" in step:
            pinned = re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"])
            assert pinned, "actions must be pinned by commit"
