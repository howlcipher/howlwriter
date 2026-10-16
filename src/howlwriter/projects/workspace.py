"""The private project workspace on disk.

    ~/.howlwriter/projects/<project-id>/
        project.json        root path, name, created, settings
        sources.json        inventory: one SourceRecord per file
        evidence.json       the evidence library
        requirements.json   the requirements ledger
        research.json       research and browser history summaries
        questions.json      open questions
        actions.jsonl       browser action audit log (append-only)
        cache/              derived artefacts: OCR'd frames, transcripts (0600)
        browser/profile/    the dedicated browser profile (never the daily browser)
        drafts/             generated outlines, briefs, drafts
        validation.json     the latest validation run

Everything here is private: directories 0700, files 0600, refused inside an
unignored Git worktree (the same guard the voice identity ledger uses).

Authorizing a project authorizes exactly its root folder. Nothing outside it
is scanned, and symlinks are not followed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from howlwriter.projects.models import (
    PROJECT_SCHEMA,
    BrowserAction,
    EvidenceItem,
    Requirement,
    SourceRecord,
)
from howlwriter.voice.identity import privacy

_VALID_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def projects_root() -> Path:
    custom = os.environ.get("HOWLWRITER_PROJECTS_DIR")
    if custom and custom.strip():
        return Path(custom.strip()).expanduser().resolve()
    return Path.home() / ".howlwriter" / "projects"


def project_id_for(root: Path, name: str | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or root.name).lower()).strip("-")[:40] or "project"
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


class ProjectWorkspace:
    def __init__(self, project_id: str, *, root: Path | None = None) -> None:
        if not _VALID_ID.match(project_id or ""):
            raise ValueError(f"invalid project id {project_id!r}")
        self.project_id = project_id
        self.base = Path(root) if root is not None else projects_root()
        self.directory = self.base / project_id

    # --- lifecycle ----------------------------------------------------

    @classmethod
    def create(
        cls, source_root: str | Path, *, name: str | None = None, root: Path | None = None
    ) -> "ProjectWorkspace":
        source = Path(source_root).expanduser()
        if not source.is_dir():
            raise ValueError(f"{source} is not a directory")
        resolved = source.resolve()
        workspace = cls(project_id_for(resolved, name), root=root)
        workspace.ensure()
        meta = workspace.load_meta()
        if not meta:
            from howlwriter.projects.scan import default_exclusions

            workspace.save_meta(
                {
                    "schema": PROJECT_SCHEMA,
                    "project_id": workspace.project_id,
                    "name": name or resolved.name,
                    "root": str(resolved),
                    "created_at": utc_now(),
                    "remote_inference_authorized": False,
                    "exclusions": default_exclusions(),
                    "browser": {"allowed_origins": [], "mode": "off"},
                }
            )
        return workspace

    @classmethod
    def list_projects(cls, root: Path | None = None) -> list[str]:
        base = Path(root) if root is not None else projects_root()
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if (p / "project.json").is_file())

    def exists(self) -> bool:
        return (self.directory / "project.json").is_file()

    def ensure(self) -> Path:
        privacy.ensure_private_dir(self.base)
        privacy.ensure_private_dir(self.directory)
        for sub in ("cache", "drafts", "browser"):
            privacy.ensure_private_dir(self.directory / sub)
        return self.directory

    # --- json helpers -------------------------------------------------

    def _read(self, name: str, default: Any) -> Any:
        path = self.directory / name
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, name: str, payload: Any) -> None:
        self.ensure()
        privacy.write_private_json(self.directory / name, payload)

    def load_meta(self) -> dict:
        return self._read("project.json", {})

    def save_meta(self, meta: dict) -> None:
        self._write("project.json", meta)

    @property
    def source_root(self) -> Path:
        meta = self.load_meta()
        if not meta:
            raise ValueError(f"project {self.project_id!r} does not exist")
        return Path(meta["root"])

    # --- sources ------------------------------------------------------

    def load_sources(self) -> dict[str, SourceRecord]:
        data = self._read("sources.json", {"sources": {}})
        return {k: SourceRecord.from_dict(v) for k, v in data.get("sources", {}).items()}

    def save_sources(self, sources: dict[str, SourceRecord]) -> None:
        self._write("sources.json", {"sources": {k: v.to_dict() for k, v in sorted(sources.items())}})

    # --- evidence -----------------------------------------------------

    def load_evidence(self) -> dict[str, EvidenceItem]:
        data = self._read("evidence.json", {"evidence": {}})
        return {k: EvidenceItem.from_dict(v) for k, v in data.get("evidence", {}).items()}

    def save_evidence(self, evidence: dict[str, EvidenceItem]) -> None:
        self._write("evidence.json", {"evidence": {k: v.to_dict() for k, v in sorted(evidence.items())}})

    # --- requirements -------------------------------------------------

    def load_requirements(self) -> dict[str, Requirement]:
        data = self._read("requirements.json", {"requirements": {}})
        return {k: Requirement.from_dict(v) for k, v in data.get("requirements", {}).items()}

    def save_requirements(self, requirements: dict[str, Requirement]) -> None:
        self._write("requirements.json", {"requirements": {k: v.to_dict() for k, v in requirements.items()}})

    # --- research, questions, validation ---------------------------------

    def load_research(self) -> list[dict]:
        return self._read("research.json", {"entries": []}).get("entries", [])

    def append_research(self, entry: dict) -> None:
        entries = self.load_research()
        entries.append({"at": utc_now(), **entry})
        self._write("research.json", {"entries": entries})

    def load_questions(self) -> list[dict]:
        return self._read("questions.json", {"questions": []}).get("questions", [])

    def save_questions(self, questions: list[dict]) -> None:
        self._write("questions.json", {"questions": questions})

    def save_validation(self, payload: dict) -> None:
        self._write("validation.json", {"at": utc_now(), **payload})

    def load_validation(self) -> dict:
        return self._read("validation.json", {})

    # --- browser actions (append-only) ---------------------------------

    def append_action(self, action: BrowserAction) -> None:
        self.ensure()
        path = self.directory / "actions.jsonl"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        privacy.write_private_text(path, existing + json.dumps(action.to_dict(), sort_keys=True) + "\n")

    def load_actions(self) -> list[BrowserAction]:
        path = self.directory / "actions.jsonl"
        if not path.is_file():
            return []
        return [
            BrowserAction.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    # --- paths ------------------------------------------------------------

    def cache_dir(self, *parts: str) -> Path:
        path = self.directory.joinpath("cache", *parts)
        privacy.ensure_private_dir(path)
        return path

    def resolve_source(self, relative: str) -> Path:
        """Absolute path of a source, refusing anything outside the root."""
        root = self.source_root.resolve()
        path = (root / relative).resolve()
        if root != path and root not in path.parents:
            raise ValueError("refusing a path outside the project root")
        return path
