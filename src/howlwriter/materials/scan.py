"""Deterministic scan of an assignment-materials directory.

Every file under the root appears in the ledger, including files HowlWriter
cannot read; nothing is silently dropped. Text extraction reuses the voice
corpus extractors rather than duplicating parsers.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat as stat_mod
import zipfile
from pathlib import Path

from howlwriter.domain.source import DEPTH_FULL_TEXT, DEPTH_PARTIAL_TEXT
from howlwriter.materials.models import (
    EVIDENCE_ROLES,
    REQUIREMENT_ROLES,
    ROLE_SOURCE_DEFAULT,
    ROLE_SOURCE_EXPLICIT,
    ROLE_SOURCE_HEURISTIC,
    ExtractionStatus,
    MaterialLedger,
    MaterialRecord,
    MaterialRole,
    MaterialScan,
)
from howlwriter.voice.corpus import extract as _extract

MAX_MATERIAL_FILES = 200
MAX_MATERIAL_BYTES = 25 * 1024 * 1024
MAX_HASH_BYTES = 512 * 1024 * 1024
MAX_TEXT_CHARS = 400_000
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_MEMBERS = 5_000

LIMITS = {
    "max_files": MAX_MATERIAL_FILES,
    "max_file_bytes": MAX_MATERIAL_BYTES,
    "max_text_chars": MAX_TEXT_CHARS,
    "max_zip_uncompressed_bytes": MAX_ZIP_UNCOMPRESSED_BYTES,
}

# Plain-text-like data that the prose extractor does not list but which is
# safe to read as text. They default to USER_DATA, not REFERENCE.
_DATA_TEXT_SUFFIXES = {".csv", ".tsv", ".log", ".json", ".yaml", ".yml"}
_ZIP_SUFFIXES = {".docx", ".odt"}
# Formats we know exist and know we do not read: a human or external tool is
# needed, so the ledger says so instead of implying anything about content.
_EXTERNAL_SUFFIXES = {
    ".pcap", ".pcapng", ".cap", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3",
    ".wav", ".m4a", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
    ".svg", ".zip", ".tar", ".gz", ".7z", ".pptx", ".xlsx", ".doc", ".ppt", ".xls",
    ".exe", ".bin", ".iso", ".vmdk", ".ova", ".db", ".sqlite",
}

_RUBRIC_TOKENS = {"rubric", "rubrics", "grading", "criteria", "evaluation", "scoring"}
_INSTRUCTION_TOKENS = {
    "instructions", "instruction", "assignment", "prompt", "requirements",
    "requirement", "brief", "guidelines", "spec", "specification",
}
_DRAFT_TOKENS = {"draft", "drafts", "outline", "submission"}
_DATA_TOKENS = {"data", "dataset", "results", "output", "capture", "lab", "log", "logs"}


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", Path(name).stem.lower()) if t}


def _sha256(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _infer_role(relpath: str, suffix: str) -> tuple[MaterialRole, str, str]:
    """Return (role, role_source, reason). Heuristics are filename-token based
    and always labelled as heuristics so a reviewer can override them."""
    toks = _tokens(Path(relpath).name)
    if toks & _RUBRIC_TOKENS:
        return MaterialRole.RUBRIC, ROLE_SOURCE_HEURISTIC, f"filename token {sorted(toks & _RUBRIC_TOKENS)[0]!r}"
    if toks & _INSTRUCTION_TOKENS:
        return MaterialRole.INSTRUCTIONS, ROLE_SOURCE_HEURISTIC, f"filename token {sorted(toks & _INSTRUCTION_TOKENS)[0]!r}"
    if toks & _DRAFT_TOKENS:
        return MaterialRole.PRIOR_DRAFT, ROLE_SOURCE_HEURISTIC, f"filename token {sorted(toks & _DRAFT_TOKENS)[0]!r}"
    if suffix in _DATA_TEXT_SUFFIXES or toks & _DATA_TOKENS:
        return MaterialRole.USER_DATA, ROLE_SOURCE_HEURISTIC, "data-like filename or suffix"
    return MaterialRole.REFERENCE, ROLE_SOURCE_DEFAULT, "default for readable documents"


def _zip_guard(path: Path) -> str | None:
    """Reject zip containers whose declared expansion is unreasonable."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                return f"archive has {len(infos)} members (limit {MAX_ZIP_MEMBERS})"
            total = sum(i.file_size for i in infos)
            if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                return f"declared uncompressed size {total} bytes exceeds limit {MAX_ZIP_UNCOMPRESSED_BYTES}"
    except zipfile.BadZipFile:
        return None  # let the extractor report the corruption
    return None


