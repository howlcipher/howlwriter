"""Inventory a mounted drive, read what can be read, and keep a private ledger.

Order of operations, and the guarantee each step carries:

1. **Mount check.** The root must exist, be a directory, and list. A mount
   that is down produces a failed scan and leaves the previous inventory
   untouched; it never produces an inventory saying every file was removed.
2. **Walk.** `os.scandir` with `follow_symlinks=False`. Before a directory is
   entered its name is checked against the exclusion policy; an excluded
   directory is counted and never listed, so nothing inside it is statted,
   read, classified, or cached. Symlinks are recorded and never followed, and
   a directory whose real path leaves the root is not entered.
3. **Change detection.** A file whose size and modification time match the
   previous scan, and whose derived record is current, is not re-read. That
   is what makes a rescan of a network drive cheap.
4. **Read.** Files are read once, in binary, with bounded concurrency and
   retries for the transient errors a FUSE mount produces. A file whose size
   or mtime changes during the read is retried, then recorded as unstable.
   A permission denial is final (a cloud-native placeholder), not retried.
5. **Analyze.** Extraction, cleanup, classification, provenance, and every
   derived measurement happen in memory; the text is discarded after.
6. **Reconcile.** Renames are matched by content, duplicates grouped, and
   existing attestations checked against each document's current content:
   kept, carried forward across small edits, or reopened when the text has
   materially changed.

The inventory is checkpointed while the scan runs, so an interrupted scan
resumes where it stopped instead of re-reading everything.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import errno
import hashlib
import os
from pathlib import Path
import stat as stat_module
import time
from typing import Any, Callable

from howlwriter.voice.corpus.dedup import hamming
from howlwriter.voice.corpus.discovery import MAX_FILE_BYTES, PROSE_SUFFIXES, classify_suffix
from howlwriter.voice.corpus.extract import extract
from howlwriter.voice.identity import analysis, classify
from howlwriter.voice.identity.exclusions import ExclusionPolicy, normalize_component
from howlwriter.voice.identity.store import (
    Decision,
    IdentityConfig,
    IdentityStore,
    utc_now,
)

#: Errors a network-backed FUSE mount raises transiently.
_TRANSIENT = {errno.EIO, errno.EAGAIN, errno.ETIMEDOUT, errno.ENOTCONN, errno.ESTALE, errno.EBUSY}
_DENIED = {errno.EPERM, errno.EACCES}

READ_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5
CHECKPOINT_EVERY = 20
MIN_PROSE_BYTES = 200

#: Cloud-drive FUSE clients expose Google-native Docs, Sheets, and
#: Slides as small extensionless entries whose content cannot be read.
NATIVE_PLACEHOLDER_MAX_BYTES = 4096

#: Attestations survive edits this small (SimHash bits and word-count drift).
CARRY_FORWARD_BITS = 6
CARRY_FORWARD_WORD_DRIFT = 0.15

ProgressCallback = Callable[[str, dict[str, Any]], None]


class MountUnavailableError(RuntimeError):
    """The source root is not reachable; nothing was changed."""


@dataclass
class WalkedFile:
    relative_path: str
    absolute_path: str
    size: int
    mtime: float
    error: str = ""


@dataclass
class WalkResult:
    files: list[WalkedFile] = field(default_factory=list)
    directories_visited: int = 0
    excluded_directories: int = 0
    noise_directories: int = 0
    symlinks_skipped: int = 0
    escaped_root: int = 0
    unlistable_directories: int = 0


def mount_status(root: Path) -> dict[str, Any]:
    """Whether the source root is usable, and what kind of filesystem it is."""
    status: dict[str, Any] = {
        "root_exists": False,
        "listable": False,
        "filesystem": "",
        "error": "",
    }
    try:
        status["root_exists"] = root.is_dir()
    except OSError as error:
        status["error"] = str(error)
        return status
    if not status["root_exists"]:
        status["error"] = "source root does not exist or is not a directory"
        return status
    try:
        with os.scandir(root) as iterator:
            next(iterator, None)
        status["listable"] = True
    except OSError as error:
        status["error"] = f"source root could not be listed: {error.strerror or error}"
    try:
        real = os.path.realpath(root)
        best = ""
        with open("/proc/mounts", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 3:
                    mount_point = parts[1].replace("\\040", " ")
                    if real.startswith(mount_point) and len(mount_point) > len(best):
                        best = mount_point
                        status["filesystem"] = parts[2]
    except OSError:
        pass
    return status


def _retry(operation: Callable[[], Any]) -> Any:
    last: OSError | None = None
    for attempt in range(READ_ATTEMPTS):
        try:
            return operation()
        except OSError as error:
            if error.errno not in _TRANSIENT:
                raise
            last = error
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    assert last is not None
    raise last


def walk(root: Path, policy: ExclusionPolicy) -> WalkResult:
    """List every file under `root` that the policy allows, without following links."""
    result = WalkResult()
    root_real = os.path.realpath(root)
    stack: list[tuple[str, str]] = [("", root_real)]
    while stack:
        relative_dir, absolute_dir = stack.pop()
        try:
            entries = _retry(lambda: sorted(os.scandir(absolute_dir), key=lambda e: e.name))
        except OSError:
            result.unlistable_directories += 1
            continue
        result.directories_visited += 1
        for entry in entries:
            relative = f"{relative_dir}/{entry.name}" if relative_dir else entry.name
            try:
                if entry.is_symlink():
                    result.symlinks_skipped += 1
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                result.files.append(WalkedFile(relative, entry.path, 0, 0.0, "stat_failed"))
                continue
            if is_dir:
                # The exclusion check happens here, before the directory is
                # entered: its contents are never listed.
                if policy.excludes(entry.name):
                    result.excluded_directories += 1
                    continue
                if policy.is_noise(entry.name):
                    result.noise_directories += 1
                    continue
                child_real = os.path.realpath(entry.path)
                if os.path.commonpath([root_real, child_real]) != root_real:
                    result.escaped_root += 1
                    continue
                stack.append((relative, child_real))
                continue
            try:
                info = _retry(lambda: entry.stat(follow_symlinks=False))
            except OSError:
                result.files.append(WalkedFile(relative, entry.path, 0, 0.0, "stat_failed"))
                continue
            if not stat_module.S_ISREG(info.st_mode):
                continue
            result.files.append(WalkedFile(relative, entry.path, info.st_size, info.st_mtime))
    result.files.sort(key=lambda f: f.relative_path)
    return result


def _read_stable(path: str, size: int, mtime: float) -> tuple[bytes | None, str, str]:
    """Read a file once, consistently. Returns (bytes, status, reason)."""
    for _attempt in range(2):
        try:
            data = _retry(lambda: Path(path).read_bytes())
        except OSError as error:
            if error.errno in _DENIED:
                return None, "native_unavailable", "the mount refused to supply this file's content"
            return None, "unreadable", f"read failed: {error.strerror or error}"
        try:
            after = os.stat(path, follow_symlinks=False)
        except OSError:
            return data, "ok", ""
        if (
            after.st_size == len(data)
            and abs(after.st_mtime - mtime) < 1e-6
            and after.st_size == size
        ):
            return data, "ok", ""
        size, mtime = after.st_size, after.st_mtime
    return None, "changed_during_read", "file changed while it was being read; retry the scan later"


def _doc_id(relative_path: str) -> str:
    return hashlib.sha256(f"doc:{relative_path}".encode("utf-8")).hexdigest()[:16]


def _ownership(relative_path: str, config: IdentityConfig) -> str:
    shared = {normalize_component(name) for name in config.shared_with_me_dirs}
    first = normalize_component(relative_path.split("/", 1)[0])
    return "shared_with_me" if first in shared else "owned"


def _format_status(file: WalkedFile) -> tuple[str, str, str]:
    """(family, status, reason) decided from metadata alone."""
    suffix = Path(file.relative_path).suffix.lower()
    if file.error:
        return "unknown", "unreadable", "the mount could not report this file's metadata"
    if not suffix and file.size <= NATIVE_PLACEHOLDER_MAX_BYTES:
        return "native_cloud", "pending", ""
    if suffix in PROSE_SUFFIXES:
        if file.size > MAX_FILE_BYTES:
            return (
                "prose",
                "too_large",
                f"{file.size} bytes exceeds the {MAX_FILE_BYTES}-byte limit",
            )
        if file.size < MIN_PROSE_BYTES:
            return "prose", "too_small", "too small to hold a paragraph of prose"
        return "prose", "pending", ""
    status, reason = classify_suffix(suffix)
    return "nonprose", "nonprose_excluded", reason or status


@dataclass
class ScanOutcome:
    report: dict[str, Any]
    inventory: dict[str, Any]
    review_queue_path: Path | None = None


def scan(
    identity: str,
    *,
    sources: list[str] | None = None,
    additional_exclusions: list[str] | None = None,
    store_root: Path | None = None,
    force: bool = False,
    progress: ProgressCallback | None = None,
    perturbations: bool = True,
    google_api: bool = False,
    google_service_factory: Callable[[], Any] | None = None,
) -> ScanOutcome:
    """Scan (or rescan) an identity's sources and update its private ledger."""
    store = IdentityStore(identity, root=store_root)
    config = store.load_config()
    if sources:
        resolved = [str(Path(s).expanduser()) for s in sources]
        config.sources = (
            list(dict.fromkeys([*config.sources, *resolved])) if config.sources else resolved
        )
    if additional_exclusions:
        config.exclusions = ExclusionPolicy(
            required=config.exclusions.required,
            additional=tuple(
                dict.fromkeys([*config.exclusions.additional, *additional_exclusions])
            ),
            prune_noise=config.exclusions.prune_noise,
        )
    if not config.sources:
        raise ValueError(
            f"identity '{store.identity}' has no sources; pass --source PATH on the first scan"
        )

    def notify(stage: str, data: dict[str, Any]) -> None:
        if progress is not None:
            try:
                progress(stage, data)
            except Exception:
                pass

    started = time.time()
    previous = store.load_inventory()
    previous_entries: dict[str, dict] = previous.get("entries", {})
    by_path = {
        e["relative_path"]: (doc_id, e)
        for doc_id, e in previous_entries.items()
        if e.get("present", True)
    }

    # --- 1. mount check (all roots must be reachable) ---
    roots: list[tuple[Path, dict]] = []
    for source in config.sources:
        root = Path(source).expanduser()
        status = mount_status(root)
        if not (status["root_exists"] and status["listable"]):
            raise MountUnavailableError(
                f"source {source} is not available ({status['error'] or 'not listable'}); "
                "the previous inventory was left unchanged"
            )
        roots.append((root, status))
    # Persist the configuration now, not at the end: a scan interrupted
    # halfway must be resumable, and resuming needs to know its sources.
    store.save_config(config)
    notify("mount", {"sources": len(roots), "filesystems": [s["filesystem"] for _, s in roots]})

    # --- 2. walk ---
    walked: list[tuple[int, WalkedFile]] = []
    walk_totals = WalkResult()
    for index, (root, _status) in enumerate(roots):
        result = walk(root, config.exclusions)
        for file in result.files:
            if len(roots) > 1:
                file.relative_path = f"{index}:{file.relative_path}"
            walked.append((index, file))
        for name in (
            "directories_visited",
            "excluded_directories",
            "noise_directories",
            "symlinks_skipped",
            "escaped_root",
            "unlistable_directories",
        ):
            setattr(walk_totals, name, getattr(walk_totals, name) + getattr(result, name))
    notify("walk", {"files": len(walked), "excluded_directories": walk_totals.excluded_directories})

    # Defence in depth: nothing walked may sit under an excluded component.
    for _, file in walked:
        parts = file.relative_path.split(":", 1)[-1].split("/")
        if config.exclusions.path_is_excluded(parts):
            raise RuntimeError("internal error: walker returned a path under an excluded directory")

    # --- 3. decide what needs reading ---
    entries: dict[str, dict] = {}
    to_read: list[tuple[str, WalkedFile, dict]] = []
    now = utc_now()
    for _, file in walked:
        family, status, reason = _format_status(file)
        old = by_path.get(file.relative_path)
        doc_id = old[0] if old else _doc_id(file.relative_path)
        prior = old[1] if old else None
        entry: dict[str, Any] = {
            "doc_id": doc_id,
            "relative_path": file.relative_path,
            "suffix": Path(file.relative_path).suffix.lower(),
            "size": file.size,
            "mtime": file.mtime,
            "family": family,
            "status": status,
            "reason": reason,
            "ownership": _ownership(file.relative_path.split(":", 1)[-1], config),
            "present": True,
            "first_seen": (prior or {}).get("first_seen", now),
            "last_seen": now,
            "previous_paths": list((prior or {}).get("previous_paths", [])),
            "analysis_version": analysis.ANALYSIS_VERSION,
        }
        unchanged = (
            prior is not None
            and not force
            and prior.get("size") == file.size
            and abs(float(prior.get("mtime", 0)) - file.mtime) < 1e-6
            and prior.get("status")
            not in ("pending", "unreadable", "changed_during_read", "analysis_failed")
            and prior.get("analysis_version") == analysis.ANALYSIS_VERSION
        )
        if unchanged:
            carried = dict(prior)
            carried.update({"last_seen": now, "present": True, "change": "unchanged"})
            entries[doc_id] = carried
            continue
        entry["change"] = "modified" if prior else "added"
        entry["last_changed"] = now
        entries[doc_id] = entry
        if status == "pending":
            to_read.append((doc_id, file, entry))

    # --- 4 & 5. read and analyze, bounded concurrency, checkpointed ---
    def process(item: tuple[str, WalkedFile, dict]) -> tuple[str, dict]:
        doc_id, file, entry = item
        data, read_status, reason = _read_stable(file.absolute_path, file.size, file.mtime)
        if data is None:
            entry["status"] = read_status
            entry["reason"] = reason
            return doc_id, entry
        entry["raw_sha256"] = hashlib.sha256(data).hexdigest()
        if entry["family"] == "native_cloud":
            # Readable after all, so not a placeholder the mount refuses. Some
            # clients expose native documents as small JSON link stubs; every
            # other small extensionless file (LICENSE, release, a binary stub)
            # is simply not prose.
            head = data[:512].lstrip()
            if head.startswith(b"{") and (
                b'"url"' in head or b'"doc_id"' in head or b'"resource_id"' in head
            ):
                entry["status"] = "native_unavailable"
                entry["reason"] = "the mount exposes a link stub, not the document's content"
            else:
                entry["family"] = "nonprose"
                entry["status"] = "nonprose_excluded"
                entry["reason"] = "no_extension"
            return doc_id, entry
        # One malformed document must cost that document, never the scan.
        # The reason records the exception type only: a message could quote
        # document text into the inventory.
        try:
            extraction = extract(Path(file.absolute_path), data)
        except Exception as error:  # parser bugs on hostile input
            entry["status"] = "extraction_failed"
            entry["reason"] = f"parser raised {type(error).__name__}"
            return doc_id, entry
        entry["parser"] = extraction.parser
        if not extraction.ok:
            entry["status"] = extraction.status
            entry["reason"] = extraction.reason
            return doc_id, entry
        try:
            derived = analysis.analyze(
                text=extraction.text,
                raw=data,
                relative_path=file.relative_path.split(":", 1)[-1],
                suffix=entry["suffix"],
                mtime=file.mtime,
                aliases=config.aliases,
                ownership=entry["ownership"],
                auto_accept_pre_llm_bylined=config.auto_accept_pre_llm_bylined,
                perturbations=perturbations,
            )
        except Exception as error:
            entry["status"] = "analysis_failed"
            entry["reason"] = f"analysis raised {type(error).__name__}"
            return doc_id, entry
        entry.update(derived)
        del extraction, data
        return doc_id, entry

    processed = 0
    inventory: dict[str, Any] = {
        "version": previous.get("version", 1),
        "entries": dict(previous_entries),
    }
    workers = max(1, min(config.max_workers, 16))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for doc_id, entry in pool.map(process, to_read):
            entries[doc_id] = entry
            processed += 1
            if processed % CHECKPOINT_EVERY == 0:
                inventory["entries"].update({k: v for k, v in entries.items()})
                store.save_inventory(inventory)
                notify("read", {"processed": processed, "total": len(to_read)})

    # --- 6. reconcile: removals and renames ---
    seen_ids = set(entries)
    removed = {
        doc_id: entry
        for doc_id, entry in previous_entries.items()
        if doc_id not in seen_ids and entry.get("present", True)
    }
    by_hash: dict[str, str] = {}
    for doc_id, entry in removed.items():
        if entry.get("raw_sha256"):
            by_hash.setdefault(entry["raw_sha256"], doc_id)
    renamed = 0
    for doc_id, entry in list(entries.items()):
        if entry.get("change") != "added" or not entry.get("raw_sha256"):
            continue
        old_id = by_hash.pop(entry["raw_sha256"], None)
        if old_id is None:
            continue
        old = removed.pop(old_id)
        entry["doc_id"] = old_id
        entry["first_seen"] = old.get("first_seen", entry["first_seen"])
        entry["previous_paths"] = [*old.get("previous_paths", []), old["relative_path"]]
        entry["change"] = "renamed"
        entries.pop(doc_id)
        entries[old_id] = entry
        renamed += 1
    for doc_id, entry in removed.items():
        gone = dict(entry)
        gone.update({"present": False, "change": "removed", "removed_at": now})
        entries[doc_id] = gone
    # Entries that were already absent before this scan stay as history.
    for doc_id, entry in previous_entries.items():
        if doc_id not in entries:
            entries[doc_id] = entry

    google_counts: dict[str, int] | None = None
    if google_api:
        from howlwriter.voice.identity import google_fallback

        notify("google_api", {"disclosure": google_fallback.DISCLOSURE})
        kwargs = {"perturbations": perturbations}
        if google_service_factory is not None:
            kwargs["service_factory"] = google_service_factory
        google_counts = google_fallback.fetch_native_documents(store, config, entries, **kwargs)

    _group_duplicates(entries)
    decisions = store.load_decisions()
    reopened, carried = _reconcile_decisions(store, decisions, entries)

    inventory = {
        "version": previous.get("version", 1),
        "identity": store.identity,
        "sources": list(config.sources),
        "entries": entries,
        "scans": [
            *previous.get("scans", [])[-19:],
            {"at": now, "duration_seconds": round(time.time() - started, 1)},
        ],
    }
    store.save_config(config)
    store.save_inventory(inventory)

    report = build_report(
        store=store,
        config=config,
        entries=entries,
        walk_totals=walk_totals,
        decisions=store.load_decisions(),
        mount=[s for _, s in roots],
        read_this_scan=processed,
        renamed=renamed,
        reopened=reopened,
        carried=carried,
        duration=time.time() - started,
    )
    if google_counts is not None:
        report["google_api"] = google_counts
    store.write_scan_report(report)
    queue_path = write_review_queue(store, entries, store.load_decisions())
    notify("done", {"processed": processed})
    return ScanOutcome(report=report, inventory=inventory, review_queue_path=queue_path)


