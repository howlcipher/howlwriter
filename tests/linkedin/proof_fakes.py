"""A scripted stand-in for the HowlProof program. No process is started and nothing is fetched.

It is a mock. It proves how HowlWriter reacts to each HowlProof outcome; it is
not evidence about HowlProof itself. ``test_howlproof_contract.py`` runs the
real program for that.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from howlwriter.linkedin.howlproof import VERDICT_EXIT_CODES, HowlProofAdapter, ProcessResult
from howlwriter.linkedin.verification import tree_digest

FAKE_VERSION = "0.0.0-fake"


def check(check_id: str, status: str = "VERIFIED", reason: str = "", detail: dict | None = None) -> dict:
    return {
        "check_id": check_id,
        "checker": f"{check_id}/v1",
        "adversary": "SECURITY",
        "status": status,
        "summary": f"{check_id} {status.lower()}",
        "limitation": f"what {check_id} does not establish",
        "reason": reason,
        "mode": "REAL",
        "duration_ms": 0,
        "evidence_refs": [],
        "detail": detail or {},
    }


class FakeHowlProof:
    """Callable with the adapter's Runner signature."""

    def __init__(self, verdict: str = "CONDITIONALLY_PROVEN") -> None:
        self.verdict = verdict
        self.checks = [check("secrets.scan"), check("research.claims", "NOT_APPLICABLE", "no claim bundle")]
        self.findings: list[dict] = []
        self.rationale = ["research.claims did not apply: no claim bundle"]
        self.limitations = ["research.claims was NOT_APPLICABLE: no claim bundle"]
        self.exit_code: int | None = None
        self.stdout: str | None = None
        self.stderr = ""
        self.raises: BaseException | None = None
        self.tree_digest: str | None = None
        self.corrupt_bundle = False
        self.acquisitions: dict[str, dict | str] = {}
        self.calls: list[list[str]] = []
        self._runs = 0

    def adapter(self) -> HowlProofAdapter:
        return HowlProofAdapter("howlproof-fake", self)

    def commands(self, name: str) -> list[list[str]]:
        return [argv for argv in self.calls if argv[1] == name]

    def __call__(self, argv: list[str], cwd: Path, timeout: float) -> ProcessResult:
        self.calls.append(list(argv))
        if argv[1] == "--version":
            return ProcessResult(0, FAKE_VERSION + "\n", "")
        if self.raises is not None:
            raise self.raises
        if argv[1] == "acquire":
            return self._acquire(argv, cwd)
        return self._evaluate(argv, cwd)

    def _acquire(self, argv: list[str], cwd: Path) -> ProcessResult:
        url = argv[argv.index("--url") + 1]
        store = cwd / argv[argv.index("--store") + 1]
        scripted = self.acquisitions.get(url, "request failed: not scripted")
        if isinstance(scripted, str):
            return ProcessResult(2, "", json.dumps({"error": scripted}) + "\n")
        identifier = "acq-" + hashlib.sha256(url.encode()).hexdigest()[:16]
        record = {
            "id": identifier,
            "kind": "RETRIEVED",
            "requested_url": url,
            "observed_url": url,
            "redirects": [],
            "retrieved_at": "2026-11-16T12:00:00Z",
            "http_status": 200,
            "content_sha256": "c" * 64,
            **scripted,
        }
        (store / "records").mkdir(parents=True, exist_ok=True)
        (store / "records" / f"{identifier}.json").write_text(json.dumps(record), encoding="utf-8")
        return ProcessResult(0, json.dumps(record), "")

    def _evaluate(self, argv: list[str], cwd: Path) -> ProcessResult:
        if self.stdout is not None:
            return ProcessResult(self.exit_code or 0, self.stdout, self.stderr)
        if self.exit_code in (2, 3):
            return ProcessResult(self.exit_code, "", self.stderr or json.dumps({"error": "scripted failure"}))
        target = Path(argv[2])
        evidence_root = cwd / argv[argv.index("--evidence-root") + 1]
        self._runs += 1
        run_id = f"hp-20261116-120000-{self._runs:012d}"
        digest = self.tree_digest or tree_digest(target)
        target_doc = {"root": "<package>", "tree_digest_before": digest, "tree_digest_after": digest}
        result = {
            "schema": "howlproof.result/v1",
            "run_id": run_id,
            "authority": "ADVISORY",
            "version": FAKE_VERSION,
            "artifact": "linkedin-post",
            "target": target_doc,
            "verdict": self.verdict,
            "deciding_rule": "scripted",
            "rationale": list(self.rationale),
            "criteria": [
                {
                    "id": "c",
                    "requirement": "checks_pass",
                    "outcome": "SATISFIED",
                    "detail": "",
                    "optional": False,
                }
            ],
            "checks": list(self.checks),
            "findings": list(self.findings),
            "unresolved_risks": [],
            "limitations": list(self.limitations),
        }
        bundle = evidence_root / run_id
        bundle.mkdir(parents=True)
        files = {
            "result.json": json.dumps(result),
            "target.json": json.dumps(target_doc),
            "config.json": json.dumps({"source": argv[argv.index("--config") + 1]}),
            "checks.jsonl": "".join(json.dumps(item) + "\n" for item in self.checks),
        }
        for name, text in files.items():
            (bundle / name).write_text(text, encoding="utf-8")
        hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
        if self.corrupt_bundle:
            hashes["result.json"] = "0" * 64
        manifest = {
            "schema": "howlproof.run/v1",
            "run_id": run_id,
            "authority": "ADVISORY",
            "version": FAKE_VERSION,
            "implementation_hash": "f" * 64,
            "verdict": self.verdict,
            "file_hashes": hashes,
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        code = VERDICT_EXIT_CODES[self.verdict] if self.exit_code is None else self.exit_code
        return ProcessResult(code, json.dumps({**result, "manifest": manifest, "path": str(bundle)}), "")
