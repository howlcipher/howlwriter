"""Human approval boundary: authenticated approval and schedule records.

HowlWriter and HowlProof propose and evaluate. Only a human authorizes, and the
only place an approval can be created is a GitHub Actions ``workflow_dispatch``
run that GitHub started for the configured account ID.

Two things make a record trustworthy, and both come from outside the
repository contents:

* ``HOWLWRITER_LINKEDIN_APPROVER_ID``: the numeric GitHub account ID allowed to
  approve. It is compared with the ``GITHUB_ACTOR_ID`` GitHub sets for the run.
  A login name, a name inside a post, or anything in a repository file is never
  used to decide who may approve.
* ``HOWLWRITER_LINKEDIN_APPROVAL_KEY``: a secret known only to the trusted
  workflows. Every record carries an HMAC-SHA256 made with it, so a record
  written by anything that does not hold the key is rejected at publish time.

Limits (see THREAT_MODEL.md): the key authenticates the workflow, not the
person. Anyone who can use the owner's GitHub token to start the workflow, or
who can change a workflow that receives the key, can produce valid approvals.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Mapping

from howlwriter.linkedin.howlproof import VERDICTS
from howlwriter.linkedin.models import (
    DATE_PATTERN,
    FINGERPRINT_PATTERN,
    SHA256_PATTERN,
    TIME_PATTERN,
    ArtifactRef,
    LifecycleState,
    Post,
    format_utc,
    parse_utc,
)
from howlwriter.linkedin.service import KEEP, DEFAULT, Clock, OperationRefused, QueueService, SystemClock
from howlwriter.linkedin.store import QueueStore, StoreError
from howlwriter.linkedin.verification import ReportVerifier, VerificationGate, sha256_bytes

S = LifecycleState

APPROVAL_SCHEMA = "howlwriter.linkedin_approval/v1"
SCHEDULE_SCHEMA = "howlwriter.linkedin_schedule_authorization/v1"
APPROVALS_DIR = "approvals"
SCHEDULE_PREFIX = "schedule-"

KEY_ENV = "HOWLWRITER_LINKEDIN_APPROVAL_KEY"
APPROVER_ENV = "HOWLWRITER_LINKEDIN_APPROVER_ID"
WORKFLOW_ENV = "HOWLWRITER_LINKEDIN_APPROVAL_WORKFLOW"
REF_ENV = "HOWLWRITER_LINKEDIN_APPROVAL_REF"
DEFAULT_WORKFLOW = ".github/workflows/linkedin-approve.yml"
DEFAULT_REF = "refs/heads/main"

METHOD = "hmac-sha256"
MIN_KEY_CHARS = 43  # 256 bits written in base64; `openssl rand -hex 32` gives 64
MAX_KEY_CHARS = 512
MAX_SCHEDULE_RECORDS = 200
MAX_RECORD_BYTES = 1024 * 1024
_DOMAIN = b"howlwriter.linkedin.approval.v1\x00"
_VERDICT_RANK = {verdict: rank for rank, verdict in enumerate(VERDICTS)}


class ApprovalRefused(OperationRefused):
    """The approval operation was refused. Nothing was approved."""


# Canonical form and authentication


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def limitations_digest(limitations: list[str]) -> str:
    """Digest of the exact limitation list an approver is shown and accepts."""
    return "sha256:" + hashlib.sha256(canonical(list(limitations))).hexdigest()


def key_id(key: bytes) -> str:
    """A short public label for a key, so a rotated key is recognizable. Not the key."""
    return hashlib.sha256(b"howlwriter.linkedin.approval.key-id\x00" + key).hexdigest()[:12]


def _mac(record: dict[str, Any], key: bytes) -> str:
    body = dict(record)
    body["authentication"] = {k: v for k, v in record["authentication"].items() if k != "mac"}
    return hmac.new(key, _DOMAIN + canonical(body), hashlib.sha256).hexdigest()


def sign(body: dict[str, Any], key: bytes) -> dict[str, Any]:
    record = dict(body)
    record["authentication"] = {"method": METHOD, "key_id": key_id(key)}
    record["authentication"]["mac"] = _mac(record, key)
    return record


def mac_problem(record: dict[str, Any], key: bytes | None) -> str:
    if key is None:
        return (
            f"the approval key ({KEY_ENV}) is not available here, so the record cannot be authenticated; "
            "only the trusted workflows hold it"
        )
    auth = record["authentication"]
    if auth["key_id"] != key_id(key):
        return "the record was made with a different approval key (rotated or foreign)"
    if not hmac.compare_digest(auth["mac"], _mac(record, key)):
        return "the record's authentication code is wrong: it was forged or changed"
    return ""


# Trust settings and workflow identity (both from the process environment, never from repository files)


@dataclass(frozen=True)
class TrustSettings:
    key: bytes | None = field(default=None, repr=False)
    approver_id: str | None = None
    workflow_path: str = DEFAULT_WORKFLOW
    ref: str = DEFAULT_REF
    repository_id: str | None = None
    problems: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> "TrustSettings":
        problems: list[str] = []
        raw = env.get(KEY_ENV, "")
        key: bytes | None = None
        if raw:
            if not MIN_KEY_CHARS <= len(raw) <= MAX_KEY_CHARS or raw != raw.strip() or len(set(raw)) < 10:
                problems.append(
                    f"{KEY_ENV} is too short or malformed; use at least {MIN_KEY_CHARS} random characters"
                )
            else:
                key = raw.encode("utf-8")
        approver = env.get(APPROVER_ENV, "") or None
        if approver is not None and not _is_digits(approver):
            problems.append(f"{APPROVER_ENV} must be the numeric GitHub account ID, not a login name")
            approver = None
        repository_id = env.get("GITHUB_REPOSITORY_ID", "") or None
        if repository_id is not None and not _is_digits(repository_id):
            repository_id = None
        return cls(
            key=key,
            approver_id=approver,
            workflow_path=env.get(WORKFLOW_ENV, "") or DEFAULT_WORKFLOW,
            ref=env.get(REF_ENV, "") or DEFAULT_REF,
            repository_id=repository_id,
            problems=tuple(problems),
        )


@dataclass(frozen=True)
class WorkflowContext:
    """Who GitHub says started this run. Read only from variables GitHub sets for a run."""

    in_actions: bool
    event: str
    actor_id: str
    actor_login: str
    triggering_actor: str
    repository: str
    repository_id: str
    run_id: str
    run_attempt: str
    workflow_ref: str
    ref: str
    sha: str

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> "WorkflowContext":
        def get(name: str) -> str:
            return env.get(name, "")

        return cls(
            in_actions=get("GITHUB_ACTIONS") == "true",
            event=get("GITHUB_EVENT_NAME"),
            actor_id=get("GITHUB_ACTOR_ID"),
            actor_login=get("GITHUB_ACTOR"),
            triggering_actor=get("GITHUB_TRIGGERING_ACTOR"),
            repository=get("GITHUB_REPOSITORY"),
            repository_id=get("GITHUB_REPOSITORY_ID"),
            run_id=get("GITHUB_RUN_ID"),
            run_attempt=get("GITHUB_RUN_ATTEMPT"),
            workflow_ref=get("GITHUB_WORKFLOW_REF"),
            ref=get("GITHUB_REF"),
            sha=get("GITHUB_SHA"),
        )

    def problems(self, trust: TrustSettings) -> list[str]:
        """Why this run may not authorize anything. Empty only for the trusted human's own dispatch."""
        problems = list(trust.problems)
        if trust.key is None and not trust.problems:
            problems.append(f"{KEY_ENV} is not set; approvals can only be made by the trusted workflow")
        if trust.approver_id is None:
            problems.append(f"{APPROVER_ENV} is not set; no account is trusted to approve")
        if not self.in_actions:
            problems.append("this is not a GitHub Actions run; only the approval workflow can approve")
        if self.event != "workflow_dispatch":
            started_by = self.event or "an unknown event"
            problems.append(f"the run was started by {started_by}, not a manual dispatch")
        if not _is_digits(self.actor_id):
            problems.append("GitHub did not report a numeric actor ID")
        elif trust.approver_id is not None and self.actor_id != trust.approver_id:
            problems.append(f"GitHub account ID {self.actor_id} is not the trusted approver")
        if not self.actor_login or self.triggering_actor != self.actor_login:
            problems.append("the run was triggered or re-run by a different account than its actor")
        if self.run_attempt != "1":
            problems.append("this is a re-run; start a new approval run instead")
        if self.ref != trust.ref:
            problems.append(f"the run is on {self.ref or 'an unknown ref'}, not {trust.ref}")
        expected = f"{self.repository}/{trust.workflow_path}@{trust.ref}"
        if not self.repository or self.workflow_ref != expected:
            problems.append(f"the run is not the trusted workflow {trust.workflow_path} on {trust.ref}")
        if not _is_digits(self.run_id) or not _is_digits(self.repository_id):
            problems.append("GitHub did not report the run and repository IDs")
        if not _is_commit(self.sha):
            problems.append("GitHub did not report the commit of the run")
        return problems

    def actor(self) -> dict[str, str]:
        return {"id": self.actor_id, "login": self.actor_login}

    def workflow(self) -> dict[str, str]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "workflow_ref": self.workflow_ref,
            "event": self.event,
            "ref": self.ref,
            "sha": self.sha,
        }

    def audit_actor(self) -> str:
        return f"github:{self.actor_login}#{self.actor_id}"