_FORMAT_RANK = {
    ".docx": 6,
    ".odt": 5,
    ".md": 4,
    ".txt": 4,
    ".html": 3,
    ".htm": 3,
    ".rtf": 2,
    ".pdf": 1,
}


def _group_duplicates(entries: dict[str, dict]) -> None:
    """Exact and near-duplicate grouping on cached fingerprints.

    The corpus build deduplicates again on full text when it runs; this pass
    exists so the inventory and the review queue do not ask the person to
    attest the same essay three times.
    """
    extracted = [
        (doc_id, e)
        for doc_id, e in entries.items()
        if e.get("present", True) and e.get("status") == "extracted" and e.get("fingerprint")
    ]
    for _, entry in extracted:
        entry.pop("duplicate_of", None)
        entry["duplicate_role"] = "unique"

    def richness(item: tuple[str, dict]) -> tuple:
        _, e = item
        return (
            _FORMAT_RANK.get(e.get("suffix", ""), 0),
            e.get("words", 0),
            e.get("mtime", 0),
            e["relative_path"],
        )

    groups: list[list[tuple[str, dict]]] = []
    for item in sorted(extracted, key=richness, reverse=True):
        _, entry = item
        fp = entry["fingerprint"]
        sim = int(str(fp.get("simhash", "0")), 16)
        placed = False
        for group in groups:
            head = group[0][1]["fingerprint"]
            if (
                head.get("content_hash") == fp.get("content_hash")
                or hamming(int(str(head.get("simhash", "0")), 16), sim) <= 10
            ):
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])
    for group in groups:
        if len(group) < 2:
            continue
        head_id = group[0][0]
        group[0][1]["duplicate_role"] = "representative"
        for doc_id, entry in group[1:]:
            entry["duplicate_role"] = "duplicate"
            entry["duplicate_of"] = head_id


