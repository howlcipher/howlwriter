"""Conservative retention for ``~/.howlwriter/runs``.

Nothing here runs automatically. Pruning only ever considers regular files
sitting directly inside the resolved runs directory whose names are exactly
HowlWriter run artifacts (``hw-YYYYMMDD-HHMMSS-xxxxxx.json`` and its
``.provenance.json`` sidecar). Anything else in the directory is invisible to
it, symlinks are refused, and age comes from the timestamp in the run id so
the result does not depend on filesystem mtimes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN_FILE_RE = re.compile(r"^(hw-(\d{8})-(\d{6})-[0-9a-f]{6})(\.provenance)?\.json$")


@dataclass
class PruneCandidate:
    run_id: str
    timestamp: datetime
    files: list[str]  # file names inside the runs dir, sorted
    reason: str


@dataclass
class PrunePlan:
    runs_dir: Path
    total_runs: int = 0
    candidates: list[PruneCandidate] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # unsafe entries left untouched

    @property
    def kept_runs(self) -> int:
        return self.total_runs - len(self.candidates)

    @property
    def files_to_remove(self) -> list[str]:
        return sorted(f for c in self.candidates for f in c.files)


def _run_timestamp(date_part: str, time_part: str) -> datetime | None:
    try:
        return datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def plan_prune(
    runs_dir: Path | str,
    *,
    older_than_days: int | None = None,
    keep_latest: int | None = None,
    now: datetime | None = None,
) -> PrunePlan:
    """Decide what would be removed. Does not touch the filesystem.

    With both criteria, a run is pruned only if it is BOTH older than the
    cutoff and outside the newest ``keep_latest`` runs.
    """
    if older_than_days is None and keep_latest is None:
        raise ValueError("specify older_than_days and/or keep_latest")
    if older_than_days is not None and older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")
    if keep_latest is not None and keep_latest < 0:
        raise ValueError("keep_latest must be >= 0")

    directory = Path(runs_dir).resolve()
    plan = PrunePlan(runs_dir=directory)
    if not directory.is_dir():
        return plan

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days) if older_than_days is not None else None

    runs: dict[str, dict] = {}
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        m = RUN_FILE_RE.match(entry.name)
        if not m:
            continue  # not ours: never listed, never touched
        if entry.is_symlink() or not entry.is_file() or entry.resolve().parent != directory:
            plan.skipped.append(entry.name)
            continue
        ts = _run_timestamp(m.group(2), m.group(3))
        if ts is None:
            plan.skipped.append(entry.name)
            continue
        info = runs.setdefault(m.group(1), {"ts": ts, "files": []})
        info["files"].append(entry.name)

    ordered = sorted(runs.items(), key=lambda kv: kv[0], reverse=True)  # newest first
    plan.total_runs = len(ordered)
    for rank, (run_id, info) in enumerate(ordered):
        reasons = []
        beyond_keep = keep_latest is not None and rank >= keep_latest
        too_old = cutoff is not None and info["ts"] < cutoff
        if keep_latest is not None and cutoff is not None:
            doomed = beyond_keep and too_old
        else:
            doomed = beyond_keep or too_old
        if not doomed:
            continue
        if too_old:
            reasons.append(f"older than {older_than_days} days")
        if beyond_keep:
            reasons.append(f"outside newest {keep_latest}")
        plan.candidates.append(
            PruneCandidate(run_id, info["ts"], sorted(info["files"]), " and ".join(reasons))
        )
    plan.candidates.sort(key=lambda c: c.run_id)
    return plan


def execute_prune(plan: PrunePlan) -> list[str]:
    """Delete the planned files. Re-validates every path immediately before
    unlinking; returns the names actually removed."""
    removed: list[str] = []
    for name in plan.files_to_remove:
        if not RUN_FILE_RE.match(name):
            continue
        path = plan.runs_dir / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != plan.runs_dir:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(name)
    return removed
