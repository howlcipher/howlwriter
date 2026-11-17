"""Contract tests against the REAL installed HowlProof program.

Skipped when ``howlproof`` is not installed (it is not a HowlWriter dependency
and is absent in HowlWriter's CI). Everything else in this directory uses a
scripted stand-in; these tests are the evidence that the adapter matches the
real program. They start one short process per evaluation and use no network.
"""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from howlwriter.linkedin.howlproof import HowlProofAdapter, find_executable
from howlwriter.linkedin.models import LifecycleState
from howlwriter.linkedin.store import QueueStore
from howlwriter.linkedin.verification import (
    CONTRACT_FILENAME,
    DEFAULT_CONTRACT,
    ELIGIBLE,
    ReportVerifier,
    VerificationService,
)
from tests.linkedin.helpers import FakeClock, make_service

EXECUTABLE = find_executable()
pytestmark = pytest.mark.skipif(EXECUTABLE is None, reason="the howlproof program is not installed")

TEXT = "Shipping small changes every day keeps reviews short.\n\nWhat has worked for your team?"


def howlproof(*args: str, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [EXECUTABLE, *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=cwd,
        check=False,
    )


@pytest.fixture
def store(tmp_path):
    queue_store = QueueStore(tmp_path / "repo")
    queue_store.initialize({CONTRACT_FILENAME: DEFAULT_CONTRACT})
    return queue_store


@pytest.fixture
def service(store):
    return make_service(store, FakeClock())


@pytest.fixture
def verification(store):
    return VerificationService(store, HowlProofAdapter(EXECUTABLE), FakeClock())


def write_claims(store, post_id: str, claims: list[dict]) -> None:
    root = store.root / "claims" / post_id
    (root / "evidence").mkdir(parents=True)
    facts = {"before": "10 min", "after": "6 min"}
    evidence = json.dumps({"id": "e1", "text": "CI export", "facts": facts}).encode()
    (root / "evidence" / "e1.json").write_bytes(evidence)
    bundle = {
        "schema": "howl.claim_bundle/v1",
        "candidate": {"candidate_id": post_id},
        "authorship": {"kind": "EXTERNAL_AUTHORED"},
        "claims": claims,
        "evidence": [
            {
                "id": "e1",
                "path": "evidence/e1.json",
                "sha256": hashlib.sha256(evidence).hexdigest(),
                "source_type": "INTERNAL_MEASUREMENT",
                "independent": False,
            }
        ],
    }
    (root / "claims.json").write_text(json.dumps(bundle), encoding="utf-8")


def arithmetic_claim(expected: str) -> dict:
    return {
        "claim_id": "c1",
        "text": "Build time fell by 40% this quarter",
        "category": "TECHNICAL",
        "evidence_refs": ["e1"],
        "check": {
            "type": "arithmetic",
            "expression": "(10 - 6) / 10 * 100",
            "expected": expected,
            "op": "eq",
        },
    }


def test_the_commands_and_flags_the_adapter_uses_exist():
    described = json.loads(howlproof("interop", "--json").stdout)
    commands = {tuple(item["path"]): set(item["flags"]) for item in described["commands"]}
    assert {"--config", "--evidence-root", "--json", "--acquisition-store"} <= commands[("evaluate",)]
    assert {"--store", "--url"} <= commands[("acquire",)]
    assert "--version" in commands[()]
    assert HowlProofAdapter(EXECUTABLE).version() == described["version"]


def test_the_starter_contract_is_valid_for_the_installed_howlproof(store):
    result = howlproof("validate", str(store.root / CONTRACT_FILENAME))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["profiles"] == ["secrets.scan", "research.claims", "docs.claims"]


def test_clean_post_real_run_is_conditional_and_the_bundle_binds_to_the_package(store, service, verification):
    post = service.add_draft(title="Clean", text=TEXT, actor="tester")
    result = verification.verify(post.id, actor="tester")
    report = result.report

    assert report["verdict"] == "CONDITIONALLY_PROVEN" and report["howlproof"]["exit_code"] == 10
    assert result.eligible and report["outcome"]["status"] == ELIGIBLE
    statuses = {c["check_id"]: c["status"] for c in report["howlproof"]["checks"]}
    assert statuses == {
        "secrets.scan": "VERIFIED",
        "research.claims": "NOT_APPLICABLE",
        "docs.claims.absolutes": "VERIFIED",
    }
    # HowlWriter's independent tree digest equals the one the real program computed.
    assert report["howlproof"]["target_tree_digest"] == report["package"]["tree_digest"]
    assert report["tools"]["howlproof"]["version"] == HowlProofAdapter(EXECUTABLE).version()
    assert report["tools"]["howlproof"]["implementation_hash"]

    stored = store.load_post(post.id)
    assert ReportVerifier(store).problems("verification", stored, stored.verification_ref) == []
    # The real program agrees that the stored bundle is intact and carries the same verdict.
    inspected = howlproof("inspect", str(store.root / report["howlproof"]["bundle_path"]))
    assert inspected.returncode == 10

    # The sealed bundle holds no absolute path into the repository.
    config = json.loads((store.root / report["howlproof"]["bundle_path"] / "config.json").read_text())
    assert config["source"] == CONTRACT_FILENAME


def test_credential_in_the_post_is_rejected_by_the_real_secret_scan(store, service, verification):
    token = "ghp_" + "a1B2" * 9  # assembled at run time; credential shaped, not a credential
    post = service.add_draft(title="Leak", text=f"{TEXT}\nDebug token {token}", actor="tester")
    result = verification.verify(post.id, actor="tester")
    report = result.report
    assert report["verdict"] == "REJECT" and report["howlproof"]["exit_code"] == 30
    assert not result.eligible and store.load_post(post.id).verification_ref is None
    assert report["howlproof"]["findings"][0]["severity"] == "BLOCKER"
    assert token not in json.dumps(report), "the report must not reprint the credential"


def test_supported_arithmetic_claim_reaches_real_proven_with_its_limit_stated(store, service, verification):
    post = service.add_draft(title="Metric", text="We cut build time by 40% this quarter.", actor="tester")
    write_claims(store, post.id, [arithmetic_claim("40")])
    result = verification.verify(post.id, actor="tester")
    report = result.report
    assert report["verdict"] == "PROVEN" and report["howlproof"]["exit_code"] == 0 and result.eligible
    assert report["claims"][0]["claim_status"] == "SUPPORTED"
    assert report["claims"][0]["evidence_status"] == "DETERMINISTIC_CHECK_ONLY"
    assert any("not verified against an acquired source" in item for item in report["outcome"]["limitations"])
    stored = store.load_post(post.id)
    assert stored.state is LifecycleState.DRAFT and stored.approval_ref is None


def test_refuted_claim_is_rejected_by_the_real_claim_evaluator(store, service, verification):
    post = service.add_draft(title="Metric", text="We cut build time by 40% this quarter.", actor="tester")
    write_claims(store, post.id, [arithmetic_claim("55")])
    result = verification.verify(post.id, actor="tester")
    assert result.report["verdict"] == "REJECT" and not result.eligible
    assert result.report["claims"][0]["claim_status"] == "REFUTED"


def test_unverifiable_empirical_claim_stays_unresolved(store, service, verification):
    post = service.add_draft(title="Metric", text="We cut build time by 40% this quarter.", actor="tester")
    claim = {
        "claim_id": "c1",
        "text": "Build time fell by 40% this quarter",
        "category": "EMPIRICAL",
        "evidence_refs": ["e1"],
    }
    write_claims(store, post.id, [claim])
    result = verification.verify(post.id, actor="tester")
    report = result.report
    assert report["verdict"] == "CONDITIONALLY_PROVEN"
    assert report["claims"][0]["claim_status"] == "INCONCLUSIVE"
    assert any("claim c1 is INCONCLUSIVE, not supported" in item for item in report["outcome"]["limitations"])


def test_malformed_claim_bundle_errors_and_blocks(store, service, verification):
    post = service.add_draft(title="Bad claims", text=TEXT, actor="tester")
    root = store.root / "claims" / post.id
    root.mkdir(parents=True)
    (root / "claims.json").write_text(
        '{"schema": "howl.claim_bundle/v1", "claims": "nope"}',
        encoding="utf-8",
    )
    result = verification.verify(post.id, actor="tester")
    assert not result.eligible
    assert any("research.claims.bundle errored" in b for b in result.report["outcome"]["blockers"])


def test_contract_whose_criterion_cannot_be_evaluated_gives_insufficient_evidence(
    store,
    service,
    verification,
):
    contract = DEFAULT_CONTRACT + (
        "  - id: claims-required\n    requirement: checks_pass\n    checks:\n      - research.claims\n"
    )
    (store.root / CONTRACT_FILENAME).write_text(contract, encoding="utf-8")
    post = service.add_draft(title="No claims", text=TEXT, actor="tester")
    result = verification.verify(post.id, actor="tester")
    assert result.report["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert result.report["howlproof"]["exit_code"] == 40
    assert not result.eligible


def test_expired_exclusion_gives_requires_human(store, service, verification):
    contract = DEFAULT_CONTRACT + (
        "exclusions:\n  - check: web.links\n    reason: Not relevant to a post package.\n"
        "    expires: 2020-01-01\n"
    )
    (store.root / CONTRACT_FILENAME).write_text(contract, encoding="utf-8")
    post = service.add_draft(title="Human", text=TEXT, actor="tester")
    result = verification.verify(post.id, actor="tester")
    assert result.report["verdict"] == "REQUIRES_HUMAN" and result.report["howlproof"]["exit_code"] == 20
    assert result.eligible
    assert any(
        item.startswith("HowlProof REQUIRES_HUMAN:") for item in result.report["outcome"]["limitations"]
    )


def test_invalid_contract_is_a_usage_error_with_no_verdict(store, service, verification):
    (store.root / CONTRACT_FILENAME).write_text(
        "schema_version: 1\nartifact: x\nunknown_key: true\n",
        encoding="utf-8",
    )
    post = service.add_draft(title="Broken contract", text=TEXT, actor="tester")
    result = verification.verify(post.id, actor="tester")
    report = result.report
    assert report["verdict"] is None and report["howlproof"]["exit_code"] == 2 and not result.eligible
    assert "invalid configuration" in report["howlproof"]["error"]


def test_contract_without_the_secret_scan_cannot_make_a_post_eligible(store, service, verification):
    weak = (
        "schema_version: 1\nartifact: linkedin-post\nprofiles: [docs.claims]\nadversaries: [OPERATOR]\n"
        "docs:\n  claim_sources: [post.txt]\n"
        "acceptance:\n  - id: collected\n    requirement: checks_pass\n    checks: [docs.claims.absolutes]\n"
    )
    (store.root / CONTRACT_FILENAME).write_text(weak, encoding="utf-8")
    post = service.add_draft(title="Weak contract", text=TEXT, actor="tester")
    result = verification.verify(post.id, actor="tester")
    assert result.report["verdict"] == "PROVEN", "the verdict under the weak contract is recorded as given"
    assert not result.eligible
    assert any("secrets.scan is absent" in b for b in result.report["outcome"]["blockers"])


def test_verify_command_end_to_end_with_the_real_program(store, service, capsys):
    from howlwriter.cli.main import main

    post = service.add_draft(title="CLI", text=TEXT, actor="tester")
    code = main(
        ["linkedin", "--repo", str(store.root), "verify", post.id, "--howlproof", EXECUTABLE, "--json"],
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["eligible"] and payload["report"]["verdict"] == "CONDITIONALLY_PROVEN"
    assert payload["report"]["links"]["network_allowed"] is False


@pytest.mark.parametrize(
    ("url", "fragment"),
    [
        ("https://127.0.0.1/x", "non-public address"),
        ("https://192.168.1.10/", "non-public address"),
        ("http://169.254.169.254/latest/meta-data", "non-public address"),
        ("https://localhost/x", "not a public DNS name"),
        ("https://user:secret@example.com/", "credentials"),
        ("ftp://example.com/file", "not supported"),
        ("https://example.com:8443/", "port 8443 is not allowed"),
    ],
)
def test_real_acquire_refuses_unsafe_destinations_before_connecting(tmp_path, url, fragment):
    """These are refused by HowlProof's address policy, so the test makes no connection."""
    run = HowlProofAdapter(EXECUTABLE).acquire(url, cwd=tmp_path, store="store")
    assert run.executed and not run.ok and fragment in run.error
    assert not (tmp_path / "store" / "records").exists()
    assert (tmp_path / "store" / "attempts.jsonl").is_file(), "the refused attempt is logged by HowlProof"
