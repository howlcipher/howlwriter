"""Adapter over the real HowlProof command line.

Only commands that exist in HowlProof 0.2.0b1 are used: ``--version``,
``evaluate`` and ``acquire``. The adapter never produces a verdict of its own.
It reports the verdict HowlProof printed, checks that the exit code agrees
with it, and turns every other situation (missing tool, usage error, internal
error, changed artifact, timeout, unreadable output) into an error with no
verdict at all.

HowlProof exit codes (``howlproof.model``): PROVEN 0, CONDITIONALLY_PROVEN 10,
REQUIRES_HUMAN 20, REJECT 30, INSUFFICIENT_EVIDENCE 40, usage 2, internal 3,
artifact changed during evaluation 4.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

VERDICT_EXIT_CODES: dict[str, int] = {
    "PROVEN": 0,
    "CONDITIONALLY_PROVEN": 10,
    "REQUIRES_HUMAN": 20,
    "REJECT": 30,
    "INSUFFICIENT_EVIDENCE": 40,
}
VERDICTS = tuple(VERDICT_EXIT_CODES)
EXIT_USAGE = 2
EXIT_INTERNAL = 3
EXIT_INTEGRITY = 4
CHECK_STATUSES = ("VERIFIED", "FAILED", "SKIPPED", "UNAVAILABLE", "NOT_APPLICABLE", "ERROR")

RESULT_SCHEMA = "howlproof.result/v1"
RUN_SCHEMA = "howlproof.run/v1"
AUTHORITY = "ADVISORY"

EXECUTABLE_ENV = "HOWLWRITER_HOWLPROOF"
EVALUATE_TIMEOUT_SECONDS = 300.0
ACQUIRE_TIMEOUT_SECONDS = 60.0
VERSION_TIMEOUT_SECONDS = 30.0
_MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str


#: (argv, working directory, timeout in seconds) -> result. Raises TimeoutError on timeout
#: and OSError when the program cannot be started.
Runner = Callable[[list[str], Path, float], ProcessResult]


def subprocess_runner(argv: list[str], cwd: Path, timeout: float) -> ProcessResult:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as expired:
        raise TimeoutError(f"no result after {timeout:.0f} seconds") from expired
    return ProcessResult(completed.returncode, completed.stdout, completed.stderr)


def find_executable(explicit: str | None = None) -> str | None:
    """Explicit argument, then ``HOWLWRITER_HOWLPROOF``, then ``howlproof`` on PATH."""
    candidate = explicit or os.environ.get(EXECUTABLE_ENV)
    if candidate:
        return candidate if (os.path.isfile(candidate) and os.access(candidate, os.X_OK)) else None
    return shutil.which("howlproof")


@dataclass(frozen=True)
class EvaluationRun:
    """What one ``howlproof evaluate`` call actually did.

    ``verdict`` is HowlProof's own word and is None whenever HowlProof did not
    deliver a usable result. ``error`` explains why in that case.
    """

    executed: bool
    command: tuple[str, ...]
    exit_code: int | None
    verdict: str | None
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict is not None and not self.error


@dataclass(frozen=True)
class AcquisitionRun:
    url: str
    executed: bool
    ok: bool
    record: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _error_text(stderr: str) -> str:
    """HowlProof prints one JSON object on stderr for failures; fall back to the raw text."""
    text = stderr.strip()
    try:
        parsed = json.loads(text.splitlines()[-1]) if text else None
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
        text = parsed["error"]
    return text[:_MAX_ERROR_CHARS]


def _result_problem(result: Any) -> str:
    """Return why a result document is unusable, or an empty string."""
    if not isinstance(result, dict):
        return "the result is not a JSON object"
    if result.get("schema") != RESULT_SCHEMA:
        return f"unexpected result schema {result.get('schema')!r}"
    if result.get("authority") != AUTHORITY:
        return "the result does not carry ADVISORY authority"
    if result.get("verdict") not in VERDICT_EXIT_CODES:
        return f"unknown verdict {result.get('verdict')!r}"
    for key, kind in (
        ("run_id", str),
        ("version", str),
        ("deciding_rule", str),
        ("rationale", list),
        ("criteria", list),
        ("checks", list),
        ("findings", list),
        ("limitations", list),
        ("target", dict),
        ("manifest", dict),
    ):
        if not isinstance(result.get(key), kind):
            return f"result field {key!r} is missing or has the wrong type"
    for check in result["checks"]:
        if not isinstance(check, dict) or check.get("status") not in CHECK_STATUSES:
            return "a check entry is malformed or has an unknown status"
        if not isinstance(check.get("check_id"), str):
            return "a check entry has no check_id"
    return ""


class HowlProofAdapter:
    def __init__(self, executable: str | None, runner: Runner | None = None) -> None:
        self.executable = executable
        self._run = runner or subprocess_runner

    @property
    def available(self) -> bool:
        return self.executable is not None

    def version(self) -> str | None:
        """The version HowlProof reports about itself, or None when it cannot be asked."""
        if not self.executable:
            return None
        try:
            outcome = self._run([self.executable, "--version"], Path.cwd(), VERSION_TIMEOUT_SECONDS)
        except (OSError, TimeoutError):
            return None
        text = (outcome.stdout or outcome.stderr).strip()
        if outcome.exit_code != 0 or not text or len(text) > 60 or "\n" in text:
            return None
        return text

    def evaluate(
        self,
        target: Path,
        *,
        cwd: Path,
        config: str,
        evidence_root: str,
        acquisition_store: str | None = None,
    ) -> EvaluationRun:
        """Run ``howlproof evaluate`` once. ``config`` and the roots are relative to ``cwd``.

        Relative paths keep the operator's home directory out of the sealed bundle.
        """
        if not self.executable:
            return EvaluationRun(False, (), None, None, "HowlProof is not installed or not on PATH")
        argv = [
            self.executable,
            "evaluate",
            str(target),
            "--config",
            config,
            "--evidence-root",
            evidence_root,
            "--json",
        ]
        if acquisition_store:
            argv += ["--acquisition-store", acquisition_store]
        shown = ("howlproof", *argv[1:2], "<package>", *argv[3:])
        try:
            outcome = self._run(argv, cwd, EVALUATE_TIMEOUT_SECONDS)
        except TimeoutError as error:
            return EvaluationRun(True, shown, None, None, f"HowlProof timed out: {error}")
        except OSError as error:
            return EvaluationRun(
                False,
                shown,
                None,
                None,
                f"HowlProof could not be started ({type(error).__name__})",
            )

        code = outcome.exit_code
        if code in (EXIT_USAGE, EXIT_INTERNAL):
            kind = "usage or configuration error" if code == EXIT_USAGE else "internal error"
            return EvaluationRun(
                True, shown, code, None, f"HowlProof exited {code} ({kind}): {_error_text(outcome.stderr)}"
            )
        try:
            result = json.loads(outcome.stdout)
        except ValueError:
            return EvaluationRun(
                True,
                shown,
                code,
                None,
                f"HowlProof exited {code} without a readable result",
            )
        problem = _result_problem(result)
        if problem:
            return EvaluationRun(True, shown, code, None, f"HowlProof result is unusable: {problem}")

        verdict = result["verdict"]
        if code == EXIT_INTEGRITY:
            return EvaluationRun(
                True,
                shown,
                code,
                verdict,
                "HowlProof reported that the package changed during evaluation (exit 4); "
                "the evidence is void",
                result,
            )
        if code != VERDICT_EXIT_CODES[verdict]:
            return EvaluationRun(
                True,
                shown,
                code,
                None,
                f"HowlProof exit code {code} does not match its printed verdict {verdict}",
                result,
            )
        return EvaluationRun(True, shown, code, verdict, "", result)

    def acquire(self, url: str, *, cwd: Path, store: str) -> AcquisitionRun:
        """Run ``howlproof acquire --url`` once. This is the only call that reaches the network.

        HowlProof enforces the fetch policy (public hosts only, every redirect hop
        re-checked, bounded time and size). Nothing is fetched by HowlWriter itself.
        """
        if not self.executable:
            return AcquisitionRun(url, False, False, error="HowlProof is not installed or not on PATH")
        argv = [self.executable, "acquire", "--store", store, "--url", url]
        try:
            outcome = self._run(argv, cwd, ACQUIRE_TIMEOUT_SECONDS)
        except TimeoutError as error:
            return AcquisitionRun(url, True, False, error=f"timed out: {error}")
        except OSError as error:
            return AcquisitionRun(url, False, False, error=f"could not be started ({type(error).__name__})")
        if outcome.exit_code != 0:
            return AcquisitionRun(
                url,
                True,
                False,
                error=_error_text(outcome.stderr) or f"exit {outcome.exit_code}",
            )
        try:
            record = json.loads(outcome.stdout)
        except ValueError:
            return AcquisitionRun(url, True, False, error="acquisition record was not readable JSON")
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            return AcquisitionRun(url, True, False, error="acquisition record is malformed")
        return AcquisitionRun(url, True, True, record=record)
