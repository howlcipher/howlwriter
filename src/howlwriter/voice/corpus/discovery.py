"""Stage 1: find candidate prose files under the roots the user supplied.

Two rules shape this module.

First, the user may hand over roots that overlap -- a drive root plus two
directories inside it is the normal case, not an edge case. Every path is
resolved to its canonical form and deduplicated BEFORE anything is read, so a
file reachable three ways is still parsed once and still counts once toward
the corpus.

Second, discovery is strictly read only. Nothing here opens a file for
writing, renames, or deletes; `stat` and directory iteration are the only
filesystem operations, and extraction later opens files in binary read mode
only. A user's document collection is not ours to modify.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

#: Formats that plausibly carry prose and that we can extract safely.
#: `.doc` is listed so a legacy Word file is reported honestly as an
#: unsupported format rather than silently vanishing from the counts.
PROSE_SUFFIXES = {
    ".docx", ".odt", ".rtf", ".txt", ".md", ".markdown",
    ".html", ".htm", ".pdf", ".doc", ".text",
}

#: Suffixes rejected outright, grouped so exclusion reports can say WHY a
#: file was skipped instead of just how many were. Voice is prose; source
#: code, spreadsheets, and slide fragments are not writing style.
_EXCLUDED_SUFFIXES: dict[str, str] = {}


def _register(reason: str, suffixes: str) -> None:
    for suffix in suffixes.split():
        _EXCLUDED_SUFFIXES[suffix] = reason


_register("source_code", (
    ".py .js .ts .tsx .jsx .go .rs .c .h .cpp .hpp .cc .java .kt .swift .rb "
    ".php .pl .sh .bash .zsh .fish .ps1 .bat .cmd .lua .r .m .scala .clj .ex "
    ".exs .erl .hs .sql .vim .el .asm .s"
))
_register("binary_or_executable", (
    ".exe .dll .so .dylib .bin .o .obj .jar .jmod .class .msi .deb .rpm "
    ".appimage .apk .iso .img .dmg .sys .drv .lib .a .pyc .pyo .wasm"
))
_register("archive", ".zip .tar .gz .bz2 .xz .7z .rar .tgz .tbz .zst .lz4")
_register("image", ".jpg .jpeg .png .gif .bmp .svg .webp .tiff .tif .ico .heic .raw .psd")
_register("audio_video", ".mp3 .mp4 .wav .flac .ogg .avi .mkv .mov .wmv .m4a .aac .webm .srm")
_register("structured_data", ".csv .tsv .xlsx .xls .ods .parquet .db .sqlite .sqlite3 .dat")
_register("slide_deck", ".pptx .ppt .odp .key")
_register("config_or_manifest", (
    ".json .yaml .yml .toml .ini .cfg .conf .properties .env .lock .plist "
    ".gradle .cmake .mk .makefile .editorconfig .gitignore .state .policy"
))
_register("machine_generated_log", ".log .out .err .trace .dmp .core .jfc .glshadercache")
_register("font_or_asset", ".ttf .otf .woff .woff2 .eot .css .scss .sass .less")
_register("license_or_notice", ".license .additional_license_info .assembly_exception")

#: Directories never worth walking into. Skipping these early is what keeps a
#: large drive root from turning discovery into a multi-minute scan.
_SKIP_DIR_NAMES = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg", "venv", ".venv",
    "site-packages", "dist-info", "egg-info", ".mypy_cache", ".pytest_cache",
    "build", "dist", "target", ".gradle", ".idea", ".vscode", ".cache",
    "RetroArchSaves", "Shared Drives", "Shared with Me",
}

#: A file this small cannot hold enough prose to say anything about voice; a
#: file this large is not a document a person wrote in one sitting. Both
#: bounds are recorded as reasons rather than applied silently.
MIN_FILE_BYTES = 512
MAX_FILE_BYTES = 40 * 1024 * 1024


@dataclass
class DiscoveredFile:
    """One canonical filesystem path, and whether it is worth extracting."""

    path: Path
    suffix: str
    size: int
    mtime: float
    status: str = "candidate"          # "candidate" | "excluded"
    reason: str = ""
    reached_via: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    files: list[DiscoveredFile] = field(default_factory=list)
    roots_supplied: int = 0
    roots_after_canonicalization: int = 0
    paths_visited: int = 0
    duplicate_root_hits: int = 0
    unreadable_roots: list[str] = field(default_factory=list)

    @property
    def candidates(self) -> list[DiscoveredFile]:
        return [f for f in self.files if f.status == "candidate"]

    @property
    def excluded(self) -> list[DiscoveredFile]:
        return [f for f in self.files if f.status == "excluded"]

    def exclusion_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.excluded:
            counts[entry.reason] = counts.get(entry.reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def canonicalize_roots(roots: list[str | Path]) -> tuple[list[Path], list[str]]:
    """Resolve roots and drop any that is contained in another.

    Given a drive root and two directories beneath it, only the drive root
    survives. This is what stops the same document being parsed once per way
    it can be reached, and it happens before any file is opened.
    """
    resolved: list[Path] = []
    unreadable: list[str] = []
    for root in roots:
        try:
            path = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            unreadable.append(str(root))
            continue
        if not path.is_dir() and not path.is_file():
            unreadable.append(str(root))
            continue
        resolved.append(path)

    # Deduplicate exact repeats first, then drop nested roots.
    unique = sorted(set(resolved), key=lambda p: len(p.parts))
    kept: list[Path] = []
    for path in unique:
        if any(_is_within(path, parent) for parent in kept):
            continue
        kept.append(path)
    return kept, unreadable


def _is_within(child: Path, parent: Path) -> bool:
    if child == parent:
        return True
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def classify_suffix(suffix: str) -> tuple[str, str]:
    """Map a file suffix to (status, reason) without reading the file."""
    lowered = suffix.lower()
    if lowered in PROSE_SUFFIXES:
        return "candidate", ""
    if lowered in _EXCLUDED_SUFFIXES:
        return "excluded", _EXCLUDED_SUFFIXES[lowered]
    if not lowered:
        return "excluded", "no_extension"
    return "excluded", "unsupported_format"


def discover(
    roots: list[str | Path],
    *,
    recursive: bool = True,
    max_files: int | None = None,
) -> DiscoveryResult:
    """Walk the supplied roots and return every canonical path found.

    Excluded files are returned alongside candidates rather than dropped, so
    the corpus report can account for every file it saw. `max_files` is a
    safety stop for an unexpectedly enormous tree, not a sampling mechanism.
    """
    canonical_roots, unreadable = canonicalize_roots(roots)
    result = DiscoveryResult(
        roots_supplied=len(roots),
        roots_after_canonicalization=len(canonical_roots),
        unreadable_roots=unreadable,
    )

    seen: dict[Path, DiscoveredFile] = {}
    seen_dirs: set[tuple[int, int]] = set()

    def consider(path: Path, via: Path) -> None:
        result.paths_visited += 1
        try:
            canonical = path.resolve()
        except (OSError, RuntimeError):
            return
        existing = seen.get(canonical)
        if existing is not None:
            # Same file, different route in. Record the extra route for the
            # report and move on -- it must not become a second document.
            result.duplicate_root_hits += 1
            if str(via) not in existing.reached_via:
                existing.reached_via.append(str(via))
            return
        try:
            stat = canonical.stat()
        except OSError:
            seen[canonical] = DiscoveredFile(
                path=canonical, suffix=canonical.suffix.lower(), size=0, mtime=0.0,
                status="excluded", reason="unreadable", reached_via=[str(via)],
            )
            return

        status, reason = classify_suffix(canonical.suffix)
        if status == "candidate":
            if stat.st_size < MIN_FILE_BYTES:
                status, reason = "excluded", "too_small"
            elif stat.st_size > MAX_FILE_BYTES:
                status, reason = "excluded", "too_large"

        seen[canonical] = DiscoveredFile(
            path=canonical,
            suffix=canonical.suffix.lower(),
            size=stat.st_size,
            mtime=stat.st_mtime,
            status=status,
            reason=reason,
            reached_via=[str(via)],
        )

    for root in canonical_roots:
        if root.is_file():
            consider(root, root)
            continue
        walker = os.walk(root, followlinks=False) if recursive else _shallow_walk(root)
        for dirpath, dirnames, filenames in walker:
            current = Path(dirpath)
            # Guard against a directory reachable twice through links.
            try:
                stat = current.stat()
                key = (stat.st_dev, stat.st_ino)
                if key in seen_dirs:
                    dirnames[:] = []
                    continue
                seen_dirs.add(key)
            except OSError:
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIR_NAMES and not d.startswith(".")
            ]
            for name in filenames:
                if name.startswith("."):
                    continue
                consider(current / name, root)
                if max_files is not None and len(seen) >= max_files:
                    break
            if max_files is not None and len(seen) >= max_files:
                break

    result.files = sorted(seen.values(), key=lambda f: str(f.path))
    return result


def _shallow_walk(root: Path):
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    filenames = [e.name for e in entries if e.is_file(follow_symlinks=False)]
    yield str(root), [], filenames
