"""Verification of one post through HowlProof, and the report that records it.

Flow (``VerificationService.verify``):

1. Materialise the post as a package directory outside the repository: the
   exact text, the content fingerprint, the media bytes and, when the operator
   declared claims, the ``howl.claim_bundle/v1`` and its evidence files.
2. Run the deterministic content checks (``content_checks``).
3. Optionally check links through ``howlproof acquire`` (explicit opt in).
4. Run the real ``howlproof evaluate`` on the package with the operator owned
   contract ``howlproof.post.yaml``.
5. Write a machine readable report as a separate artifact and attach a
   reference to the post only when nothing blocks.

The report's ``verdict`` is HowlProof's own verdict, copied. It is null when
HowlProof did not deliver one. Nothing here can raise a verdict; the
deterministic checks can only add blockers and limitations.

A verification report never authorizes publication. It makes a post eligible
for human approval (milestone M3) or blocks it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from howlwriter import __version__ as HOWLWRITER_VERSION
from howlwriter.linkedin import content_checks as cc
from howlwriter.linkedin.checks import ERROR, WARNING, CheckFinding
from howlwriter.linkedin.howlproof import (
    AUTHORITY,
    RUN_SCHEMA,
    VERDICTS,
    EvaluationRun,
    HowlProofAdapter,
)
from howlwriter.linkedin.models import (
    FINGERPRINT_PATTERN,
    ArtifactRef,
    LifecycleState,
    Post,
    format_utc,
    parse_utc,
)
from howlwriter.linkedin.service import (
    VERIFIABLE_STATES,
    Clock,
    OperationRefused,
    QueueService,
    SystemClock,
)
from howlwriter.linkedin.store import QueueStore, StoreError

S = LifecycleState

REPORT_SCHEMA = "howlwriter.linkedin_verification/v1"
PACKAGE_SCHEMA = "howlwriter.linkedin_verification_package/v1"

VERIFICATION_DIR = "verification"
HOWLPROOF_ROOT = "verification/howlproof"
ACQUISITION_STORE = "verification/acquisitions"
CLAIMS_DIR = "claims"
CONTRACT_FILENAME = "howlproof.post.yaml"
CLAIM_BUNDLE_FILE = "claims.json"

ELIGIBLE = "ELIGIBLE_FOR_HUMAN_APPROVAL"
BLOCKED = "BLOCKED"

#: Verdicts a human may be asked to approve. REJECT and INSUFFICIENT_EVIDENCE block.
APPROVABLE_VERDICTS = ("PROVEN", "CONDITIONALLY_PROVEN", "REQUIRES_HUMAN")
_VERDICT_RANK = {verdict: rank for rank, verdict in enumerate(VERDICTS)}
#: HowlProof checks that must have run and reached VERIFIED, whatever the contract says.
REQUIRED_HOWLPROOF_CHECKS = ("secrets.scan",)

MAX_CLAIM_FILES = 250
MAX_CLAIM_FILE_BYTES = 4 * 1024 * 1024
_SKIPPED_BY_HOWLPROOF = frozenset({".git", ".venv", "node_modules", "__pycache__", ".mypy_cache"})

LINK_REACHABLE = "REACHABLE"
LINK_BROKEN = "BROKEN"
LINK_UNCONFIRMED = "UNCONFIRMED"
LINK_NOT_CHECKED = "NOT_CHECKED"

STANDING_LIMITATIONS = (
    "No model and no person read the post during verification. Statements without a number "
    "(comparisons, causes, quotations, superlatives) were not extracted or checked; the approver must "
    "read for them.",
    "HowlProof describes its verdicts as advisory. A verdict is a statement about the evidence that was "
    "examined, not a statement that the post is true.",
)

DEFAULT_CONTRACT = """\
# HowlProof acceptance contract for one LinkedIn post package.
# Owned by the operator. HowlWriter passes this file to `howlproof evaluate --config`
# and records its SHA-256 in every verification report. Check it with
# `howlproof validate howlproof.post.yaml` after editing.
#
# HowlWriter additionally requires that secrets.scan ran and reached VERIFIED,
# whatever this file says.
schema_version: 1
artifact: linkedin-post
description: One LinkedIn post, its media, and any declared claims with their evidence.
profiles:
  - secrets.scan
  - research.claims
  - docs.claims
adversaries:
  - FUNCTIONAL
  - SECURITY
  - OPERATOR
blocking_severity: HIGH
docs:
  claim_sources:
    - post.txt
acceptance:
  - id: no-credentials
    requirement: checks_pass
    checks:
      - secrets.scan
  - id: no-severe-findings
    requirement: max_findings
    limit: 0
    min_severity: HIGH
