"""I/O and atomic file writing utilities."""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(
    path: Path | str, content: str, encoding: str = "utf-8"
) -> Path:
    """Safely and atomically writes text to path via temporary sibling file."""
    target_path = Path(path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(
        f".{target_path.name}.{os.getpid()}.tmp"
    )
    try:
        temp_path.write_text(content, encoding=encoding)
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
    return target_path


def atomic_write_bytes(path: Path | str, content: bytes) -> Path:
    """Safely and atomically writes bytes to path via temporary sibling file."""
    target_path = Path(path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(
        f".{target_path.name}.{os.getpid()}.tmp"
    )
    try:
        temp_path.write_bytes(content)
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
    return target_path
