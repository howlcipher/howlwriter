"""Directory exclusions that are enforced before anything is opened.

A user who says "never read my Gemini Gems folder" means the folder, at any
depth, under any capitalization a sync client happens to produce. They do not
mean "any file whose name contains the word gems". So matching works on whole
path components, after a normalization that is deliberately modest:

* Unicode NFKC, so a full-width or composed variant is the same name;
* case folding, so `Gemini Gems` and `GEMINI GEMS` are one name;
* separators (whitespace, `_`, `-`, `.`) collapsed, so `gemini_gems` and
  `gemini-gems` match too, and a spaceless comparison so `GeminiGems` does.

What it does not do is substring matching. `My Gemini Gems Notes.docx` is a
file, not the excluded directory, and `gemini gems backup` is a different
directory name. A rule that excluded those would be guessing at intent, and
guessing wrong in the permissive direction is the failure that matters here,
so the rule is exact-after-normalization and nothing looser.

The walker consults this before it recurses into a directory, so nothing
inside an excluded directory is listed, statted, read, classified, or cached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

#: The three directories William asked never to be traversed. They are the
#: defaults for an identity job created with `--identity william`, and are
#: written into that identity's private config rather than hardcoded into the
#: generic scanner: another person's identity gets their own list.
WILLIAM_REQUIRED_EXCLUSIONS: tuple[str, ...] = ("gemini gems", "retroarchsaves", "shared drives")

#: Directories that are never authored prose and are pruned for every scan:
#: version-control internals and dependency caches. Counted, not listed.
NOISE_DIRECTORIES: tuple[str, ...] = (
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "site-packages",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".gradle",
    ".idea",
)

_SEPARATORS = re.compile(r"[\s_\-.]+")


def normalize_component(name: str) -> str:
    """Normalize one path component for exclusion comparison."""
    value = unicodedata.normalize("NFKC", name or "").casefold()
    value = _SEPARATORS.sub(" ", value).strip()
    return value


def _compact(normalized: str) -> str:
    return normalized.replace(" ", "")


@dataclass
class ExclusionPolicy:
    """Which directory names a scan must never enter."""

    required: tuple[str, ...] = ()
    additional: tuple[str, ...] = ()
    prune_noise: bool = True
    _keys: set[str] = field(default_factory=set, init=False, repr=False)
    _noise: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        for name in (*self.required, *self.additional):
            normalized = normalize_component(name)
            if not normalized:
                continue
            self._keys.add(normalized)
            self._keys.add(_compact(normalized))
        if self.prune_noise:
            self._noise = {name.casefold() for name in NOISE_DIRECTORIES}

    @property
    def names(self) -> list[str]:
        """Every configured exclusion, normalized, for reporting."""
        seen: dict[str, None] = {}
        for name in (*self.required, *self.additional):
            normalized = normalize_component(name)
            if normalized:
                seen[normalized] = None
        return list(seen)

    def excludes(self, component: str) -> bool:
        """True when a directory with this name must not be entered."""
        normalized = normalize_component(component)
        if not normalized:
            return False
        return normalized in self._keys or _compact(normalized) in self._keys

    def is_noise(self, component: str) -> bool:
        return component.casefold() in self._noise

    def path_is_excluded(self, relative_parts: tuple[str, ...] | list[str]) -> bool:
        """True when any directory component of a relative path is excluded.

        Used as a second line of defence wherever a path arrives from
        somewhere other than the walker (a ledger written by an older version,
        a review file a user edited, a rename detected after the fact).
        """
        directories = list(relative_parts)[:-1]
        return any(self.excludes(part) for part in directories)

    def to_dict(self) -> dict:
        return {
            "required": list(self.required),
            "additional": list(self.additional),
            "prune_noise": self.prune_noise,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "ExclusionPolicy":
        data = data or {}
        return cls(
            required=tuple(str(x) for x in data.get("required", ()) or ()),
            additional=tuple(str(x) for x in data.get("additional", ()) or ()),
            prune_noise=bool(data.get("prune_noise", True)),
        )