# Record structure


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 500 and "\n" not in value


def _is_digits(value: Any) -> bool:
    return isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 20


def _is_commit(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) in (40, 64)
        and all(character in "0123456789abcdef" for character in value)
    )


def _matches(pattern) -> Callable[[Any], bool]:
    return lambda value: isinstance(value, str) and bool(pattern.match(value))


def _optional(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda value: value is None or check(value)


def _is_timestamp(value: Any) -> bool:
    try:
        parse_utc(value)
    except ValueError:
        return False
    return True


def _is_limitations(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 500
        and all(isinstance(item, str) and len(item) <= 4000 for item in value)
    )


def _is_media(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and set(item) == {"path", "sha256"}
        and _is_text(item["path"])
        and _matches(SHA256_PATTERN)(item["sha256"])
        for item in value
    )


_ACTOR = {"id": _is_digits, "login": _is_text}
_WORKFLOW = {
    "repository": _is_text,
    "repository_id": _is_digits,
    "run_id": _is_digits,
    "run_attempt": _is_digits,
    "workflow_ref": _is_text,
    "event": _is_text,
    "ref": _is_text,
    "sha": _is_commit,
}
_AUTH = {"method": lambda v: v == METHOD, "key_id": _is_text, "mac": _matches(SHA256_PATTERN)}
_SCHEDULE = {"date": _optional(_matches(DATE_PATTERN)), "time": _optional(_matches(TIME_PATTERN))}

_APPROVAL_SPEC: dict[str, Any] = {
    "schema": lambda v: v == APPROVAL_SCHEMA,
    "post_id": _is_text,
    "content_fingerprint": _matches(FINGERPRINT_PATTERN),
    "media": _is_media,
    "verification": {
        "path": _is_text,
        "sha256": _matches(SHA256_PATTERN),
        "created_at": _is_timestamp,
        "verdict": lambda v: v in VERDICTS,
        "status": _is_text,
        "howlproof_run_id": _is_text,
        "howlproof_manifest_sha256": _matches(SHA256_PATTERN),
    },
    "accepted_limitations": _is_limitations,
    "limitations_digest": _matches(FINGERPRINT_PATTERN),
    "schedule": _SCHEDULE,
    "actor": _ACTOR,
    "workflow": _WORKFLOW,
    "approved_at": _is_timestamp,
    "authentication": _AUTH,
}

_SCHEDULE_SPEC: dict[str, Any] = {
    "schema": lambda v: v == SCHEDULE_SCHEMA,
    "post_id": _is_text,
    "content_fingerprint": _matches(FINGERPRINT_PATTERN),
    "approval": {"path": _is_text, "sha256": _matches(SHA256_PATTERN)},
    "previous": _SCHEDULE,
    "schedule": _SCHEDULE,
    "actor": _ACTOR,
    "workflow": _WORKFLOW,
    "authorized_at": _is_timestamp,
    "authentication": _AUTH,
}


def shape_problems(value: Any, spec: dict[str, Any], where: str = "") -> list[str]:
    """Strict structure check: exactly the expected keys, each with a valid value."""
    label = where.rstrip(".") or "record"
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    if set(value) != set(spec):
        return [f"{label} must have exactly: {', '.join(sorted(spec))}"]
    problems: list[str] = []
    for name, check in spec.items():
        if isinstance(check, dict):
            problems += shape_problems(value[name], check, f"{where}{name}.")
        elif not check(value[name]):
            problems.append(f"{where}{name} is missing or invalid")
    return problems


def approval_record_problems(record: Any) -> list[str]:
    return shape_problems(record, _APPROVAL_SPEC)


def schedule_record_problems(record: Any) -> list[str]:
    return shape_problems(record, _SCHEDULE_SPEC)


def _post_schedule(post: Post) -> dict[str, str | None]:
    return {"date": post.scheduled_date, "time": post.scheduled_time}


def _dump(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# Checking stored records


class ApprovalVerifier:
    """Decides whether a stored approval is genuine for a post, and delegates reports to M2.

    Nothing in the reference or the record is taken on trust: the file hash, the
    structure, the authentication code, the approver's account ID, the workflow
    identity, the content and media fingerprints and the verification coverage
    are all checked against the post as it is now.
    """

    def __init__(self, store: QueueStore, trust: TrustSettings, clock: Clock | None = None) -> None:
        self.store = store
        self.trust = trust
        self.clock = clock or SystemClock()
        self.reports = ReportVerifier(store)

    def problems(self, kind: str, post: Post, ref: ArtifactRef) -> list[str]:
        if kind == "verification":
            return self.reports.problems(kind, post, ref)
        if kind != "approval":
            return [f"unknown artifact kind {kind!r}"]
        _record, problems = self.load(post, ref)
        return problems

    def _read(self, path: str, expected_sha256: str | None) -> tuple[Any, str]:
        try:
            file = self.store.artifact_file(path)
            if file.is_symlink() or file.stat().st_size > MAX_RECORD_BYTES:
                return None, "the record file is a link or too large"
            payload = file.read_bytes()
        except (OSError, StoreError):
            return None, "the record file is missing or unreadable"
        if expected_sha256 is not None and sha256_bytes(payload) != expected_sha256:
            return None, "the record was changed after it was attached"
        try:
            return json.loads(payload), ""
        except ValueError:
            return None, "the record is not valid JSON"

    def _identity_problems(self, record: dict[str, Any]) -> list[str]:
        """Checks common to approval and schedule records, after the structure is known good."""
        problems: list[str] = list(self.trust.problems)
        problem = mac_problem(record, self.trust.key)
        if problem:
            # Without a valid authentication code nothing else in the record means anything.
            return problems + [problem]
        trust, flow = self.trust, record["workflow"]
        if trust.approver_id is None:
            problems.append(f"{APPROVER_ENV} is not set; no account is trusted to approve")
        elif record["actor"]["id"] != trust.approver_id:
            problems.append("the record was made for an account that is not the trusted approver")
        if flow["event"] != "workflow_dispatch" or flow["run_attempt"] != "1" or flow["ref"] != trust.ref:
            problems.append("the record does not come from a first-attempt dispatch on the trusted branch")
        if flow["workflow_ref"] != f"{flow['repository']}/{trust.workflow_path}@{trust.ref}":
            problems.append("the record does not come from the trusted approval workflow")
        if trust.repository_id is not None and flow["repository_id"] != trust.repository_id:
            problems.append("the record was made in a different repository")
        return problems

    def load(self, post: Post, ref: ArtifactRef) -> tuple[dict[str, Any] | None, list[str]]:
        prefix = f"{APPROVALS_DIR}/{post.id}/"
        name = ref.path[len(prefix):]
        if (
            not ref.path.startswith(prefix)
            or "/" in name
            or not name.endswith(".json")
            or name.startswith(SCHEDULE_PREFIX)
        ):
            return None, [f"an approval record for this post must be a file under {prefix}"]
        record, problem = self._read(ref.path, ref.sha256)
        if problem:
            return None, [f"approval: {problem}"]
        shape = approval_record_problems(record)
        if shape:
            return None, ["the approval record is malformed: " + "; ".join(shape[:5])]
        problems = self._identity_problems(record)
        if problems:
            return None, problems

        current = post.computed_fingerprint()
        if record["post_id"] != post.id:
            problems.append("the approval belongs to a different post")
        if record["content_fingerprint"] != current or ref.content_fingerprint != current:
            problems.append("the approval was given for different content")
        if record["media"] != [{"path": item.path, "sha256": item.sha256} for item in post.media]:
            problems.append("the approval was given for different media")
        if record["limitations_digest"] != limitations_digest(record["accepted_limitations"]):
            problems.append("the approval's limitation list does not match its digest")
        now = self.clock.now()
        age = now - parse_utc(record["approved_at"])
        limit = timedelta(days=self.store.load_config().approval_max_age_days)
        if age < timedelta(minutes=-5):
            problems.append("the approval is dated in the future")
        if age > limit:
            problems.append(
                f"the approval is {age.days} day(s) old (limit {limit.days}); the post needs a new approval"
            )
        problems += self._verification_problems(post, record)
        return record, problems

    def _verification_problems(self, post: Post, record: dict[str, Any]) -> list[str]:
        """The approval names one report. A newer report is covered only if it is no worse."""
        ref, approved = post.verification_ref, record["verification"]
        if ref is None:
            return ["no verification report is attached"]
        if ref.path == approved["path"] and ref.sha256 == approved["sha256"]:
            return []
        report, problems = self.reports.load(post, ref)
        if report is None or problems:
            return problems or ["the attached verification report is unusable"]
        if _VERDICT_RANK[report["verdict"]] > _VERDICT_RANK[approved["verdict"]]:
            return [
                f"the verification verdict weakened from {approved['verdict']} to {report['verdict']} "
                "after approval; the post needs a new approval"
            ]
        accepted = set(record["accepted_limitations"])
        extra = [item for item in report["outcome"]["limitations"] if item not in accepted]
        if extra:
            return [
                f"the current verification lists {len(extra)} limitation(s) the approver never accepted "
                f"(first: {extra[0][:200]}); the post needs a new approval"
            ]
        return []

    def schedule_problems(self, post: Post, record: dict[str, Any]) -> list[str]:
        """Is the post's present date and time one the approver authorized?"""
        wanted = _post_schedule(post)
        if record["schedule"] == wanted:
            return []
        directory = self.store.root / APPROVALS_DIR / post.id
        try:
            names = sorted(
                entry.name
                for entry in directory.iterdir()
                if entry.name.startswith(SCHEDULE_PREFIX) and entry.name.endswith(".json")
            )
        except OSError:
            names = []
        for name in reversed(names[-MAX_SCHEDULE_RECORDS:]):
            candidate, problem = self._read(f"{APPROVALS_DIR}/{post.id}/{name}", None)
            if problem or schedule_record_problems(candidate) or self._identity_problems(candidate):
                continue
            if (
                candidate["post_id"] == post.id
                and candidate["content_fingerprint"] == post.computed_fingerprint()
                and post.approval_ref is not None
                and candidate["approval"]
                == {"path": post.approval_ref.path, "sha256": post.approval_ref.sha256}
                and candidate["schedule"] == wanted
            ):
                return []
        shown = f"{wanted['date'] or 'no date'} {wanted['time'] or 'default time'}"
        return [
            f"the schedule {shown} was not authorized: it differs from the approved schedule and no "
            "authenticated schedule authorization matches it"
        ]


class ApprovalGate:
    """Publish time gate: a genuine, current human approval and an authorized schedule."""

    def __init__(self, store: QueueStore, trust: TrustSettings, clock: Clock | None = None) -> None:
        self.verifier = ApprovalVerifier(store, trust, clock)

    def blockers(self, post: Post) -> list[str]:
        if post.approval_ref is None:
            return ["no human approval is recorded"]
        record, problems = self.verifier.load(post, post.approval_ref)
        if record is None or problems:
            return problems
        return self.verifier.schedule_problems(post, record)


def publish_gates(
    store: QueueStore, trust: TrustSettings, clock: Clock | None = None
) -> tuple[VerificationGate, ApprovalGate]:
    """The gates a real publishing run must install. Both are always returned together."""
    return VerificationGate(store, clock), ApprovalGate(store, trust, clock)


# Creating records (trusted workflow only)


class ApprovalService:
    def __init__(
        self,
        store: QueueStore,
        env: Mapping[str, str],
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self.trust = TrustSettings.from_environment(env)
        self.context = WorkflowContext.from_environment(env)
        self.verifier = ApprovalVerifier(store, self.trust, self.clock)
        self.queue = QueueService(store, self.clock, verifier=self.verifier)

    def review(self, post_id: str) -> dict[str, Any]:
        """Everything an approver must see, and the two values they confirm. Changes nothing."""
        post = self.store.load_post(post_id)
        blockers: list[str] = []
        report: dict[str, Any] | None = None
        if post.state is not S.READY_FOR_REVIEW:
            blockers.append(f"the post is {post.state.value}; only a READY_FOR_REVIEW post can be approved")
        if post.verification_ref is None:
            blockers.append("no verification report is attached; run 'howlwriter linkedin verify' first")
        else:
            blockers += VerificationGate(self.store, self.clock).blockers(post)
            loaded, problems = self.verifier.reports.load(post, post.verification_ref)
            report = loaded if not problems else None
        limitations = list(report["outcome"]["limitations"]) if report else []
        return {
            "post_id": post.id,
            "title": post.title,
            "state": post.state.value,
            "text": post.text,
            "urls": list(post.urls),
            "media": [item.to_dict() for item in post.media],
            "schedule": _post_schedule(post),
            "content_fingerprint": post.computed_fingerprint(),
            "verification": (
                {
                    "path": post.verification_ref.path,
                    "sha256": post.verification_ref.sha256,
                    "created_at": report["created_at"],
                    "verdict": report["verdict"],
                    "status": report["outcome"]["status"],
                    "howlproof_run_id": report["howlproof"]["run_id"],
                    "howlproof_manifest_sha256": report["howlproof"]["manifest_sha256"],
                }
                if report and post.verification_ref
                else None
            ),
            "limitations": limitations,
            "limitations_digest": limitations_digest(limitations),
            "blockers": blockers,
            "approvable": not blockers,
        }

    def _require_trusted_run(self) -> None:
        problems = self.context.problems(self.trust)
        if problems:
            raise ApprovalRefused("not authorized: " + "; ".join(problems))

    def _stamp(self) -> tuple[str, str]:
        at = format_utc(self.clock.now())
        return at, at.replace("-", "").replace(":", "")

    def approve(self, post_id: str, *, fingerprint: str, accepted_limitations_digest: str) -> Post:
        """Record the trusted human's approval of exactly what ``review`` shows now."""
        self._require_trusted_run()
        assert self.trust.key is not None
        with self.store.lock():
            review = self.review(post_id)
            if review["blockers"]:
                raise ApprovalRefused("the post cannot be approved: " + "; ".join(review["blockers"][:5]))
            if fingerprint != review["content_fingerprint"]:
                raise ApprovalRefused(
                    "the fingerprint you confirmed is not the post's current content; review it again"
                )
            if accepted_limitations_digest != review["limitations_digest"]:
                raise ApprovalRefused(
                    "the limitations you accepted are not the current verification's limitations; "
                    "review it again"
                )
            at, stamp = self._stamp()
            record = sign(
                {
                    "schema": APPROVAL_SCHEMA,
                    "post_id": post_id,
                    "content_fingerprint": review["content_fingerprint"],
                    "media": [{"path": item["path"], "sha256": item["sha256"]} for item in review["media"]],
                    "verification": review["verification"],
                    "accepted_limitations": review["limitations"],
                    "limitations_digest": review["limitations_digest"],
                    "schedule": review["schedule"],
                    "actor": self.context.actor(),
                    "workflow": self.context.workflow(),
                    "approved_at": at,
                },
                self.trust.key,
            )
            shape = approval_record_problems(record)
            if shape:
                raise ApprovalRefused("the approval record could not be built: " + "; ".join(shape[:5]))
            payload = _dump(record)
            relative = f"{APPROVALS_DIR}/{post_id}/{stamp}-{fingerprint[7:15]}.json"
            (self.store.root / APPROVALS_DIR / post_id).mkdir(parents=True, exist_ok=True)
            relative = self.store.write_artifact(relative, payload)
            ref = ArtifactRef(relative, sha256_bytes(payload), review["content_fingerprint"])
            return self.queue.approve(post_id, ref, actor=self.context.audit_actor())

    def authorize_schedule(self, post_id: str, *, new_date: str | None, new_time: str = KEEP) -> Post:
        """Move an approved post and record that the trusted human authorized the new slot.

        Verification and approval are kept: the content did not change.
        """
        self._require_trusted_run()
        assert self.trust.key is not None
        with self.store.lock():
            post = self.store.load_post(post_id)
            if post.approval_ref is None:
                raise ApprovalRefused("the post has no approval; set its date before approval instead")
            _record, problems = self.verifier.load(post, post.approval_ref)
            if problems:
                raise ApprovalRefused("the post's approval is not valid: " + "; ".join(problems[:5]))
            moved = post
            if new_date is not None or new_time != KEEP:
                moved = self.queue.reschedule(
                    post_id, actor=self.context.audit_actor(), new_date=new_date, new_time=new_time
                )
            at, stamp = self._stamp()
            record = sign(
                {
                    "schema": SCHEDULE_SCHEMA,
                    "post_id": post_id,
                    "content_fingerprint": moved.computed_fingerprint(),
                    "approval": {"path": post.approval_ref.path, "sha256": post.approval_ref.sha256},
                    "previous": _post_schedule(post),
                    "schedule": _post_schedule(moved),
                    "actor": self.context.actor(),
                    "workflow": self.context.workflow(),
                    "authorized_at": at,
                },
                self.trust.key,
            )
            relative = f"{APPROVALS_DIR}/{post_id}/{SCHEDULE_PREFIX}{stamp}.json"
            self.store.write_artifact(relative, _dump(record))
            return moved


__all__ = [
    "APPROVAL_SCHEMA",
    "SCHEDULE_SCHEMA",
    "APPROVER_ENV",
    "KEY_ENV",
    "DEFAULT",
    "KEEP",
    "ApprovalGate",
    "ApprovalRefused",
    "ApprovalService",
    "ApprovalVerifier",
    "TrustSettings",
    "WorkflowContext",
    "approval_record_problems",
    "limitations_digest",
    "publish_gates",
    "schedule_record_problems",
    "sign",
]
