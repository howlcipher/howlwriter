"""Safe deterministic filename generation and path sanitization."""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata


class PathTraversalError(ValueError):
    """Raised when an output filename or path attempts directory traversal."""


class OutputCollisionError(FileExistsError):
    """Raised when an output destination already exists and overwrite was not authorized."""


# Control characters, null bytes, and shell-sensitive characters
_UNSAFE_CHARS_RE = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*`$\'!;&()\[\]{}]')
_WHITESPACE_PUNCT_RE = re.compile(r"[\s\-_\/]+")


def sanitize_filename_base(title: str, max_length: int = 60) -> str:
    """Produces a clean, deterministic, shell-safe filename base from a document title.

    - Strips path separators, null bytes, and traversal tokens.
    - Normalizes unicode to NFKD (removing accents where practical).
    - Replaces spaces, slashes, and dashes with a single hyphen.
    - Converts to lowercase and bounds length at word boundaries where possible.
    """
    if not title or not title.strip():
        return "artifact"

    # Reject explicit directory traversal attempts
    raw = title.strip()
    if "\x00" in raw or ".." in raw:
        # Check if it attempts directory traversal
        parts = re.split(r"[/\\]+", raw)
        if any(p == ".." for p in parts):
            raise PathTraversalError(f"Path traversal sequence detected in title/name: {title!r}")

    # Unicode normalization
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")

    # Strip unsafe characters
    cleaned = _UNSAFE_CHARS_RE.sub(" ", normalized)

    # Collapse whitespace and dividers to single hyphens
    slug = _WHITESPACE_PUNCT_RE.sub("-", cleaned).strip("-.").lower()

    if not slug:
        return "artifact"

    # Truncate at max_length without cutting in the middle of a word if possible
    if len(slug) > max_length:
        truncated = slug[:max_length]
        if "-" in truncated:
            slug = truncated.rsplit("-", 1)[0]
        else:
            slug = truncated

    return slug or "artifact"


def safe_filename(title: str, extension: str, max_length: int = 60) -> str:
    """Generates a safe filename with normalized extension."""
    if "/" in title or "\\" in title:
        raise PathTraversalError(f"Directory separator not allowed in filename: {title!r}")
    base = sanitize_filename_base(title, max_length=max_length)
    ext = extension.strip()
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{base}{ext.lower()}"


def resolve_safe_output_path(
    destination: str | Path,
    default_dir: str | Path = "output",
    allow_absolute: bool = True,
) -> Path:
    """Resolves and validates an output path to prevent traversal surprises."""
    dest_path = Path(destination)

    # Check for null bytes
    if "\x00" in str(destination):
        raise PathTraversalError("Null byte in output path.")

    # Normalize path
    try:
        resolved = dest_path.expanduser().resolve()
    except Exception as exc:
        raise PathTraversalError(f"Invalid output path '{destination}': {exc}") from exc

    # If relative path was passed without directory component, put in default_dir
    if not dest_path.is_absolute() and len(dest_path.parts) == 1:
        out_dir = Path(default_dir).expanduser().resolve()
        resolved = out_dir / dest_path.name

    return resolved
