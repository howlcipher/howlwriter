"""Inventory, classify, and extract a project folder -- incrementally and resumably.

The scan walks exactly the project root: no symlinks are followed, excluded
directory names are never entered, hidden files and noise directories are
skipped, and the file count is bounded. Each file is handled in isolation: a
malformed PDF, a corrupt capture, or a crashed decoder becomes that file's
`failed` status and the scan moves on.

Incremental: a file whose size, modification time, and adapter version are
unchanged keeps its previous results and is not re-read. Checkpointed: the
inventory and evidence library are saved after every file, so an interrupted
scan resumes where it stopped, and long media is cached by content hash.

Duplicates (identical content at two paths) are extracted once; the second
copy points at the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from typing import Callable

from howlwriter.projects import classify as cls
from howlwriter.projects import models as m
from howlwriter.projects.adapters import ADAPTER_VERSION, AdapterResult
from howlwriter.projects.resources import HeavyWorker, ResourcePolicy
from howlwriter.projects.workspace import ProjectWorkspace, utc_now
from howlwriter.voice.identity.exclusions import ExclusionPolicy

MAX_FILES = 2_000
MAX_DEPTH = 12
#: Per-format byte ceilings. Media is streamed to ffmpeg, never read whole.
SIZE_LIMITS = {
    "document": 60 * 1024 * 1024,
    "image": 40 * 1024 * 1024,
    "pcap": 500 * 1024 * 1024,
    "media": 4 * 1024 * 1024 * 1024,
    "data": 30 * 1024 * 1024,
}
DATA_EXCERPT_LINES = 40
#: Browser profile and cache directories: never prose or evidence, often sensitive
#: (cookies, session storage), and frequently thousands of files.
BROWSER_DATA_DIRS = {
    "cache",
    "code cache",
    "gpucache",
    "service worker",
    "indexeddb",
    "local storage",
    "session storage",
    "blob_storage",
    "crashpad",
    "shadercache",
    "grshadercache",
    "dawncache",
    "dawngraphitecache",
}
_PROFILE_MARKERS = ("Local State", "Cookies", "Preferences", "Login Data")


def _is_browser_profile(path: Path) -> bool:
    """A Chromium/Firefox user-data or profile directory."""
    try:
        if (path / "Local State").is_file() or (path / "cookies.sqlite").is_file():
            return True
        return sum((path / marker).exists() for marker in _PROFILE_MARKERS) >= 2
    except OSError:
        return False


def default_exclusions() -> list[str]:
    """Exclusions every local voice identity configured, so a project folder
    inside a personal corpus root never enters a directory its owner barred."""
    names: list[str] = []
    try:
        from howlwriter.voice.identity.store import IdentityStore

        for identity in IdentityStore.list_identities():
            names += IdentityStore(identity).load_config().exclusions.names
    except Exception:
        pass
    return sorted(set(names))


@dataclass
class ScanReport:
    project_id: str
    files: int = 0
    new_or_changed: int = 0
    unchanged: int = 0
    removed: int = 0
    duplicates: int = 0
    failed: int = 0
    evidence_items: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    interrupted: bool = False
    workload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _family(suffix: str) -> str:
    if suffix in cls.PCAP_SUFFIXES:
        return "pcap"
    if suffix in cls.IMAGE_SUFFIXES:
        return "image"
    if suffix in cls.VIDEO_SUFFIXES or suffix in cls.AUDIO_SUFFIXES:
        return "media"
    if suffix in cls.DATA_SUFFIXES:
        return "data"
    if suffix in cls.DOCUMENT_SUFFIXES:
        return "document"
    return "other"


def walk(root: Path, policy: ExclusionPolicy, skipped: dict[str, int]) -> list[tuple[str, os.stat_result]]:
    """(relative POSIX path, lstat) of every regular file under root, safely."""
    found: list[tuple[str, os.stat_result]] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            skipped["unreadable_directory"] = skipped.get("unreadable_directory", 0) + 1
            continue
        for entry in entries:
            if entry.name.startswith("."):
                skipped["hidden"] = skipped.get("hidden", 0) + 1
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                skipped["unstattable"] = skipped.get("unstattable", 0) + 1
                continue
            if stat.S_ISLNK(info.st_mode):
                skipped["symlink"] = skipped.get("symlink", 0) + 1
                continue
            if stat.S_ISDIR(info.st_mode):
                if policy.excludes(entry.name):
                    skipped["excluded_directory"] = skipped.get("excluded_directory", 0) + 1
                elif entry.name.casefold() in BROWSER_DATA_DIRS or _is_browser_profile(Path(entry.path)):
                    skipped["browser_profile_or_cache"] = skipped.get("browser_profile_or_cache", 0) + 1
                elif policy.is_noise(entry.name):
                    skipped["noise_directory"] = skipped.get("noise_directory", 0) + 1
                elif depth + 1 > MAX_DEPTH:
                    skipped["too_deep"] = skipped.get("too_deep", 0) + 1
                else:
                    stack.append((Path(entry.path), depth + 1))
                continue
            if not stat.S_ISREG(info.st_mode):
                skipped["special_file"] = skipped.get("special_file", 0) + 1
                continue
            if len(found) >= MAX_FILES:
                skipped["over_file_limit"] = skipped.get("over_file_limit", 0) + 1
                continue
            found.append((Path(entry.path).relative_to(root).as_posix(), info))
    return sorted(found)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _gained_capability(previous: m.SourceRecord, now: dict) -> bool:
    """True when an extraction step that was off last time is available now and would matter.

    A PDF only benefits from OCR when it had image-only pages.
    """
    before = previous.metadata.get("options")
    if before is None:  # recorded before options were tracked: infer from the adapter that ran
        method = previous.adapter or ""
        before = {"ocr": "ocr" in method or previous.status == "extracted", "transcribe": "whisper" in method,
                  "frames": "frames" in method}
    if previous.suffix == ".pdf" and not previous.metadata.get("visual_pages"):
        return False
    return any(enabled and not before.get(name) for name, enabled in now.items())


def source_id_for(relative: str) -> str:
    return "src-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]


def evidence_id_for(source_id: str, item: dict) -> str:
    key = json.dumps([source_id, item.get("kind"), item.get("locator")], sort_keys=True, default=str)
    return "ev-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _extract_data(path: Path, data: bytes) -> AdapterResult:
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    result = AdapterResult(method="text-lines", text=text, metadata={"lines": len(lines)})
    for start in range(0, min(len(lines), 4000), DATA_EXCERPT_LINES):
        block = [line for line in lines[start:start + DATA_EXCERPT_LINES] if line.strip()]
        if not block:
            continue
        result.items.append(
            {
                "kind": "data_lines",
                "source_type": "data",
                "method": "text-lines",
                "status": "directly_observed",
                "location": f"lines {start + 1}–{min(start + DATA_EXCERPT_LINES, len(lines))}",
                "locator": {"lines": [start + 1, min(start + DATA_EXCERPT_LINES, len(lines))]},
                "excerpt": "\n".join(block)[:900],
                "confidence": "high",
            }
        )
    if len(lines) > 4000:
        result.warnings.append(f"only the first 4000 of {len(lines)} lines were indexed")
    return result


class Extractors:
    """The adapters, constructed lazily and shareable across scans (and tests)."""

    def __init__(
        self,
        *,
        ocr=None,
        transcriber=None,
        tshark=None,
        media_frames: bool = True,
        policy: ResourcePolicy | None = None,
    ) -> None:
        self._ocr = ocr
        self._transcriber = transcriber
        self._tshark = tshark
        self.media_frames = media_frames
        self.policy = policy or ResourcePolicy()
        self._worker = None

    @property
    def worker(self) -> HeavyWorker:
        """One governed worker shared by OCR and transcription for this scan."""
        if self._worker is None:
            self._worker = HeavyWorker(self.policy)
        return self._worker

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()
            self._worker = None

    def options(self, suffix: str) -> dict[str, bool]:
        """Which optional extraction steps apply to this format in this scan."""
        family = _family(suffix)
        if family == "image" or suffix == ".pdf":
            return {"ocr": bool(getattr(self.ocr, "available", False))}
        if family == "media":
            options = {"transcribe": bool(getattr(self.transcriber, "available", False))}
            if suffix in cls.VIDEO_SUFFIXES:
                options["frames"] = bool(self.media_frames and getattr(self.ocr, "available", False))
            return options
        return {}

    @property
    def ocr(self):
        if self._ocr is None:
            from howlwriter.projects.adapters.images import OcrEngine

            self._ocr = OcrEngine(worker=self.worker)
        return self._ocr

    @property
    def tshark(self):
        if self._tshark is None:
            from howlwriter.projects.adapters.pcap import TShark

            self._tshark = TShark(policy=self.policy)
        return self._tshark

    @property
    def transcriber(self):
        if self._transcriber is None:
            from howlwriter.projects.adapters.media import Transcriber

            self._transcriber = Transcriber(worker=self.worker, policy=self.policy)
        return self._transcriber

    def run(
        self, workspace: ProjectWorkspace, path: Path, relative: str, suffix: str, sha: str
    ) -> AdapterResult:
        family = _family(suffix)
        if family == "pcap":
            from howlwriter.projects.adapters.pcap import analyze

            return analyze(path, tshark=self.tshark)
        if family == "media":
            from howlwriter.projects.adapters.media import extract_media

            kind = "audio" if suffix in cls.AUDIO_SUFFIXES else "video"
            return extract_media(
                path,
                sha256=sha,
                cache_dir=workspace.cache_dir("media"),
                transcriber=self.transcriber,
                ocr=self.ocr,
                frames=self.media_frames,
                kind=kind,
            )
        data = path.read_bytes()
        if family == "image":
            from howlwriter.projects.adapters.images import extract_image

            return extract_image(path, data, ocr=self.ocr)
        if family == "data":
            return _extract_data(path, data)
        if suffix == ".pdf":
            from howlwriter.projects.adapters.documents import extract_pdf

            return extract_pdf(path, data, cache_dir=workspace.cache_dir("pdf", sha[:16]), ocr=self.ocr)
        from howlwriter.projects.adapters.documents import extract_text_document

        return extract_text_document(path, data)


def scan_project(
    workspace: ProjectWorkspace,
    *,
    extractors: Extractors | None = None,
    force: bool = False,
    only: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ScanReport:
    """Scan (or rescan) a project. Returns a report; state is saved as it goes."""
    meta = workspace.load_meta()
    owned = extractors is None
    extractors = extractors or Extractors(policy=ResourcePolicy.from_dict(meta.get("resources")))
    try:
        return _scan(
            workspace, meta, extractors, force=force, only=only, progress=progress, should_stop=should_stop
        )
    finally:
        if owned:
            extractors.close()


def _scan(workspace, meta, extractors, *, force, only, progress, should_stop) -> ScanReport:
    started = time.monotonic()
    root = workspace.source_root
    if not root.is_dir():
        raise FileNotFoundError(f"project folder {root} is not available")
    policy = ExclusionPolicy(additional=tuple(meta.get("exclusions", [])))
    report = ScanReport(project_id=workspace.project_id)
    sources = workspace.load_sources()
    evidence = workspace.load_evidence()
    meta["scan_state"] = {"status": "running", "started_at": utc_now()}
    workspace.save_meta(meta)

    files = walk(root, policy, report.skipped)
    report.files = len(files)
    seen_ids: set[str] = set()
    by_hash: dict[str, str] = {
        r.sha256: sid for sid, r in sources.items() if r.sha256 and r.status not in ("duplicate", "failed")
    }
    for relative, info in files:
        source_id = source_id_for(relative)
        seen_ids.add(source_id)
        if only and relative not in only and source_id not in only:
            continue
        if should_stop and should_stop():
            report.interrupted = True
            break
        suffix = Path(relative).suffix.lower()
        previous = sources.get(source_id)
        unchanged = (
            previous is not None
            and not force
            and previous.present
            and previous.size == info.st_size
            and abs(previous.mtime - info.st_mtime) < 1e-6
            and previous.analysis_version == ADAPTER_VERSION
            and previous.status not in ("pending", "duplicate")
            and not _gained_capability(previous, extractors.options(suffix))
        )
        if unchanged:
            report.unchanged += 1
            continue
        report.new_or_changed += 1
        if progress:
            progress(relative)
        record = previous or m.SourceRecord(
            source_id=source_id, path=relative, suffix=suffix, size=0, mtime=0.0
        )
        record.path, record.suffix, record.size, record.mtime = relative, suffix, info.st_size, info.st_mtime
        record.present, record.warnings, record.analysis_version = True, [], ADAPTER_VERSION
        for stale in [eid for eid, item in evidence.items() if item.source_id == source_id]:
            del evidence[stale]
        path = root / relative
        family = _family(suffix)
        try:
            limit = SIZE_LIMITS.get(family)
            if family == "other":
                record.status, record.status_reason, record.adapter = (
                    "skipped",
                    f"no adapter for {suffix or 'this file'}",
                    "",
                )
                result = AdapterResult(status="skipped")
            elif limit and info.st_size > limit:
                record.status, record.status_reason = (
                    "skipped",
                    f"larger than the {limit // (1024 * 1024)} MB limit",
                )
                result = AdapterResult(status="skipped")
            else:
                record.sha256 = _hash_file(path)
                original = by_hash.get(record.sha256)
                if original and original != source_id and original in sources and sources[original].present:
                    record.status, record.status_reason = (
                        "duplicate",
                        f"identical to {sources[original].path}",
                    )
                    if record.category_source != "user":
                        # Same content, but a name can carry the role (a "scoring matrix" image).
                        if _family(suffix) == "document":
                            record.category = sources[original].category
                            record.category_reason = f"same content as {sources[original].path}"
                        else:
                            record.category, record.category_reason = cls.classify(relative, suffix, "")
                    record.evidence_count = 0
                    sources[source_id] = record
                    report.duplicates += 1
                    workspace.save_sources(sources)
                    continue
                by_hash.setdefault(record.sha256, source_id)
                result = extractors.run(workspace, path, relative, suffix, record.sha256)
                record.status = result.status
                record.status_reason = result.reason
        except Exception as error:  # one bad file never stops the project
            result = AdapterResult(status="failed", reason=f"{type(error).__name__}: {str(error)[:160]}")
            record.status, record.status_reason = "failed", result.reason
        record.adapter = result.method
        record.warnings = result.warnings[:20]
        record.metadata = {k: v for k, v in result.metadata.items() if k != "lines"}
        record.metadata["options"] = extractors.options(suffix)
        if record.category_source != "user":
            record.category, record.category_reason = cls.classify(relative, suffix, result.text)
        if record.status == "failed":
            report.failed += 1
        name = Path(relative).name
        count = 0
        for raw in result.items:
            item = m.EvidenceItem(
                evidence_id=evidence_id_for(source_id, raw),
                source_id=source_id,
                source_path=relative,
                category=record.category,
                extracted_at=utc_now(),
                source_sha256=record.sha256,
                citation=f"{name}, {raw.get('location', '')}",
                **{k: v for k, v in raw.items() if k in m.EvidenceItem.__dataclass_fields__},
            )
            evidence[item.evidence_id] = item
            count += 1
        record.evidence_count = count
        sources[source_id] = record
        workspace.save_sources(sources)  # checkpoint after every file
        workspace.save_evidence(evidence)

    if not report.interrupted and not only:
        for source_id, record in sources.items():
            if source_id.startswith("web-"):
                continue  # browser evidence has no file to disappear
            if source_id not in seen_ids and record.present:
                record.present = False
                report.removed += 1
                for stale in [eid for eid, item in evidence.items() if item.source_id == source_id]:
                    del evidence[stale]
        workspace.save_sources(sources)
        workspace.save_evidence(evidence)
    # Category corrections apply to evidence already in the library.
    for item in evidence.values():
        if item.source_id in sources:
            item.category = sources[item.source_id].category
    workspace.save_evidence(evidence)

    from howlwriter.projects.requirements import refresh_requirements

    refresh_requirements(workspace, sources=sources, evidence=evidence)
    present = [r for r in sources.values() if r.present]
    for record in present:
        report.by_category[record.category] = report.by_category.get(record.category, 0) + 1
        report.by_status[record.status] = report.by_status.get(record.status, 0) + 1
    report.evidence_items = len(evidence)
    if extractors._worker is not None:
        report.workload = dict(extractors._worker.stats, policy=extractors.policy.to_dict())
    report.seconds = round(time.monotonic() - started, 2)
    meta = workspace.load_meta()
    meta["scan_state"] = {
        "status": "interrupted" if report.interrupted else "complete",
        "finished_at": utc_now(),
        "report": report.to_dict(),
    }
    workspace.save_meta(meta)
    return report


def set_category(workspace: ProjectWorkspace, source: str, category: str) -> m.SourceRecord:
    """A user correction. It survives every rescan."""
    if category not in m.CATEGORIES:
        raise ValueError(f"unknown category {category!r}; choose from {', '.join(m.CATEGORIES)}")
    sources = workspace.load_sources()
    record = sources.get(source) or next((r for r in sources.values() if r.path == source), None)
    if record is None:
        raise ValueError(f"no source {source!r} in this project")
    record.category, record.category_source, record.category_reason = category, "user", "set by the user"
    sources[record.source_id] = record
    workspace.save_sources(sources)
    evidence = workspace.load_evidence()
    for item in evidence.values():
        if item.source_id == record.source_id:
            item.category = category
    workspace.save_evidence(evidence)
    from howlwriter.projects.requirements import refresh_requirements

    refresh_requirements(workspace, sources=sources, evidence=evidence)
    return record