def _reconcile_decisions(
    store: IdentityStore, decisions: dict[str, Decision], entries: dict[str, dict]
) -> tuple[int, int]:
    """Keep, carry forward, or reopen each attestation against current content."""
    reopened = carried = 0
    changed = False
    for doc_id, decision in decisions.items():
        entry = entries.get(doc_id)
        if entry is None or not entry.get("present", True):
            continue
        decision.path = entry["relative_path"]
        fp = entry.get("fingerprint") or {}
        current_hash = entry.get("raw_sha256", "")
        if not decision.content_hash or decision.content_hash == current_hash:
            if decision.content_hash and decision.status != "active":
                # Content is back to exactly what was attested.
                decision.status = "active"
                decision.status_reason = ""
                changed = True
            continue
        old_sim = int(decision.simhash or "0", 16)
        new_sim = int(str(fp.get("simhash", "0")), 16)
        words = int(entry.get("words", 0))
        drift = abs(words - decision.words) / max(1, decision.words)
        if (
            fp
            and hamming(old_sim, new_sim) <= CARRY_FORWARD_BITS
            and drift <= CARRY_FORWARD_WORD_DRIFT
        ):
            if decision.status != "carried_forward":
                decision.status = "carried_forward"
                decision.status_reason = "document was lightly edited after attestation"
                carried += 1
                changed = True
        elif decision.status != "reopened":
            decision.status = "reopened"
            decision.status_reason = (
                "document content changed substantially after attestation; confirm again"
            )
            reopened += 1
            changed = True
    if changed or decisions:
        store.save_decisions(decisions)
    return reopened, carried


