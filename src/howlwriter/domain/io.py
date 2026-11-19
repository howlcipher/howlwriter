"""I/O and atomic file writing utilities."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile

_DEFAULT_UMASK = 0o022


def _current_umask() -> int:
    """The process umask, read without changing it.

    os.umask can only be read by setting it, which is process-wide and would
    briefly expose files other threads create. Parse /proc instead.
    """
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("Umask:"):
                    return int(line.split()[1], 8)
    except (OSError, ValueError, IndexError):
        pass
    return _DEFAULT_UMASK


def _fsync_directory(directory: Path) -> None:
    """Best effort: make the rename itself durable."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path | str, data: bytes, private: bool) -> Path:
    target_path = Path(path).resolve()
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(parent), prefix=f".{target_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if private:
            os.chmod(temp_name, 0o600)
        else:
            try:
                mode = stat.S_IMODE(target_path.stat().st_mode)
            except OSError:
                mode = 0o666 & ~_current_umask()
            os.chmod(temp_name, mode)
        os.replace(temp_name, target_path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    _fsync_directory(parent)
    return target_path


def atomic_write_text(
    path: Path | str, content: str, encoding: str = "utf-8", *, private: bool = False
) -> Path:
    """Atomically write text to path via a unique, fsynced temporary sibling.

    With ``private=True`` the file is 0600. Otherwise it keeps the existing
    file's mode, or the umask-derived default for a new file.
    """
    return _atomic_write(path, content.encode(encoding), private)


def atomic_write_bytes(path: Path | str, content: bytes, *, private: bool = False) -> Path:
    """Atomically write bytes to path; see ``atomic_write_text``."""
    return _atomic_write(path, content, private)
