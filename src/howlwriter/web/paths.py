"""Where the local web API may read and write the owner's files.

The API is unauthenticated, so the document endpoints only touch plain text
files in ordinary locations: no dotfiles or dot-directories (``.ssh``,
``.config``, ``.local``), nothing under ``~/.howlwriter``, no symlinked files,
and no directories created on the way. A symlinked directory on the way is fine
(``/home`` -> ``/var/home``), but the resolved path must pass the same suffix,
dot and private-folder checks as the path as given.
"""

from __future__ import annotations

import os
from pathlib import Path

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
PUBLISH_SUFFIXES = TEXT_SUFFIXES | {".docx", ".pdf"}


class PathNotAllowed(Exception):
    """The path is outside what the web API may touch; the message says why."""


def _has_dot_component(path: Path) -> bool:
    return any(part.startswith(".") and part not in (".", "..") for part in path.parts)


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def check_user_path(raw: str, *, suffixes: frozenset[str], for_write: bool) -> Path:
    """Return the resolved path if the policy allows it, else raise PathNotAllowed."""
    if not raw or "\x00" in raw:
        raise PathNotAllowed("The path is empty or invalid.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    # Judge the components as written, so ".ssh/.." cannot be used to slip past the dot rule.
    if _has_dot_component(path):
        raise PathNotAllowed("Files in dotfiles or dot-directories (such as .ssh or .config) are not allowed.")
    path = Path(os.path.normpath(path))

    if path.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise PathNotAllowed(f"Only {allowed} files are allowed here.")
    if _has_dot_component(path):
        raise PathNotAllowed("Files in dotfiles or dot-directories (such as .ssh or .config) are not allowed.")

    if path.is_symlink():
        raise PathNotAllowed("Symbolic links are not allowed.")

    resolved = path.resolve()
    if resolved.suffix.lower() not in suffixes:
        raise PathNotAllowed("The path resolves to a file type that is not allowed here.")
    if _has_dot_component(resolved):
        raise PathNotAllowed("Files in dotfiles or dot-directories (such as .ssh or .config) are not allowed.")
    private_root = (Path.home() / ".howlwriter").resolve()
    if _is_inside(resolved, private_root):
        raise PathNotAllowed("HowlWriter's private data folder is not available through the web API.")

    if for_write:
        if not resolved.parent.is_dir():
            raise PathNotAllowed("The folder does not exist; create it first.")
        if resolved.exists() and not resolved.is_file():
            raise PathNotAllowed("The path is not a regular file.")
    else:
        if not resolved.exists():
            raise FileNotFoundError(raw)
        if not resolved.is_file():
            raise PathNotAllowed("The path is not a regular file.")
    return resolved