def effective_authorship(entry: dict, decisions: dict[str, Decision]) -> tuple[str, str]:
    """(authorship, basis) for an entry: an effective attestation wins."""
    decision = decisions.get(entry.get("doc_id", ""))
    if decision is not None and decision.effective:
        return decision.authorship, "attested"
    proposal = entry.get("proposal") or {}
    return proposal.get("authorship", classify.UNKNOWN_AUTHORSHIP), "proposed"


def needs_review(entry: dict, decisions: dict[str, Decision]) -> bool:
    if not entry.get("present", True) or entry.get("status") != "extracted":
        return False
    if entry.get("duplicate_role") == "duplicate":
        return False
    decision = decisions.get(entry["doc_id"])
    if decision is not None and decision.effective:
        return False
    if decision is not None and decision.status == "reopened":
        # The person put this document somewhere; a material change means
        # they must look again, whatever the heuristic proposal now says.
        return True
    return bool((entry.get("proposal") or {}).get("needs_review"))


def build_report(
    *,
    store: IdentityStore,
    config: IdentityConfig,
    entries: dict[str, dict],
    walk_totals: WalkResult,
    decisions: dict[str, Decision],
    mount: list[dict],
    read_this_scan: int,
    renamed: int,
    reopened: int,
    carried: int,
    duration: float,
) -> dict[str, Any]:
    """Counts only. No file names, no titles, no text."""
    present = [e for e in entries.values() if e.get("present", True)]

    def count(predicate) -> int:
        return sum(1 for e in present if predicate(e))

    statuses: dict[str, int] = {}
    categories: dict[str, int] = {}
    authorship: dict[str, int] = {}
    for entry in present:
        statuses[entry.get("status", "?")] = statuses.get(entry.get("status", "?"), 0) + 1
        if entry.get("status") == "extracted":
            category = (entry.get("classification") or {}).get("category", "unknown")
            categories[category] = categories.get(category, 0) + 1
            value, basis = effective_authorship(entry, decisions)
            key = f"{value} ({basis})"
            authorship[key] = authorship.get(key, 0) + 1
    academic = {"academic_paper", "academic_discussion", "academic_lab", "research_analysis"}
    professional = {
        "technical_documentation",
        "professional_engineering_document",
        "professional_article",
        "linkedin_or_public_commentary",
    }
    extracted = [e for e in present if e.get("status") == "extracted"]
    eligible = count(lambda e: e.get("family") in ("prose", "native_cloud"))
    readable = len(extracted) + statuses.get("sensitive_excluded", 0)
    return {
        "identity": store.identity,
        "scanned_at": utc_now(),
        "duration_seconds": round(duration, 1),
        "mount": mount,
        "exclusions": config.exclusions.names,
        "walk": {
            "directories_visited": walk_totals.directories_visited,
            "excluded_directories_skipped": walk_totals.excluded_directories,
            "noise_directories_skipped": walk_totals.noise_directories,
            "symlinks_not_followed": walk_totals.symlinks_skipped,
            "directories_outside_root_refused": walk_totals.escaped_root,
            "unlistable_directories": walk_totals.unlistable_directories,
        },
        "files_inventoried": len(present),
        "removed_since_last_scan": sum(1 for e in entries.values() if e.get("change") == "removed"),
        "renamed_since_last_scan": renamed,
        "read_this_scan": read_this_scan,
        "eligible_prose_files": eligible,
        "native_cloud_unavailable": statuses.get("native_unavailable", 0),
        "readable_documents": readable,
        "extracted_documents": len(extracted),
        "unreadable_or_failed": sum(
            statuses.get(s, 0)
            for s in (
                "unreadable",
                "extraction_failed",
                "analysis_failed",
                "changed_during_read",
                "scanned_no_text_layer",
                "empty",
                "unsupported_format",
            )
        ),
        "statuses": dict(sorted(statuses.items())),
        "categories": dict(sorted(categories.items())),
        "authorship": dict(sorted(authorship.items())),
        "academic_candidates": count(
            lambda e: e.get("status") == "extracted"
            and (e.get("classification") or {}).get("category") in academic
        ),
        "professional_candidates": count(
            lambda e: e.get("status") == "extracted"
            and (e.get("classification") or {}).get("category") in professional
        ),
        "duplicates": count(lambda e: e.get("duplicate_role") == "duplicate"),
        "pending_reviews": count(lambda e: needs_review(e, decisions)),
        "decisions": {
            "active": sum(1 for d in decisions.values() if d.status == "active"),
            "carried_forward": sum(1 for d in decisions.values() if d.status == "carried_forward"),
            "reopened": sum(1 for d in decisions.values() if d.status == "reopened"),
            "reopened_this_scan": reopened,
            "carried_forward_this_scan": carried,
        },
        "coverage": {
            "content_read_share_of_eligible": round(readable / eligible, 3) if eligible else 0.0,
            "complete": statuses.get("native_unavailable", 0) == 0
            and statuses.get("unreadable", 0) == 0,
            "note": (
                "native cloud documents were inventoried but not read; the mount does not "
                "expose their content"
                if statuses.get("native_unavailable")
                else ""
            ),
        },
    }