def _extract_text(path: Path, suffix: str):
    """Return (status, method, text, reason)."""
    if suffix in _ZIP_SUFFIXES:
        problem = _zip_guard(path)
        if problem:
            return ExtractionStatus.FAILED, "zip_guard", "", f"refused: {problem}"
    if suffix in _DATA_TEXT_SUFFIXES:
        from howlwriter.voice.corpus.extract.plain import extract_plain
        result = extract_plain(path)
    else:
        result = _extract.extract(path)

    st = result.status
    if st == _extract.STATUS_OK and result.text.strip():
        return ExtractionStatus.OK, result.parser, result.text, result.reason
    if st == _extract.STATUS_EMPTY or (st == _extract.STATUS_OK):
        return ExtractionStatus.EMPTY, result.parser, "", result.reason or "no text content"
    if st == _extract.STATUS_SCANNED:
        return ExtractionStatus.SCANNED_NO_TEXT, result.parser, "", result.reason
    if st == _extract.STATUS_UNAVAILABLE:
        return ExtractionStatus.UNAVAILABLE, result.parser, "", result.reason
    if st == _extract.STATUS_UNSUPPORTED:
        if suffix in _EXTERNAL_SUFFIXES:
            return (ExtractionStatus.REQUIRES_EXTERNAL_INSPECTION, result.parser, "",
                    f"{suffix} content is not text-extractable by HowlWriter; inspect with an external tool")
        return ExtractionStatus.UNSUPPORTED_FOR_TEXT_EXTRACTION, result.parser, "", result.reason
    return ExtractionStatus.FAILED, result.parser, "", result.reason


def _normalize_overrides(overrides: dict[str, str] | None) -> dict[str, MaterialRole]:
    out: dict[str, MaterialRole] = {}
    for key, value in (overrides or {}).items():
        try:
            out[str(key).replace("\\", "/").lstrip("./")] = MaterialRole(str(value).upper())
        except ValueError as exc:
            valid = ", ".join(r.value for r in MaterialRole)
            raise ValueError(f"invalid material role {value!r} for {key!r} (valid: {valid})") from exc
    return out


