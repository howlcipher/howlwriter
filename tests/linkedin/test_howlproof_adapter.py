"""HowlProof adapter against a scripted program: verdicts are preserved, everything else is an error."""

from __future__ import annotations

import json

import pytest

from howlwriter.linkedin.howlproof import (
    VERDICT_EXIT_CODES,
    HowlProofAdapter,
    ProcessResult,
    find_executable,
)
from tests.linkedin.proof_fakes import FAKE_VERSION, FakeHowlProof, check


def evaluate(fake: FakeHowlProof, tmp_path):
    package = tmp_path / "package"
    package.mkdir(exist_ok=True)
    (package / "post.txt").write_text("hello", encoding="utf-8")
    return fake.adapter().evaluate(package, cwd=tmp_path, config="contract.yaml", evidence_root="out")


@pytest.mark.parametrize("verdict", list(VERDICT_EXIT_CODES))
def test_each_howlproof_verdict_is_reported_unchanged(tmp_path, verdict):
    run = evaluate(FakeHowlProof(verdict), tmp_path)
    assert run.ok and run.verdict == verdict and run.exit_code == VERDICT_EXIT_CODES[verdict]
    assert run.result["verdict"] == verdict


def test_only_real_howlproof_subcommands_and_flags_are_used(tmp_path):
    fake = FakeHowlProof()
    evaluate(fake, tmp_path)
    fake.adapter().acquire("https://example.com/a", cwd=tmp_path, store="store")
    fake.adapter().version()
    argv = fake.commands("evaluate")[0]
    assert argv[3:] == ["--config", "contract.yaml", "--evidence-root", "out", "--json"]
    assert fake.commands("acquire")[0][2:] == ["--store", "store", "--url", "https://example.com/a"]
    assert {call[1] for call in fake.calls} == {"evaluate", "acquire", "--version"}


@pytest.mark.parametrize(("code", "word"), [(2, "usage"), (3, "internal")])
def test_usage_and_internal_errors_yield_no_verdict(tmp_path, code, word):
    fake = FakeHowlProof("PROVEN")
    fake.exit_code = code
    fake.stderr = json.dumps({"error": "invalid configuration"})
    run = evaluate(fake, tmp_path)
    assert not run.ok and run.verdict is None and run.executed
    assert word in run.error and "invalid configuration" in run.error


def test_artifact_changed_during_evaluation_is_an_error(tmp_path):
    fake = FakeHowlProof("INSUFFICIENT_EVIDENCE")
    fake.exit_code = 4
    run = evaluate(fake, tmp_path)
    assert not run.ok and "exit 4" in run.error


def test_exit_code_that_disagrees_with_the_printed_verdict_is_rejected(tmp_path):
    fake = FakeHowlProof("PROVEN")
    fake.exit_code = 30
    run = evaluate(fake, tmp_path)
    assert run.verdict is None and "does not match" in run.error

    fake = FakeHowlProof("REJECT")
    fake.exit_code = 0
    assert evaluate(fake, tmp_path).verdict is None, "a REJECT printed with exit 0 must not pass"


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not json",
        "[]",
        json.dumps({"schema": "howlproof.result/v2", "verdict": "PROVEN"}),
        json.dumps({"schema": "howlproof.result/v1", "authority": "BINDING", "verdict": "PROVEN"}),
        json.dumps({"schema": "howlproof.result/v1", "authority": "ADVISORY", "verdict": "APPROVED"}),
        json.dumps({"schema": "howlproof.result/v1", "authority": "ADVISORY", "verdict": "PROVEN"}),
    ],
)
def test_unreadable_or_incomplete_output_is_never_a_verdict(tmp_path, stdout):
    fake = FakeHowlProof("PROVEN")
    fake.stdout = stdout
    run = evaluate(fake, tmp_path)
    assert run.verdict is None and run.error


def test_unknown_check_status_is_rejected(tmp_path):
    fake = FakeHowlProof("PROVEN")
    fake.checks = [check("secrets.scan", "PASSED")]
    assert evaluate(fake, tmp_path).verdict is None


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("no result after 300 seconds"), OSError("exec format error")],
)
def test_timeout_and_start_failure_are_errors(tmp_path, failure):
    fake = FakeHowlProof("PROVEN")
    fake.raises = failure
    run = evaluate(fake, tmp_path)
    assert run.verdict is None and run.error
    acquisition = fake.adapter().acquire("https://example.com/a", cwd=tmp_path, store="store")
    assert not acquisition.ok and acquisition.error


def test_missing_program_never_runs_anything(tmp_path, monkeypatch):
    def refuse(*_):  # pragma: no cover - must not be reached
        raise AssertionError("nothing may be executed without a program")

    adapter = HowlProofAdapter(None, refuse)
    run = adapter.evaluate(tmp_path, cwd=tmp_path, config="c", evidence_root="o")
    assert not run.executed and run.verdict is None and "not installed" in run.error
    assert adapter.version() is None
    assert not adapter.acquire("https://example.com", cwd=tmp_path, store="s").executed

    monkeypatch.setenv("HOWLWRITER_HOWLPROOF", str(tmp_path / "absent"))
    assert find_executable() is None, "a configured but missing program must not fall back to PATH"
    assert find_executable(str(tmp_path / "also-absent")) is None


def test_acquire_reports_the_record_or_the_refusal(tmp_path):
    fake = FakeHowlProof()
    fake.acquisitions = {
        "https://example.com/ok": {
            "observed_url": "https://example.com/final",
            "redirects": ["https://example.com/final"],
        },
        "https://example.com/gone": "https://example.com/gone returned status 404",
    }
    ok = fake.adapter().acquire("https://example.com/ok", cwd=tmp_path, store="store")
    assert ok.ok and ok.record["observed_url"] == "https://example.com/final"
    gone = fake.adapter().acquire("https://example.com/gone", cwd=tmp_path, store="store")
    assert not gone.ok and "404" in gone.error


def test_version_is_what_the_program_says_or_nothing():
    assert FakeHowlProof().adapter().version() == FAKE_VERSION
    noisy = HowlProofAdapter("x", lambda argv, cwd, timeout: ProcessResult(0, "line one\nline two\n", ""))
    assert noisy.version() is None
    failing = HowlProofAdapter("x", lambda argv, cwd, timeout: ProcessResult(1, "0.2.0", ""))
    assert failing.version() is None