_QUEUE_HEADER = """\
# Authorship review for identity '{identity}'.
#
# Each entry below is a document that would affect a personal profile but
# whose authorship has not been confirmed. Set `decision:` to one of:
#
#   CONFIRMED_HUMAN_AUTHORED         you wrote it without substantial AI drafting
#   HUMAN_AUTHORED_LIGHT_AI_EDITING  your writing; AI only polished wording (half weight)
#   MIXED_AUTHORSHIP                 partly yours: also set include_paragraphs: "1-4,7"
#   SUBSTANTIALLY_AI_GENERATED       mostly AI-drafted; never used as your voice
#   THIRD_PARTY                      someone else's document
#   UNKNOWN_AUTHORSHIP               not sure; stays out of the profiles
#
# Leave `decision: pending` to skip. Apply with:
#   howlwriter voice review --identity {identity} --apply {path}
#
# This file is regenerated by each scan; decisions already applied are kept
# in decisions.json and never lost.
"""


def write_review_queue(
    store: IdentityStore, entries: dict[str, dict], decisions: dict[str, Decision]
) -> Path:
    import yaml

    pending = [e for e in entries.values() if needs_review(e, decisions)]
    pending.sort(
        key=lambda e: (-(e.get("proposal") or {}).get("review_priority", 0), e["relative_path"])
    )
    items = []
    for entry in pending:
        proposal = entry.get("proposal") or {}
        classification = entry.get("classification") or {}
        provenance = entry.get("provenance") or {}
        decision = decisions.get(entry["doc_id"])
        items.append(
            {
                "doc_id": entry["doc_id"],
                "path": entry["relative_path"],
                "category": classification.get("category"),
                "context": classification.get("context"),
                "words": entry.get("words"),
                "paragraphs": entry.get("paragraph_count"),
                "proposed": proposal.get("authorship"),
                "why_uncertain": list(proposal.get("reasons", []))[:6],
                "style_signals": list(proposal.get("style_signals", [])),
                "predates_llm_era": provenance.get("predates_llm_era"),
                "reopened": bool(decision and decision.status == "reopened"),
                "decision": "pending",
                "include_paragraphs": "",
                "category_override": "",
                "context_override": "",
                "note": "",
            }
        )
    path = store.directory / "review_queue.yaml"
    body = _QUEUE_HEADER.format(identity=store.identity, path=path)
    body += yaml.safe_dump({"pending": items}, sort_keys=False, allow_unicode=True, width=100)
    return store.write_review_queue(body)
