"""Where private identity data may live, and with what permissions.

Two guarantees, both enforced in code rather than left to documentation.

Owner-only permissions. Every directory this package creates is 0700 and
every file 0600. A shared machine or a backup tool that copies home
directories should not widen who can read a map of someone's writing.

Never inside an unprotected Git worktree. The default location is under the
home directory, but `HOWLWRITER_IDENTITIES_DIR` and `HOWLWRITER_VOICES_DIR`
can point anywhere, including -- by accident -- into a checkout. Before
anything is written, the target is checked: if it sits inside a Git worktree
and Git would not ignore it, the write is refused with an explanation. A
`.gitignore` rule is not protection after the fact, so the check runs first.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from howlwriter.domain.io import atomic_write_text

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600


class PrivateLocationError(RuntimeError):
    """Raised when private data would be written somewhere Git could track it."""


def identities_root() -> Path:
    custom = os.environ.get("HOWLWRITER_IDENTITIES_DIR")
    if custom and custom.strip():
        return Path(custom.strip()).expanduser().resolve()
    return Path.home() / ".howlwriter" / "identities"


def preferences_path() -> Path:
    custom = os.environ.get("HOWLWRITER_PREFERENCES_FILE")
    if custom and custom.strip():
        return Path(custom.strip()).expanduser().resolve()
    return Path.home() / ".howlwriter" / "preferences.yaml"


def _git_worktree_of(path: Path) -> Path | None:
    """The top of the Git worktree containing `path`, if any.

    Walks up looking for `.git` rather than shelling out first, so the common
    case (a home directory that is not a repository) costs no subprocess.
    """
    current = path
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def assert_private_location(path: Path) -> None:
    """Refuse a location Git would track.

    A path inside a worktree is acceptable only when `git check-ignore`
    confirms it is ignored. If Git is unavailable the location is refused
    rather than assumed safe.
    """
    resolved = path.expanduser().resolve()
    worktree = _git_worktree_of(_nearest_existing(resolved))
    if worktree is None:
        return
    # Probe a path INSIDE the target: a directory rule such as `private/`
    # cannot match the directory's own path before it exists, because Git
    # cannot know it will be a directory. A child path makes that explicit.
    probe = resolved / ".howlwriter-ignore-probe"
    try:
        completed = subprocess.run(
            ["git", "-C", str(worktree), "check-ignore", "-q", "--no-index", str(probe)],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PrivateLocationError(
            f"{resolved} is inside the Git worktree {worktree} and Git could not be "
            f"asked whether it is ignored ({error}); refusing to write private data there"
        ) from error
    if completed.returncode != 0:
        raise PrivateLocationError(
            f"{resolved} is inside the Git worktree {worktree} and is not ignored by Git. "
            "Private voice data must never be trackable; choose a location outside the "
            "repository (the default is ~/.howlwriter/identities)."
        )


def ensure_private_dir(path: Path) -> Path:
    """Create `path` (and parents under it) with owner-only permissions."""
    assert_private_location(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, DIRECTORY_MODE)
    except OSError:
        pass
    return path


def write_private_text(path: Path, content: str) -> None:
    """Atomically write a private file and restrict it to the owner."""
    ensure_private_dir(path.parent)
    atomic_write_text(path, content)
    try:
        os.chmod(path, FILE_MODE)
    except OSError:
        pass


def write_private_json(path: Path, payload: Any) -> None:
    write_private_text(path, json.dumps(payload, indent=2, sort_keys=True, default=str))


def restrict_tree(path: Path) -> None:
    """Tighten permissions on an existing directory tree, e.g. a voice profile.

    `VoiceStore` predates this module and writes files with the default umask.
    Called after a profile build commits so personal profiles end up 0600 like
    everything else here, without changing how VoiceStore itself works.
    """
    if not path.exists():
        return
    for root, dirs, files in os.walk(path):
        try:
            os.chmod(root, DIRECTORY_MODE)
        except OSError:
            pass
        for name in files:
            try:
                os.chmod(os.path.join(root, name), FILE_MODE)
            except OSError:
                pass


def restrict_directory(path: Path) -> None:
    """Owner-only mode on one existing directory (no recursion, no content change)."""
    try:
        if path.is_dir():
            os.chmod(path, DIRECTORY_MODE)
    except OSError:
        pass
