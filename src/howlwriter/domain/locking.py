"""Cross-thread and cross-process advisory locking for a directory of records.

`file_lock(directory)` serialises load-modify-save cycles. Within one process a
per-path reentrant thread lock is used; the outermost hold in a thread also
takes `fcntl.flock` on a lock file so other processes (CLI plus web server)
are excluded too. Hold it for the short read-modify-write only, never across
a scan or a model call.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import threading
from typing import Iterator

try:  # pragma: no cover - platform dependent
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

_REGISTRY_LOCK = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_LOCAL = threading.local()


def _thread_lock(key: str) -> threading.RLock:
    with _REGISTRY_LOCK:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = _THREAD_LOCKS[key] = threading.RLock()
        return lock


def _state() -> dict[str, list]:
    held = getattr(_LOCAL, "held", None)
    if held is None:
        held = _LOCAL.held = {}
    return held


@contextmanager
def file_lock(directory: Path | str, name: str = ".lock") -> Iterator[None]:
    """Hold an exclusive lock on `<directory>/<name>`; reentrant per thread."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"cannot lock {directory}: directory does not exist")
    lock_path = directory.resolve() / name
    key = str(lock_path)
    thread_lock = _thread_lock(key)
    with thread_lock:
        held = _state()
        entry = held.get(key)
        if entry is not None:
            entry[0] += 1
            try:
                yield
            finally:
                entry[0] -= 1
            return
        fd = None
        if fcntl is not None:
            fd = os.open(key, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except BaseException:
                os.close(fd)
                raise
        held[key] = [1, fd]
        try:
            yield
        finally:
            del held[key]
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
