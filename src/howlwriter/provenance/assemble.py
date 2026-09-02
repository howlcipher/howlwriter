"""Assembling a run's provenance, and writing it where it stays private.

Two rules govern where these files land.

They are local. A provenance record for an outline run contains the user's own
sentences, their claims, and -- at full level -- every prompt this system built
around them. That is exactly what makes it useful and exactly what makes it
unsafe to publish by default. Nothing here writes to a shared location, and the
sidecar paths sit beside the artifact the user already chose to write.

They are opt-in. Recording always happens; persisting does not. `--provenance`
asks for a record, and the level decides how much of the prompt survives into
it. A user who never asks gets the run record HowlWriter has always kept and no
new files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from howlwriter.domain.generation_provenance import (
    LEVEL_FULL,
    LEVEL_SUMMARY,
    ContributionSummary,
    GenerationProvenance,
    redact,
    sha256_text,
)
from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.outline import NodeKind, Outline
from howlwriter.provenance.manifest import render_manifest


@dataclass
class ProvenanceArtifacts:
    """Paths actually written, so a caller can report them truthfully."""

    provenance_json: Path | None = None
    manifest_text: Path | None = None
    outline_yaml: Path | None = None
    sources_json: Path | None = None

    def written(self) -> list[Path]:
        return [
            p for p in (
                self.provenance_json,
                self.manifest_text,
                self.outline_yaml,
                self.sources_json,
            ) if p is not None
        ]


def summarize_outline(outline: Outline) -> dict[str, Any]:
    """Counts and ids only -- the outline text itself lives in its own sidecar."""
    return {
        "schema": outline.schema,
        "title": outline.title,
        "topic": outline.topic,
        "mode": outline.mode,
        "target_words": outline.target_words,
        "max_words": outline.max_words,
        "enforce_order": outline.enforce_order,
        "node_count": len(outline.all_nodes()),
        "nodes_by_kind": {
            kind.value: len(outline.nodes_of(kind))
            for kind in NodeKind
            if outline.nodes_of(kind)
        },
        "required_point_ids": [n.id for n in outline.required_points()],
        "preserved_ids": [n.id for n in outline.preserved()],
        "research_questions": len(outline.research),
    }


def build_contribution(
    outline: Outline | None,
    *,
    coverage: dict[str, Any] | None,
    artifact_text: str,
    added_claims: list[dict[str, Any]] | None = None,
    gaps: list[str] | None = None,
    research_grounded: int = 0,
    unsupported: int = 0,
) -> ContributionSummary:
    """Counts of supplied versus represented. Never a percentage."""
    summary = ContributionSummary(
        artifact_words=len(artifact_text.split()),
        model_added_claims=len(added_claims or []),
        gaps_reported=len(gaps or []),
        research_grounded_additions=research_grounded,
        unsupported_additions=unsupported,
    )
    if outline is not None:
        summary.claims_supplied = len(outline.claims())
        summary.required_points_supplied = len(outline.required_points())
        summary.preserved_supplied = len(outline.preserved())
        summary.examples_supplied = len(
            outline.nodes_of(NodeKind.EXAMPLE, NodeKind.EXPERIENCE)
        )
        summary.voice_seeds_supplied = len(outline.voice_seeds())
        summary.user_words_supplied = outline.supplied_words()
    if coverage:
        summary.required_points_represented = coverage.get("required_represented", 0)
        summary.preserved_retained = coverage.get("preserved_retained", 0)
        summary.examples_represented = coverage.get("examples_represented", 0)
        # A claim counts as represented when its node did; the coverage report
        # already decided that per node, so it is read back rather than re-judged.
        represented = {
            f["node_id"] for f in coverage.get("findings", [])
            if f.get("status") == "PRESENT"
        }
        if outline is not None:
            summary.claims_represented = sum(
                1 for node in outline.claims() if node.id in represented
            )
    return summary


def _redact_tree(value: Any, mask_paths: bool) -> Any:
    """Redact every string anywhere in a nested structure.

    Redacting only the prompt fields was not enough. A coverage finding echoes
    the user's preserved text back into the record verbatim, so a credential
    that appeared in a preserved passage survived at `coverage.findings[].text`
    while the prompt that carried the same string was cleaned. Anything that
    can hold free text has to be covered, including fields added later, so this
    walks the whole tree rather than naming carriers one at a time.
    """
    if isinstance(value, str):
        return redact(value, mask_paths=mask_paths)
    if isinstance(value, dict):
        return {k: _redact_tree(v, mask_paths) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_tree(v, mask_paths) for v in value]
    return value


def finalize(
    provenance: GenerationProvenance,
    *,
    level: str,
    mask_paths: bool = False,
) -> GenerationProvenance:
    """Apply the requested level and redaction to a completed record.

    Returns a copy: the in-memory record keeps everything so a caller can write
    a summary sidecar and still render a full manifest in the same run.
    """
    reduced = GenerationProvenance.from_dict(provenance.to_dict())
    reduced.provenance_level = level
    reduced.calls = [
        call.redacted(level=level, mask_paths=mask_paths) for call in provenance.calls
    ]
    reduced.completed_at = provenance.completed_at or datetime.now(timezone.utc).isoformat()

    # Everything outside the calls -- coverage findings, gaps, warnings, added
    # claims, origin excerpts -- goes through the same scrub. The calls are
    # excluded because `redacted` has already handled them at the right level,
    # and re-running it would undo the summary-level suppression.
    payload = reduced.to_dict()
    calls = payload.pop("calls")
    cleaned = _redact_tree(payload, mask_paths)
    cleaned["calls"] = calls
    return GenerationProvenance.from_dict(cleaned)


def write_artifacts(
    provenance: GenerationProvenance,
    artifact_path: Path | str,
    *,
    level: str = LEVEL_SUMMARY,
    outline: Outline | None = None,
    sources: Any = None,
    mask_paths: bool = False,
) -> ProvenanceArtifacts:
    """Write the sidecars beside the artifact. Local, private, never published."""
    target = Path(artifact_path)
    stem = target.with_suffix("")
    written = ProvenanceArtifacts()
    record = finalize(provenance, level=level, mask_paths=mask_paths)

    written.provenance_json = Path(f"{stem}.provenance.json")
    atomic_write_text(written.provenance_json, record.to_json())

    written.manifest_text = Path(f"{stem}.manifest.txt")
    atomic_write_text(written.manifest_text, render_manifest(record) + "\n")

    if outline is not None:
        written.outline_yaml = Path(f"{stem}.outline.yaml")
        atomic_write_text(
            written.outline_yaml,
            "# Copy of the outline this artifact was written from.\n"
            "# Credentials are redacted; the original file on disk is unchanged.\n"
            + _redact_tree_yaml(outline.to_dict(), mask_paths),
        )

    if sources:
        written.sources_json = Path(f"{stem}.sources.json")
        payload = sources if isinstance(sources, (list, dict)) else [
            s.to_dict() if hasattr(s, "to_dict") else str(s) for s in sources
        ]
        atomic_write_text(written.sources_json, json.dumps(payload, indent=2, default=str))

    return written


def provenance_path(run_id: str) -> Path:
    """Where a run's provenance lives when it is kept.

    Beside the diagnostic run records, for the same reason those live there:
    outside any repository, under the user's home, private by default. A
    provenance record is more sensitive than a run record, not less.
    """
    from howlwriter.diagnostic.run_record import get_default_runs_dir

    return get_default_runs_dir() / f"{run_id}.provenance.json"


def save_provenance(
    provenance: GenerationProvenance,
    *,
    level: str = LEVEL_SUMMARY,
    mask_paths: bool = False,
) -> Path | None:
    """Persist a run's provenance next to its run record.

    Never raises. Diagnostics that can abort a writing job are worse than
    diagnostics that go missing, which is the rule `RunRecord.save` already
    follows.
    """
    try:
        if not provenance.run_id:
            return None
        target = provenance_path(provenance.run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        record = finalize(provenance, level=level, mask_paths=mask_paths)
        atomic_write_text(target, record.to_json())
        return target
    except Exception:                                   # pragma: no cover
        return None


def load_provenance(run_id: str) -> GenerationProvenance | None:
    """Read a saved record back, or None when the run kept none."""
    target = provenance_path(run_id)
    if not target.is_file():
        return None
    try:
        return GenerationProvenance.from_dict(
            json.loads(target.read_text(encoding="utf-8"))
        )
    except Exception:
        return None


def _redact_tree_yaml(data: dict[str, Any], mask_paths: bool) -> str:
    import yaml as _yaml

    return _yaml.safe_dump(
        _redact_tree(data, mask_paths), sort_keys=False, allow_unicode=True
    )


def hash_or_empty(text: str | None) -> str:
    return sha256_text(text) if text else ""


__all__ = [
    "LEVEL_FULL",
    "LEVEL_SUMMARY",
    "load_provenance",
    "provenance_path",
    "save_provenance",
    "ProvenanceArtifacts",
    "build_contribution",
    "finalize",
    "hash_or_empty",
    "summarize_outline",
    "write_artifacts",
]
