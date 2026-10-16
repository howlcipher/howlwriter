"""Shared operations behind the `howlwriter project` CLI and the web routes."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from howlwriter.projects import models as m
from howlwriter.projects.workspace import ProjectWorkspace, project_id_for, utc_now


def resolve(reference: str) -> ProjectWorkspace:
    """A project by id, or by the folder it was opened from."""
    candidate = Path(reference).expanduser()
    if candidate.is_dir():
        workspace = ProjectWorkspace(project_id_for(candidate.resolve()))
        if workspace.exists():
            return workspace
        raise ValueError(f"no project has been opened for {candidate}; run `howlwriter project open` first")
    workspace = ProjectWorkspace(reference)
    if not workspace.exists():
        known = ", ".join(ProjectWorkspace.list_projects()) or "none"
        raise ValueError(f"no project {reference!r} (known: {known})")
    return workspace


def summary(workspace: ProjectWorkspace) -> dict:
    meta = workspace.load_meta()
    sources = [s for s in workspace.load_sources().values() if s.present]
    evidence = workspace.load_evidence()
    requirements = workspace.load_requirements()
    actions = workspace.load_actions()
    return {
        "project_id": workspace.project_id,
        "name": meta.get("name"),
        "root": meta.get("root"),
        "created_at": meta.get("created_at"),
        "scan_state": {k: v for k, v in (meta.get("scan_state") or {}).items() if k != "report"},
        "last_scan": (meta.get("scan_state") or {}).get("report", {}),
        "remote_inference_authorized": bool(meta.get("remote_inference_authorized")),
        "sources": len(sources),
        "sources_by_category": dict(Counter(s.category for s in sources)),
        "sources_by_status": dict(Counter(s.status for s in sources)),
        "evidence": len(evidence),
        "evidence_by_status": dict(Counter(e.status for e in evidence.values())),
        "requirements": len(requirements),
        "requirements_by_status": dict(Counter(r.status for r in requirements.values())),
        "browser_actions": len(actions),
        "open_questions": len(workspace.load_questions()),
        "validation": {k: workspace.load_validation().get(k) for k in ("at", "verdict", "issue_counts")},
    }


def authorize_remote(workspace: ProjectWorkspace, allow: bool) -> dict:
    meta = workspace.load_meta()
    meta["remote_inference_authorized"] = bool(allow)
    meta.setdefault("authorizations", []).append({"at": utc_now(), "remote_inference": bool(allow)})
    workspace.save_meta(meta)
    return {"remote_inference_authorized": bool(allow)}


def compare_captures(workspace: ProjectWorkspace, first: str, second: str) -> dict:
    from howlwriter.projects.adapters.pcap import compare

    sources = workspace.load_sources()
    evidence = workspace.load_evidence()

    def find(ref: str) -> m.SourceRecord:
        hits = [
            s
            for s in sources.values()
            if s.present and (s.source_id == ref or s.path == ref or Path(s.path).name == ref)
        ]
        if len(hits) != 1:
            raise ValueError(f"{ref!r} matches {len(hits)} sources; give the path relative to the project")
        if hits[0].category != m.PACKET_CAPTURE:
            raise ValueError(f"{hits[0].path} is not a packet capture")
        return hits[0]

    a, b = find(first), find(second)

    def items(record):
        return [e.to_dict() for e in evidence.values() if e.source_id == record.source_id]

    findings = compare(items(a), items(b), before_name=Path(a.path).name, after_name=Path(b.path).name)
    return {
        "before": a.path,
        "after": b.path,
        "findings": findings,
        "status": m.DERIVED,
        "method": "deterministic comparison of extracted packet findings",
    }
