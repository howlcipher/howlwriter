"""Structured, local-first run records for continuous dogfooding and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any

from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.serialization import DataClassSerializationMixin


def generate_run_id() -> str:
    """Generates a sortable, unique run identifier: hw-YYYYMMDD-HHMMSS-<6char_hex>."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    rand = secrets.token_hex(3)
    return f"hw-{ts}-{rand}"


def get_default_runs_dir() -> Path:
    """Returns directory for durable local dogfood run records."""
    custom = os.environ.get("HOWLWRITER_RUNS_DIR")
    if custom and custom.strip():
        return Path(custom.strip()).expanduser().resolve()
    return Path.home() / ".howlwriter" / "runs"


def compute_sha256(text: str) -> str:
    """Computes SHA-256 hash of text without storing the text itself."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_failure(error: Exception | str) -> str:
    """Deterministically classifies failure into standard diagnostic categories."""
    msg = str(error).lower()
    if "timeout" in msg or "timed out" in msg:
        return "PROVIDER_TIMEOUT"
    if "empty" in msg or "unparseable" in msg:
        return "PROVIDER_EMPTY_RESPONSE"
    if "exited with code" in msg or "exit code" in msg or "terminated" in msg:
        return "PROVIDER_NONZERO_EXIT"
    if "exceeds safe single-pass limit" in msg:
        return "DOCUMENT_SIZE_EXCEEDED"
    if "not configured" in msg or "unconfigured" in msg:
        return "CONFIGURATION_FAILURE"
    write_keywords = ("permission", "io", "disk", "space", "failed to write", "destination")
    if "write" in msg and any(kw in msg for kw in write_keywords):
        return "OUTPUT_WRITE_FAILURE"
    if "semantic drift" in msg:
        return "SEMANTIC_DRIFT"
    if "meaning review" in msg or "meaning preservation" in msg:
        return "MEANING_REVIEW_FAILURE"
    if "parse" in msg or "yaml" in msg or "json" in msg:
        return "STRUCTURED_PARSE_FAILURE"
    if "interrupt" in msg or isinstance(error, KeyboardInterrupt):
        return "INTERRUPTED"
    if isinstance(error, (FileNotFoundError, ValueError, TypeError)):
        return "USER_ERROR"
    return "ENGINEERING_FAILURE"


def get_howlwriter_version() -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version("howlwriter")
    except Exception:
        return "0.1.0"


def get_howlplane_version() -> str | None:
    try:
        import importlib.metadata
        return importlib.metadata.version("howlplane")
    except Exception:
        pass
    try:
        import howlplane
        return getattr(howlplane, "__version__", None)
    except Exception:
        pass
    return None


def get_git_revision(repo_dir: Path | str | None = None) -> str | None:
    try:
        import subprocess
        cwd = str(repo_dir) if repo_dir else str(Path(__file__).parents[3])
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None


def get_howlplane_git_revision() -> str | None:
    env_root = os.environ.get("HOWLPLANE_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.is_dir() and (p / ".git").exists():
            rev = get_git_revision(p)
            if rev:
                return rev
    try:
        import howlplane

        if hasattr(howlplane, "__file__") and howlplane.__file__:
            pkg_dir = Path(howlplane.__file__).resolve().parent
            for candidate in [pkg_dir, pkg_dir.parent]:
                if (candidate / ".git").exists():
                    rev = get_git_revision(candidate)
                    if rev:
                        return rev
    except Exception:
        pass
    return None


@dataclass
class RunRecord(DataClassSerializationMixin):
    """Structured local diagnostic record for a HowlWriter execution."""

    run_id: str = field(default_factory=generate_run_id)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    command: str = "humanize"
    howlwriter_version: str = field(default_factory=get_howlwriter_version)
    howlplane_version: str | None = field(default_factory=get_howlplane_version)
    git_revision: str | None = field(default_factory=get_git_revision)
    howlplane_git_revision: str | None = field(
        default_factory=get_howlplane_git_revision
    )
    writing_mode: str | None = None
    success: bool = True
    status: str = "READY"  # READY | NEEDS_REVIEW | BLOCKED | REJECTED

    # Provider & Reviewer metadata
    humanizer_provider: str | None = None
    humanizer_model: str | None = None
    meaning_reviewer_provider: str | None = None
    meaning_reviewer_model: str | None = None
    reviewer_independence: str | None = None

    # Deterministic & Semantic findings
    lint_before_count: int | None = None
    lint_after_count: int | None = None
    banned_words: int | None = None
    ai_style_warnings: int | None = None
    meaning_preservation: str | None = None
    semantic_meaning_status: str | None = None
    changes_count: int = 0

    # Constraint-compliance signals (status/boolean only, mirroring the
    # granularity of the fields already mirrored above)
    length_hard_ceiling_exceeded: bool = False
    requirements_coverage_status: str | None = None
    redundancy_flagged: bool = False
    identifier_grounding_flagged: bool = False
    source_freshness_flagged: bool = False
    consistency_review_status: str | None = None

    # Timing metrics
    humanizer_duration_seconds: float | None = None
    meaning_reviewer_duration_seconds: float | None = None
    total_duration_seconds: float | None = None

    # Execution flags
    fallback_occurred: bool = False
    retry_occurred: bool = False

    # Privacy-conscious document metadata (NO FULL PROSE ARCHIVED)
    input_path: str | None = None
    input_chars: int = 0
    input_sha256: str | None = None
    output_path: str | None = None
    output_chars: int | None = None
    output_sha256: str | None = None

    # Error & Failure evidence
    failure_category: str | None = None
    error_message: str | None = None
    exit_code: int = 0

    # Correlation
    howlplane_task_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def deterministic_meaning_result(self) -> str | None:
        return self.meaning_preservation

    @property
    def semantic_meaning_result(self) -> str | None:
        return self.semantic_meaning_status

    @property
    def input_size(self) -> int:
        return self.input_chars

    @property
    def output_size(self) -> int | None:
        return self.output_chars

    @property
    def humanizer_duration(self) -> float | None:
        return self.humanizer_duration_seconds

    @property
    def review_duration(self) -> float | None:
        return self.meaning_reviewer_duration_seconds

    @property
    def total_duration(self) -> float | None:
        return self.total_duration_seconds

    @property
    def review_provider(self) -> str | None:
        return self.meaning_reviewer_provider

    @property
    def review_model(self) -> str | None:
        return self.meaning_reviewer_model

    def save(self, runs_dir: Path | str | None = None) -> Path | None:
        """Saves run record locally as JSON. Never raises to prevent aborting user task."""
        target_dir = Path(runs_dir) if runs_dir else get_default_runs_dir()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            record_path = target_dir / f"{self.run_id}.json"
            content = json.dumps(self.to_dict(), indent=2)
            atomic_write_text(record_path, content)
            return record_path
        except Exception as exc:
            # Diagnostics failure must NEVER fail the user's primary writing job
            print(
                f"warning: failed to save diagnostic run record {self.run_id}: {exc}",
                file=sys.stderr,
            )
            return None

    @classmethod
    def load(
        cls, run_id: str, runs_dir: Path | str | None = None
    ) -> RunRecord | None:
        """Loads a run record from disk by run_id or file path."""
        target_dir = Path(runs_dir) if runs_dir else get_default_runs_dir()
        file_path = (
            Path(run_id)
            if run_id.endswith(".json") and Path(run_id).is_file()
            else target_dir / f"{run_id}.json"
        )
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None

    @classmethod
    def list_records(
        cls, limit: int = 20, runs_dir: Path | str | None = None
    ) -> list[RunRecord]:
        """Lists recent run records sorted by filename descending (newest first)."""
        target_dir = Path(runs_dir) if runs_dir else get_default_runs_dir()
        if not target_dir.exists():
            return []
        records = []
        for file_path in sorted(target_dir.glob("*.json"), reverse=True)[:limit]:
            record = cls.load(file_path.name.replace(".json", ""), runs_dir=target_dir)
            if record is not None:
                records.append(record)
        return records