"""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_digest(root: Path) -> str:
    """HowlProof's tree digest (``howlproof.target.tree_digest``), computed independently.

    Used to prove that the sealed HowlProof bundle was made for exactly this package.
    """
    names = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(sha256_bytes((root / name).read_bytes()).encode())
        digest.update(b"\n")
    return digest.hexdigest()


# Package


@dataclass
class Package:
    tree_digest: str
    files: list[dict[str, str]]
    problems: list[str]
    claim_texts: list[str] | None
    claim_ids: list[str]
    evidence_sources: dict[str, list[str]]
    evidence: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PACKAGE_SCHEMA,
            "tree_digest": self.tree_digest,
            "files": self.files,
            "problems": self.problems,
        }


def claims_dir(store: QueueStore, post_id: str) -> Path:
    return store.root / CLAIMS_DIR / post_id


def build_package(post: Post, store: QueueStore, destination: Path) -> Package:
    """Write the deterministic package for ``post`` into ``destination`` (an empty directory)."""
    problems: list[str] = []
    files: list[dict[str, str]] = []
    evidence: list[dict[str, str]] = []

    def put(relative: str, data: bytes, role: str) -> None:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append({"path": relative, "sha256": sha256_bytes(data), "role": role})

    put("post.txt", post.text.encode("utf-8"), "post_text")
    summary = {
        "schema": PACKAGE_SCHEMA,
        "post_id": post.id,
        "content_fingerprint": post.computed_fingerprint(),
        "urls": list(post.urls),
        "media": [item.to_dict() for item in post.media],
    }
    put(
        "post.json",
        (json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(),
        "post_record",
    )

    for media in post.media:
        try:
            data = store.media_file(media.path).read_bytes()
        except (OSError, StoreError) as error:
            problems.append(f"media file {media.path} could not be packaged ({type(error).__name__})")
            continue
        put(media.path, data, "media")

    claim_texts: list[str] | None = None
    claim_ids: list[str] = []
    sources: dict[str, list[str]] = {}
    source = claims_dir(store, post.id)
    if source.is_symlink():
        problems.append("the claims directory must not be a symbolic link")
    elif source.is_dir():
        entries = sorted(path for path in source.rglob("*") if not path.is_dir())
        if len(entries) > MAX_CLAIM_FILES:
            problems.append(f"the claims directory holds more than {MAX_CLAIM_FILES} files")
            entries = []
        for path in entries:
            relative = path.relative_to(source).as_posix()
            parts = PurePosixPath(relative).parts
            if path.is_symlink() or not path.is_file():
                problems.append(f"claims entry {relative} is not a regular file")
                continue
            if _SKIPPED_BY_HOWLPROOF & set(
                parts,
            ) or relative in ("post.txt", "post.json") or parts[0] == "media":
                problems.append(f"claims entry {relative} uses a reserved name")
                continue
            if path.stat().st_size > MAX_CLAIM_FILE_BYTES:
                problems.append(f"claims entry {relative} exceeds {MAX_CLAIM_FILE_BYTES} bytes")
                continue
            data = path.read_bytes()
            role = "claim_bundle" if relative == CLAIM_BUNDLE_FILE else "claim_evidence"
            put(relative, data, role)
            evidence.append(
                {"path": f"{CLAIMS_DIR}/{post.id}/{relative}", "sha256": sha256_bytes(data), "role": role}
            )
        bundle = source / CLAIM_BUNDLE_FILE
        if bundle.is_file() and not bundle.is_symlink():
            claim_texts, claim_ids, sources = _read_claims(bundle)

    return Package(tree_digest(destination), files, problems, claim_texts, claim_ids, sources, evidence)


def _read_claims(bundle: Path) -> tuple[list[str] | None, list[str], dict[str, list[str]]]:
    """Read claim texts and evidence source addresses. HowlProof does the real validation."""
    try:
        document = json.loads(bundle.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, [], {}
    if not isinstance(document, dict) or not isinstance(document.get("claims"), list):
        return None, [], {}
    refs = {
        entry.get("id"): entry.get("source_ref")
        for entry in document.get("evidence", [])
        if isinstance(entry, dict) and isinstance(entry.get("source_ref"), str)
    }
    texts: list[str] = []
    ids: list[str] = []
    sources: dict[str, list[str]] = {}
    for item in document["claims"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        texts.append(item["text"])
        claim_id = str(item.get("claim_id", ""))
        ids.append(claim_id)
        for ref in item.get("evidence_refs") or []:
            if isinstance(ref, str) and ref in refs:
                sources.setdefault(refs[ref], []).append(claim_id)
    return texts, ids, sources


# HowlProof bundle integrity (independent of the HowlProof program)


def bundle_problems(bundle: Path) -> tuple[list[str], dict[str, Any]]:
    """Re-check a sealed HowlProof bundle against its own integrity index.

    Returns (problems, facts). Mirrors ``howlproof.evidence.Bundle.load`` so the
    check also works where HowlProof is not installed (the hosted publish run).
    """
    facts: dict[str, Any] = {}
    manifest_path = bundle / "manifest.json"
    if bundle.is_symlink(
    ) or not bundle.is_dir() or manifest_path.is_symlink() or not manifest_path.is_file():
        return ["the HowlProof bundle or its manifest is missing"], facts
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError):
        return ["the HowlProof bundle manifest is not readable JSON"], facts
    if not isinstance(manifest, dict) or manifest.get("schema") != RUN_SCHEMA:
        return ["the HowlProof bundle manifest has an unsupported schema"], facts
    if manifest.get("authority") != AUTHORITY:
        return ["the HowlProof bundle does not carry ADVISORY authority"], facts
    hashes = manifest.get("file_hashes")
    if not isinstance(
        hashes,
        dict,
    ) or not all(isinstance(k, str) and isinstance(v, str) for k, v in hashes.items()):
        return ["the HowlProof bundle integrity index is malformed"], facts
    problems: list[str] = []
    actual: set[str] = set()
    for entry in bundle.rglob("*"):
        if entry.is_symlink():
            name = entry.relative_to(bundle).as_posix()
            return [f"the HowlProof bundle contains a symbolic link: {name}"], facts
        if entry.is_file() and entry != manifest_path:
            actual.add(entry.relative_to(bundle).as_posix())
    unindexed = sorted(actual - set(hashes))
    if unindexed:
        problems.append(f"the HowlProof bundle contains files outside its integrity index: {unindexed[:5]}")
    for name, expected in sorted(hashes.items()):
        parts = PurePosixPath(name).parts
        if PurePosixPath(name).is_absolute() or ".." in parts:
            problems.append(f"the HowlProof bundle index names an unsafe path: {name}")
            continue
        candidate = bundle / name
        if not candidate.is_file():
            problems.append(f"HowlProof bundle file is missing: {name}")
        elif sha256_bytes(candidate.read_bytes()) != expected:
            problems.append(f"HowlProof bundle file does not match its recorded hash: {name}")
    if problems:
        return problems, facts
    try:
        result = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
        target = json.loads((bundle / "target.json").read_text(encoding="utf-8"))
        config = (bundle / "config.json").read_bytes()
    except (OSError, ValueError):
        return ["the HowlProof bundle lacks a readable result, target or configuration"], facts
    if not isinstance(result, dict) or not isinstance(target, dict):
        return ["the HowlProof bundle result or target is malformed"], facts
    facts.update(
        manifest_sha256=sha256_bytes(manifest_bytes),
        run_id=manifest.get("run_id"),
        version=manifest.get("version"),
        implementation_hash=manifest.get("implementation_hash"),
        verdict=result.get("verdict"),
        tree_digest_before=target.get("tree_digest_before"),
        tree_digest_after=target.get("tree_digest_after"),
        config_sha256=sha256_bytes(config),
    )
    return [], facts


# Report


def _hp_section(
    run: EvaluationRun,
    bundle_facts: dict[str, Any],
    bundle_issues: list[str],
    contract: dict,
) -> dict:
    result = run.result
    error = run.error
    if not error and bundle_issues:
        error = "the HowlProof evidence bundle failed its integrity check: " + "; ".join(bundle_issues[:3])
    return {
        "executed": run.executed,
        "command": list(run.command),
        "exit_code": run.exit_code,
        "error": error,
        "run_id": result.get("run_id"),
        "version": result.get("version"),
        "implementation_hash": (result.get("manifest") or {}).get("implementation_hash"),
        "verdict": run.verdict,
        "verdict_unusable": None,
        "deciding_rule": result.get("deciding_rule"),
        "rationale": [str(item) for item in result.get("rationale", [])],
        "criteria": [
            {key: item.get(key) for key in ("id", "requirement", "outcome", "detail", "optional")}
            for item in result.get("criteria", [])
            if isinstance(item, dict)
        ],
        "checks": [
            {
                key: check.get(key, "")
                for key in ("check_id", "checker", "status", "summary", "limitation", "reason", "mode")
            }
            for check in result.get("checks", [])
        ],
        "findings": [
            {
                key: finding.get(key)
                for key in (
                    "id",
                    "check_id",
                    "severity",
                    "confidence",
                    "title",
                    "summary",
                    "location",
                    "state",
                )
            }
            | {"blocking": bool(finding.get("blocking"))}
            for finding in result.get("findings", [])
            if isinstance(finding, dict)
        ],
        "limitations": [str(item) for item in result.get("limitations", [])],
        "unresolved_risks": [str(item) for item in result.get("unresolved_risks", [])],
        "bundle_path": f"{HOWLPROOF_ROOT}/{result['run_id']}" if result.get("run_id") else None,
        "manifest_sha256": bundle_facts.get("manifest_sha256"),
        "target_tree_digest": (result.get("target") or {}).get("tree_digest_before"),
        "contract": contract,
    }


def _claim_rows(run: EvaluationRun) -> list[dict[str, Any]]:
    rows = []
    for check in run.result.get("checks", []):
        detail = check.get("detail") if isinstance(check.get("detail"), dict) else {}
        if str(check.get("check_id", "")).startswith("research.claims.c") and "claim_id" in detail:
            rows.append(
                {
                    "claim_id": str(detail.get("claim_id")),
                    "check_id": check["check_id"],
                    "check_status": check["status"],
                    "claim_status": str(detail.get("claim_status", "")),
                    "evidence_status": str((detail.get("assurance") or {}).get("evidence_status", "")),
                    "explanation": str(detail.get("explanation", ""))[:500],
                }
            )
    return rows


def derive_outcome(report: dict[str, Any]) -> dict[str, Any]:
    """Decide eligibility from the recorded facts alone.

    The same function runs when the report is written and again whenever it is
    checked, so an edited ``outcome`` block cannot make a blocked report pass.
    """
    blockers: list[str] = []
    limitations: list[str] = []
    hp = report["howlproof"]
    verdict = hp["verdict"]

    for problem in report["package"]["problems"]:
        blockers.append(f"package: {problem}")
    if not hp["executed"]:
        blockers.append(f"HowlProof did not run: {hp['error'] or 'no reason recorded'}")
    elif hp["error"]:
        blockers.append(hp["error"])
    if report["verdict"] != verdict:
        blockers.append("the report verdict differs from the HowlProof verdict it records")
    if verdict is None:
        blockers.append("there is no HowlProof verdict")
    elif verdict not in APPROVABLE_VERDICTS:
        blockers.append(f"HowlProof verdict is {verdict}: " + "; ".join(hp["rationale"][:5]))
    if hp["executed"] and verdict is not None:
        statuses = {check["check_id"]: check["status"] for check in hp["checks"]}
        for required in REQUIRED_HOWLPROOF_CHECKS:
            if statuses.get(required) != "VERIFIED":
                blockers.append(
                    f"required HowlProof check {required} is {statuses.get(required, 'absent from the run')}"
                )
        for check in hp["checks"]:
            if check["status"] == "ERROR":
                blockers.append(f"HowlProof check {check['check_id']} errored: {check['reason']}")
        if hp["target_tree_digest"] != report["package"]["tree_digest"]:
            blockers.append("HowlProof evaluated a different file set than the package recorded here")
        if hp["manifest_sha256"] is None:
            blockers.append("the HowlProof evidence bundle was not found or not intact")
        if not hp["contract"].get("sha256"):
            blockers.append("the HowlProof acceptance contract was not recorded")

        if verdict != "PROVEN":
            limitations += [f"HowlProof {verdict}: {line}" for line in hp["rationale"]]
        limitations += [f"HowlProof limitation: {line}" for line in hp["limitations"]]
        limitations += [f"HowlProof unresolved risk: {line}" for line in hp["unresolved_risks"]]
        for check in hp["checks"]:
            if check["status"] == "VERIFIED" and check["limitation"]:
                limitations.append(f"{check['check_id']} does not establish: {check['limitation']}")
    for row in report["claims"]:
        if row["check_status"] != "VERIFIED":
            limitations.append(
                f"claim {row['claim_id']} is {row['claim_status'] or row['check_status']}, not supported: "
                f"{row['explanation']}"
            )
        elif not row["evidence_status"].startswith("SOURCE_VERIFIED"):
            limitations.append(
                f"claim {row['claim_id']} is {row['claim_status']} with evidence status "
                f"{row['evidence_status'] or 'unknown'}: the check held on the numbers supplied, and those "
                "numbers were not verified against an acquired source"
            )

    for record in report["preflight"]:
        status = record["status"]
        if status == cc.CHECK_ERROR:
            blockers.append(f"check {record['id']} errored ({record['reason']})")
        elif status == cc.FAILED:
            errors = [f["message"] for f in record["findings"] if f["severity"] == ERROR]
            blockers += [f"{record['id']}: {message}" for message in errors]
            if not errors:
                blockers.append(f"check {record['id']} failed")
        elif status == cc.NOT_EXECUTED:
            limitations.append(f"{record['id']} was not executed: {record['reason']}")
        elif status not in (cc.PASSED, cc.NOT_APPLICABLE):
            blockers.append(f"check {record['id']} has an unknown status {status!r}")
        limitations += [
            f"{record['id']}: {f['message']}" for f in record["findings"] if f["severity"] == WARNING
        ]
        if status == cc.PASSED:
            limitations.append(f"{record['id']} does not establish: {record['limitation']}")

    limitations += list(STANDING_LIMITATIONS)
    return {
        "status": BLOCKED if blockers else ELIGIBLE,
        "blockers": list(dict.fromkeys(blockers)),
        "limitations": list(dict.fromkeys(limitations)),
        "human_approval_required": True,
    }


def report_problems(data: Any) -> list[str]:
    """Structural validation of a stored report. Returns every problem found."""
    if not isinstance(data, dict):
        return ["the report is not a JSON object"]
    problems: list[str] = []

    def need(container: Any, key: str, kinds: Any, where: str) -> Any:
        value = container.get(key) if isinstance(container, dict) else None
        if not isinstance(container, dict) or key not in container or not isinstance(value, kinds):
            problems.append(f"{where}{key} is missing or has the wrong type")
            return None
        return value

    if data.get("schema") != REPORT_SCHEMA:
        problems.append(f"schema must be {REPORT_SCHEMA!r}")
    need(data, "post_id", str, "")
    fingerprint = need(data, "content_fingerprint", str, "")
    if fingerprint is not None and not FINGERPRINT_PATTERN.match(fingerprint):
        problems.append("content_fingerprint is malformed")
    created = need(data, "created_at", str, "")
    if created is not None:
        try:
            parse_utc(created)
        except ValueError:
            problems.append("created_at is not a UTC timestamp")
    if data.get("verdict") is not None and data.get("verdict") not in VERDICTS:
        problems.append("verdict is not a HowlProof verdict or null")
    for key in ("media", "evidence", "preflight", "claims"):
        need(data, key, list, "")
    need(data, "tools", dict, "")
    package = need(data, "package", dict, "")
    if package is not None:
        need(package, "tree_digest", str, "package.")
        need(package, "problems", list, "package.")
        need(package, "files", list, "package.")
    links = need(data, "links", dict, "")
    if links is not None:
        need(links, "network_allowed", bool, "links.")
        need(links, "results", list, "links.")
    hp = need(data, "howlproof", dict, "")
    if hp is not None:
        need(hp, "executed", bool, "howlproof.")
        need(hp, "error", str, "howlproof.")
        for key in (
            "rationale",
            "checks",
            "findings",
            "limitations",
            "unresolved_risks",
            "criteria",
            "command",
        ):
            need(hp, key, list, "howlproof.")
        need(hp, "contract", dict, "howlproof.")
        for key in ("verdict", "manifest_sha256", "target_tree_digest", "bundle_path", "run_id"):
            if key not in hp or not isinstance(hp[key], (str, type(None))):
                problems.append(f"howlproof.{key} is missing or has the wrong type")
        if hp.get("verdict") is not None and hp.get("verdict") not in VERDICTS:
            problems.append("howlproof.verdict is not a HowlProof verdict or null")
        for check in hp.get("checks") or []:
            if not isinstance(check, dict) or not all(
                isinstance(check.get(key), str) for key in ("check_id", "status", "reason", "limitation")
            ):
                problems.append("a howlproof.checks entry is malformed")
                break
        if not all(isinstance(line, str) for key in ("rationale", "limitations", "unresolved_risks")
                   for line in (hp.get(key) or [])):
            problems.append("howlproof rationale and limitations must be text")
    for record in data.get("preflight") or []:
        ok = (
            isinstance(record, dict)
            and all(isinstance(record.get(key), str) for key in (
                "id",
                "status",
                "reason",
                "limitation",
                "method",
            ))
            and record.get("status") in cc.CHECK_STATUSES
            and isinstance(record.get("findings"), list)
            and all(
                isinstance(f, dict) and all(
                    isinstance(f.get(k), str) for k in ("code", "severity", "message")
                )
                for f in record["findings"]
            )
        )
        if not ok:
            problems.append("a preflight entry is malformed")
            break
    for row in data.get("claims") or []:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str)
            for key in ("claim_id", "check_status", "claim_status", "evidence_status", "explanation")
        ):
            problems.append("a claims entry is malformed")
            break
    if package is not None and not all(isinstance(item, str) for item in package.get("problems") or []):
        problems.append("package.problems must be text")
    outcome = need(data, "outcome", dict, "")
    if outcome is not None:
        if outcome.get("status") not in (ELIGIBLE, BLOCKED):
            problems.append("outcome.status is unknown")
        need(outcome, "blockers", list, "outcome.")
        need(outcome, "limitations", list, "outcome.")
    return problems


def _link_results(
    post: Post, package: Package, adapter: HowlProofAdapter, store: QueueStore, allow_network: bool
) -> tuple[list[dict[str, Any]], cc.CheckRecord, list[dict[str, str]]]:
    check_id = "links.reachability"
    limitation = (
        "a link that answered shows only that bytes were received at that time. It does not show that the "
        "page supports the post. HowlProof accepts text pages only, so a working PDF or image link is "
        "reported as unconfirmed"
    )
    rows: list[dict[str, Any]] = [
        {
            "url": url,
            "status": LINK_NOT_CHECKED,
            "observed_url": None,
            "redirects": [],
            "acquisition_id": None,
            "content_sha256": None,
            "retrieved_at": None,
            "detail": "",
            "cited_by_claims": sorted(set(package.evidence_sources.get(url, []))),
        }
        for url in post.urls
    ]
    if not post.urls:
        return rows, cc.not_applicable(check_id, "the post has no links"), []
    if not allow_network:
        return rows, cc.not_executed(check_id, "network checks were not requested (--allow-network)"), []
    if not adapter.available:
        return rows, cc.not_executed(check_id, "HowlProof is not installed, so no link was contacted"), []

    findings: list[CheckFinding] = []
    evidence: list[dict[str, str]] = []
    for row in rows:
        run = adapter.acquire(row["url"], cwd=store.root, store=ACQUISITION_STORE)
        if run.ok:
            record = run.record
            row.update(
                status=LINK_REACHABLE,
                observed_url=record.get("observed_url"),
                redirects=list(record.get("redirects") or []),
                acquisition_id=record.get("id"),
                content_sha256=record.get("content_sha256"),
                retrieved_at=record.get("retrieved_at"),
            )
            record_path = store.root / ACQUISITION_STORE / "records" / f"{record['id']}.json"
            if record_path.is_file():
                evidence.append(
                    {
                        "path": f"{ACQUISITION_STORE}/records/{record['id']}.json",
                        "sha256": sha256_bytes(record_path.read_bytes()),
                        "role": "link_acquisition",
                    }
                )
            if _host(record.get("observed_url")) != _host(row["url"]):
                findings.append(
                    CheckFinding(
                        "LINK_REDIRECTS_ELSEWHERE",
                        WARNING,
                        f"{row['url']} ends at a different host: {record.get('observed_url')}",
                    )
                )
        else:
            row["detail"] = run.error
            gone = any(f"returned status {code}" in run.error for code in (404, 410))
            row["status"] = LINK_BROKEN if gone else LINK_UNCONFIRMED
            if gone:
                findings.append(
                    CheckFinding("LINK_BROKEN", ERROR, f"{row['url']} was not found: {run.error}"),
                )
            else:
                findings.append(
                    CheckFinding(
                        "LINK_UNCONFIRMED",
                        WARNING,
                        f"{row['url']} could not be confirmed: {run.error}",
                    )
                )
        if not row["cited_by_claims"]:
            findings.append(
                CheckFinding(
                    "LINK_NOT_EVIDENCE",
                    cc.INFO,
                    f"{row['url']} is not the recorded source of any declared claim",
                )
            )
    errors = any(f.severity == ERROR for f in findings)
    reachable = sum(1 for row in rows if row["status"] == LINK_REACHABLE)
    record = cc.CheckRecord(
        check_id,
        cc.FAILED if errors else cc.PASSED,
        f"{reachable} of {len(rows)} link(s) answered through howlproof acquire",
        limitation,
        tuple(findings),
        method="howlproof acquire",
    )
    return rows, record, evidence


def _host(url: Any) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower() if isinstance(url, str) else ""


@dataclass(frozen=True)
class VerificationResult:
    report: dict[str, Any]
    report_path: str
    eligible: bool
    attached: bool
    post: Post
    #: Why an otherwise eligible report was not attached (a weaker result after approval).
    withdrawn_reason: str = ""


class VerificationService:
    def __init__(
        self,
        store: QueueStore,
        adapter: HowlProofAdapter,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.clock = clock or SystemClock()
        self.verifier = ReportVerifier(store)
        self.queue = QueueService(store, self.clock, verifier=self.verifier)

    def verify(self, post_id: str, *, actor: str, allow_network: bool = False) -> VerificationResult:
        post = self.store.load_post(post_id)
        if post.state not in VERIFIABLE_STATES:
            raise OperationRefused(f"a {post.state.value} post cannot be verified")
        config = self.store.load_config()
        snapshot = self.store.load_snapshot()
        previous_verdict = self._previous_verdict(post)

        scratch = Path(tempfile.mkdtemp(prefix="howlwriter-verify-"))
        try:
            package_dir = scratch / "package"
            package_dir.mkdir()
            package = build_package(post, self.store, package_dir)

            media_facts: list[dict[str, Any]] = []

            def images() -> cc.CheckRecord:
                record, facts = cc.check_images(post, self.store)
                media_facts.extend(facts)
                return record

            preflight = [
                cc.run_guarded("content.format", lambda: cc.check_format(post, config, self.store)),
                cc.run_guarded("content.unicode", lambda: cc.check_unicode(post)),
                cc.run_guarded("content.links", lambda: cc.check_links(post)),
                cc.run_guarded("content.duplicates", lambda: cc.check_duplicates(post, snapshot.posts)),
                cc.run_guarded("privacy.patterns", lambda: cc.check_privacy(post)),
                cc.run_guarded("media.images", images),
                cc.run_guarded("claims.coverage", lambda: cc.check_claim_coverage(post, package.claim_texts)),
            ]
            if snapshot.invalid:
                preflight.append(
                    cc.not_executed(
                        "content.duplicates.unreadable",
                        f"{len(snapshot.invalid)} post file(s) are invalid and were not compared for "
                        "duplicates",
                    )
                )
            links, link_record, link_evidence = _link_results(
                post,
                package,
                self.adapter,
                self.store,
                allow_network,
            )
            preflight.append(link_record)

            contract_path = self.store.root / CONTRACT_FILENAME
            contract: dict[str, Any] = {"path": CONTRACT_FILENAME, "sha256": None}
            if contract_path.is_file() and not contract_path.is_symlink():
                contract["sha256"] = sha256_bytes(contract_path.read_bytes())
                store_arg = ACQUISITION_STORE if (self.store.root / ACQUISITION_STORE).is_dir() else None
                run = self.adapter.evaluate(
                    package_dir,
                    cwd=self.store.root,
                    config=CONTRACT_FILENAME,
                    evidence_root=HOWLPROOF_ROOT,
                    acquisition_store=store_arg,
                )
            else:
                run = EvaluationRun(
                    False,
                    (),
                    None,
                    None,
                    f"{CONTRACT_FILENAME} is missing; run 'howlwriter linkedin init' to create the starter "
                    "contract",
                )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        bundle_facts: dict[str, Any] = {}
        bundle_issues: list[str] = []
        run_id = run.result.get("run_id")
        if isinstance(run_id, str) and PurePosixPath(run_id).name == run_id and run_id not in ("", ".", ".."):
            bundle_issues, bundle_facts = bundle_problems(self.store.root / HOWLPROOF_ROOT / run_id)
            if not bundle_issues and bundle_facts.get("verdict") != run.result.get("verdict"):
                bundle_issues = ["the sealed bundle records a different verdict than HowlProof printed"]
                bundle_facts = {}

        hp = _hp_section(run, bundle_facts, bundle_issues, contract)
        created_at = format_utc(self.clock.now())
        report: dict[str, Any] = {
            "schema": REPORT_SCHEMA,
            "post_id": post.id,
            "content_fingerprint": post.computed_fingerprint(),
            "created_at": created_at,
            "media": media_facts or [{"path": m.path, "sha256": m.sha256} for m in post.media],
            "package": package.to_dict(),
            "evidence": package.evidence + link_evidence,
            "tools": {
                "howlwriter": HOWLWRITER_VERSION,
                "howlproof": {
                    "version": hp["version"] or self.adapter.version(),
                    "implementation_hash": hp["implementation_hash"],
                },
            },
            "howlproof": hp,
            "preflight": [record.to_dict() for record in preflight],
            "links": {"network_allowed": allow_network, "results": links},
            "claims": _claim_rows(run),
            "verdict": hp["verdict"] if not hp["error"] else None,
        }
        if hp["error"]:
            # No verdict is carried forward from a run that did not complete cleanly.
            hp["verdict_unusable"] = hp["verdict"]
            hp["verdict"] = None
        report["outcome"] = derive_outcome(report)

        stamp = created_at.replace("-", "").replace(":", "")
        relative = f"{VERIFICATION_DIR}/{post.id}/{stamp}-{post.computed_fingerprint()[7:15]}.json"
        payload = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        relative = self.store.write_artifact(relative, payload)

        with self.store.lock():
            # HowlProof ran without the lock. Decide only against the post it was run for.
            if self.store.load_post(post.id).revision != post.revision:
                raise OperationRefused(
                    f"the post changed while it was being verified; the report {relative} was kept but "
                    "not attached. Run verify again"
                )
            return self._decide(post, report, relative, payload, previous_verdict, actor)

    def _decide(
        self,
        post: Post,
        report: dict[str, Any],
        relative: str,
        payload: bytes,
        previous_verdict: str | None,
        actor: str,
    ) -> VerificationResult:
        """Attach an eligible report, or withdraw. Called under the store lock."""
        eligible = report["outcome"]["status"] == ELIGIBLE
        reason = ""
        if eligible and post.state in (S.APPROVED, S.SCHEDULED, S.FAILED) and previous_verdict is not None:
            if _VERDICT_RANK[report["verdict"]] > _VERDICT_RANK[previous_verdict]:
                eligible = False
                reason = (
                    f"the verdict weakened from {previous_verdict} to {report['verdict']} after approval; "
                    "the post needs a fresh review"
                )
        accepted = self._accepted_limitations(post) if eligible else None
        if eligible and accepted is not None:
            extra = [item for item in report["outcome"]["limitations"] if item not in accepted]
            if extra:
                eligible = False
                reason = (
                    f"the new report lists {len(extra)} limitation(s) the approval did not accept "
                    f"(first: {extra[0][:200]}); the post needs a fresh review"
                )
        if eligible:
            ref = ArtifactRef(relative, sha256_bytes(payload), post.computed_fingerprint())
            updated = self.queue.attach_verification(post.id, ref, actor=actor)
            return VerificationResult(report, relative, True, True, updated)
        detail = " ".join((reason or "; ".join(report["outcome"]["blockers"][:3])).split())
        updated = self.queue.withdraw_verification(
            post.id,
            actor=actor,
            detail=f"{relative}: {detail}"[:1500],
        )
        return VerificationResult(report, relative, False, False, updated, reason)

    def _accepted_limitations(self, post: Post) -> list[str] | None:
        """The limitation list a recorded approval accepted, or None when there is none to read.

        This is a courtesy check so a refresh that outgrows the approval is caught
        at once. The authoritative check is the approval gate at publish time.
        """
        if post.approval_ref is None or post.state not in (S.APPROVED, S.SCHEDULED, S.FAILED):
            return None
        try:
            data = json.loads(self.store.artifact_file(post.approval_ref.path).read_bytes())
        except (OSError, StoreError, ValueError):
            return None
        accepted = data.get("accepted_limitations") if isinstance(data, dict) else None
        if not isinstance(accepted, list):
            return None
        return [item for item in accepted if isinstance(item, str)]

    def _previous_verdict(self, post: Post) -> str | None:
        if post.verification_ref is None:
            return None
        try:
            data = json.loads(
                (self.store.artifact_file(post.verification_ref.path)).read_text(encoding="utf-8"),
            )
        except (OSError, ValueError, StoreError):
            return None
        verdict = data.get("verdict") if isinstance(data, dict) else None
        return verdict if verdict in VERDICTS else None


class ReportVerifier:
    """Decides whether a stored verification report is genuine for a post.

    It trusts nothing in the reference: the file hash, the fingerprint, the
    eligibility decision, the sealed HowlProof bundle and the package contents
    (media, claims and evidence as they are on disk now) are all recomputed.

    Limit: the report is not signed. Someone who can write to the repository
    can produce a consistent forged report and bundle. That is addressed by the
    human approval boundary (``approval.py``), which binds the report an approver saw.
    """

    def __init__(self, store: QueueStore) -> None:
        self.store = store

    def problems(self, kind: str, post: Post, ref: ArtifactRef) -> list[str]:
        if kind != "verification":
            return [f"{kind} artifacts are not accepted here; approvals are checked by the approval verifier"]
        report, problems = self.load(post, ref)
        if report is None or problems:
            return problems
        return self.evidence_problems(post, report)

    def load(self, post: Post, ref: ArtifactRef) -> tuple[dict[str, Any] | None, list[str]]:
        prefix = f"{VERIFICATION_DIR}/{post.id}/"
        if not ref.path.startswith(prefix) or not ref.path.endswith(".json") or "/" in ref.path[len(prefix):]:
            return None, [f"a verification report for this post must be a file under {prefix}"]
        try:
            payload = self.store.artifact_file(ref.path).read_bytes()
        except (OSError, StoreError):
            return None, ["the verification report file is missing or unreadable"]
        if sha256_bytes(payload) != ref.sha256:
            return None, ["the verification report was changed after it was attached"]
        try:
            report = json.loads(payload)
        except ValueError:
            return None, ["the verification report is not valid JSON"]
        problems = report_problems(report)
        if problems:
            return None, ["the verification report is malformed: " + "; ".join(problems[:5])]
        current = post.computed_fingerprint()
        if report["post_id"] != post.id:
            problems.append("the verification report belongs to a different post")
        if report["content_fingerprint"] != current or ref.content_fingerprint != current:
            problems.append("the verification report was made for different content")
        derived = derive_outcome(report)
        if derived != report["outcome"]:
            problems.append("the report's stated outcome does not follow from its recorded checks")
        if derived["status"] != ELIGIBLE:
            problems.append("the verification is blocked: " + "; ".join(derived["blockers"][:5]))
        return report, problems

    def evidence_problems(self, post: Post, report: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        hp = report["howlproof"]
        expected_path = f"{HOWLPROOF_ROOT}/{hp['run_id']}"
        if hp["bundle_path"] != expected_path or PurePosixPath(str(hp["run_id"])).name != hp["run_id"]:
            return ["the report points at a HowlProof bundle outside the evidence root"]
        issues, facts = bundle_problems(self.store.root / expected_path)
        if issues:
            return issues[:5]
        if facts["manifest_sha256"] != hp["manifest_sha256"]:
            problems.append("the HowlProof bundle is not the one the report recorded")
        if facts["verdict"] != report["verdict"]:
            problems.append("the HowlProof bundle records a different verdict than the report")
        digest = report["package"]["tree_digest"]
        if facts["tree_digest_before"] != digest or facts["tree_digest_after"] != digest:
            problems.append("the HowlProof bundle was made for a different package")

        scratch = Path(tempfile.mkdtemp(prefix="howlwriter-recheck-"))
        try:
            rebuilt = build_package(post, self.store, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        if rebuilt.problems or rebuilt.tree_digest != digest:
            problems.append(
                "the post's media, claims or evidence files changed since verification; verify the post again"
            )
        return problems


class VerificationGate:
    """Publish time gate: the attached verification must still be genuine and recent.

    This gate alone never allows a publication. The approval gate is also required;
    use ``approval.publish_gates`` to build both.
    """

    def __init__(self, store: QueueStore, clock: Clock | None = None) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self.verifier = ReportVerifier(store)

    def blockers(self, post: Post) -> list[str]:
        ref = post.verification_ref
        if ref is None:
            return ["no verification report is attached"]
        report, problems = self.verifier.load(post, ref)
        if report is None or problems:
            return problems
        problems = self.verifier.evidence_problems(post, report)
        limit = timedelta(days=self.store.load_config().verification_max_age_days)
        age = self.clock.now() - parse_utc(report["created_at"])
        if age > limit:
            problems.append(
                f"the verification is {age.days} day(s) old (limit {limit.days}); verify the post again "
                "before it is published"
            )
        if age < timedelta(minutes=-5):
            problems.append("the verification report is dated in the future")
        return problems