def scan_materials(
    directory: str | Path,
    overrides: dict[str, str] | None = None,
    *,
    exclude: list[str | Path] | None = None,
) -> MaterialScan:
    """Scan ``directory`` and return the ledger plus extracted texts.

    ``overrides`` maps a root-relative path (or bare filename) to a role and
    always beats filename heuristics. ``exclude`` lists files (e.g. the
    assignment spec itself) that are not materials.
    """
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"materials directory not found: {directory}")
    root = root.resolve()
    role_overrides = _normalize_overrides(overrides)
    excluded = set()
    for e in exclude or []:
        try:
            excluded.add(Path(e).resolve())
        except OSError:
            pass

    ledger = MaterialLedger(root_label=root.name or "materials", limits=dict(LIMITS))
    texts: dict[str, str] = {}

    entries: list[tuple[str, Path]] = []
    skipped_dirs: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        keep = []
        for d in dirnames:
            full = Path(dirpath) / d
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                entries.append((rel, full))  # recorded as a skipped symlink
            elif d.startswith("."):
                skipped_dirs.append(rel)
            else:
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            full = Path(dirpath) / f
            if full.resolve() in excluded and not full.is_symlink():
                continue
            entries.append((full.relative_to(root).as_posix(), full))
    entries.sort(key=lambda item: item[0])

    if skipped_dirs:
        ledger.warnings.append(f"skipped hidden directories: {', '.join(sorted(skipped_dirs))}")
    if len(entries) > MAX_MATERIAL_FILES:
        ledger.warnings.append(
            f"{len(entries)} files found; only the first {MAX_MATERIAL_FILES} (sorted by path) were inspected"
        )
        dropped = entries[MAX_MATERIAL_FILES:]
        entries = entries[:MAX_MATERIAL_FILES]
        ledger.limits["files_not_inspected"] = [rel for rel, _ in dropped][:50]

    for index, (rel, full) in enumerate(entries, start=1):
        mid = f"M{index:03d}"
        suffix = full.suffix.lower()
        warnings: list[str] = []
        base = dict(material_id=mid, path=rel, name=full.name, suffix=suffix)

        role_override = role_overrides.get(rel) or role_overrides.get(full.name)
        if role_override is not None:
            role, role_source, reason = role_override, ROLE_SOURCE_EXPLICIT, "explicit override"
        else:
            role, role_source, reason = _infer_role(rel, suffix)

        def _finish(record: MaterialRecord) -> None:
            ledger.records.append(record)

        if full.is_symlink():
            _finish(MaterialRecord(
                **base, size_bytes=0, sha256=None, role=MaterialRole.AUXILIARY,
                role_source=ROLE_SOURCE_DEFAULT, role_reason="symlinks are never followed",
                extraction_status=ExtractionStatus.SKIPPED_SYMLINK,
                warnings=["symlink not followed (path boundary protection)"],
                provenance={"origin": "assignment_materials"},
            ))
            continue

        try:
            st = full.stat()
        except OSError as exc:
            _finish(MaterialRecord(
                **base, size_bytes=0, sha256=None, role=MaterialRole.AUXILIARY,
                role_source=ROLE_SOURCE_DEFAULT, role_reason="unreadable",
                extraction_status=ExtractionStatus.UNAVAILABLE,
                warnings=[f"could not stat file: {exc.strerror or exc}"],
                provenance={"origin": "assignment_materials"},
            ))
            continue
        if not stat_mod.S_ISREG(st.st_mode):
            _finish(MaterialRecord(
                **base, size_bytes=0, sha256=None, role=MaterialRole.AUXILIARY,
                role_source=ROLE_SOURCE_DEFAULT, role_reason="not a regular file",
                extraction_status=ExtractionStatus.UNSUPPORTED_FOR_TEXT_EXTRACTION,
                warnings=["special file; not read"],
                provenance={"origin": "assignment_materials"},
            ))
            continue

        size = st.st_size
        digest = _sha256(full) if size <= MAX_HASH_BYTES else None
        if digest is None:
            warnings.append("sha256 not computed")

        if size > MAX_MATERIAL_BYTES:
            status, method, text, why = (ExtractionStatus.SKIPPED_TOO_LARGE, "none", "",
                                         f"{size} bytes exceeds {MAX_MATERIAL_BYTES} byte limit")
        else:
            status, method, text, why = _extract_text(full, suffix)
        if why and status != ExtractionStatus.OK:
            warnings.append(why)

        truncated = False
        if status == ExtractionStatus.OK and len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
            truncated = True
            warnings.append(f"extracted text truncated to {MAX_TEXT_CHARS} characters")

        extracted = status == ExtractionStatus.OK
        if not extracted and role_source != ROLE_SOURCE_EXPLICIT and role != MaterialRole.AUXILIARY:
            # Nothing was read, so a filename-based role claims nothing about content.
            if status in (ExtractionStatus.REQUIRES_EXTERNAL_INSPECTION,
                          ExtractionStatus.UNSUPPORTED_FOR_TEXT_EXTRACTION,
                          ExtractionStatus.SKIPPED_TOO_LARGE):
                role, role_source, reason = MaterialRole.AUXILIARY, ROLE_SOURCE_DEFAULT, "no extractable text"

        depth = None
        if extracted:
            depth = DEPTH_PARTIAL_TEXT if truncated else DEPTH_FULL_TEXT
        record = MaterialRecord(
            **base,
            size_bytes=size, sha256=digest, role=role, role_source=role_source, role_reason=reason,
            extraction_status=status, extraction_method=method,
            text_extracted=extracted, text_chars=len(text) if extracted else 0, truncated=truncated,
            may_be_requirements=extracted and role in REQUIREMENT_ROLES,
            may_be_evidence=extracted and role in EVIDENCE_ROLES,
            evidence_depth=depth if (extracted and role in EVIDENCE_ROLES) else None,
            warnings=warnings,
            provenance={"origin": "assignment_materials", "sha256": digest},
        )
        ledger.records.append(record)
        if extracted:
            texts[mid] = text

    return MaterialScan(ledger=ledger, texts=texts)
