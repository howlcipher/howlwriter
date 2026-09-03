"""The private personal-voice registry on disk.

A personal voice is user data. It lives outside the repository, under the
same `~/.howlwriter` root the run records already use, and nothing in it is
ever committed, distributed, or turned into a shared style.

What is kept is derived and privacy-safe:

    profile.json    abstract traits, distributions, counts
    sources.json    per-source metadata for incremental rebuild
    features.json   cached feature vectors and abstract trait labels
    overrides.yaml  the user's own corrections, never regenerated
    build.json      counts, timings, providers, warnings

What is not kept is the writing itself. Raw and extracted prose is transient
-- it exists in memory during a build and is gone when the build ends, whether
it succeeded or failed. `sources.json` holds paths and hashes because a
rebuild genuinely needs them to tell a changed file from an unchanged one, and
because this directory is local private data; it holds no document content.

Builds are atomic. A rebuild assembles a complete new directory beside the
old one and swaps it in only after validation passes, so a provider outage
halfway through cannot leave a good profile half-overwritten.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

import yaml

from howlwriter.domain.io import atomic_write_text
from howlwriter.domain.voice import StructuralVector, VoiceOverrides, VoiceProfile
from howlwriter.voice.corpus.features import DocumentFeatures

PROFILE_FILE = "profile.json"
SOURCES_FILE = "sources.json"
FEATURES_FILE = "features.json"
OVERRIDES_FILE = "overrides.yaml"
BUILD_FILE = "build.json"

#: Names that are safe as a directory component and as a CLI argument.
_VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_OVERRIDES_TEMPLATE = """\
# User overrides for the '{name}' voice.
#
# Generated traits are observations and can be wrong. Anything set here is
# your stated intent, wins over what the corpus suggested, and survives every
# rebuild untouched.
#
# preserve: habits to keep even if the humanizer would smooth them away
# avoid:    habits to suppress even if the corpus shows them
# traits:   pin a specific trait to a specific value
#
# preserve:
#   - long flowing sentences when the argument needs them
# avoid:
#   - overly polished conclusions
# traits:
#   directness: high

preserve: []
avoid: []
traits: {{}}
notes: ""
"""


def voices_root() -> Path:
    """Where personal voices live.

    Follows the convention already set by the run records
    (`~/.howlwriter/runs`, overridable by environment) rather than inventing
    a second user-data location.
    """
    custom = os.environ.get("HOWLWRITER_VOICES_DIR")
    if custom and custom.strip():
        return Path(custom.strip()).expanduser().resolve()
    return Path.home() / ".howlwriter" / "voices"


def validate_name(name: str) -> str:
    """Normalize and check a voice name.

    The name becomes a directory component, so a name that could escape the
    voices root is rejected rather than sanitized -- silently rewriting a name
    would make `voice inspect` disagree with `voice build`.
    """
    normalized = (name or "").strip().lower()
    if not _VALID_NAME.match(normalized):
        raise ValueError(
            f"invalid voice name {name!r}: use lowercase letters, digits, hyphens and "
            "underscores, starting with a letter or digit (max 64 characters)"
        )
    return normalized


@dataclass
class SourceRecord:
    """Private per-source metadata. Enough to rebuild, no document content."""

    key: str
    path: str
    size: int = 0
    mtime: float = 0.0
    content_hash: str = ""
    feature_hash: str = ""
    parser: str = ""
    extraction_status: str = ""
    classification: str = ""
    inclusion: str = ""
    weight: float = 0.0
    context: str = ""
    context_confidence: float = 0.0
    split: str = ""
    group_id: str = ""
    duplicate_role: str = ""
    duplicate_relation: str = ""
    words: int = 0
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "SourceRecord":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


@dataclass
class BuildRecord:
    """Operational facts about a build. No document content."""

    built_at: str = ""
    duration_seconds: float = 0.0
    status: str = "unknown"
    roots: list[str] = field(default_factory=list)
    stages: dict[str, float] = field(default_factory=dict)
    providers: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    trait_analysis: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "BuildRecord":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})


class VoiceStore:
    """Read and write one named personal voice."""

    def __init__(self, name: str, root: Path | None = None) -> None:
        self.name = validate_name(name)
        self.root = Path(root) if root is not None else voices_root()
        self.directory = self.root / self.name

    # --- existence ---------------------------------------------------

    def exists(self) -> bool:
        return (self.directory / PROFILE_FILE).is_file()

    @classmethod
    def list_names(cls, root: Path | None = None) -> list[str]:
        base = Path(root) if root is not None else voices_root()
        if not base.is_dir():
            return []
        return sorted(
            entry.name for entry in base.iterdir()
            if entry.is_dir() and (entry / PROFILE_FILE).is_file()
        )

    # --- reading -----------------------------------------------------

    def load_structural_vectors(self) -> list[StructuralVector]:
        """Load compact structural vectors cached from training documents only.

        The feature cache also contains holdout, excluded, and review-held
        documents.  It is a cache, not an eligibility list.  Reconstructing an
        older profile from every cached entry silently contaminates both the
        training distribution and its holdout, so source records remain the
        authority for which keys may become anchors.
        """
        docs = self.load_features()
        sources = self.load_sources()
        eligible = {
            key
            for key, record in sources.items()
            if record.split == "train"
            and record.inclusion in ("include", "include_low_weight")
        }
        vectors: list[StructuralVector] = []
        for key, entry in docs.items():
            if key not in eligible:
                continue
            if not isinstance(entry, dict):
                continue
            feat_dict = entry.get("features")
            if not isinstance(feat_dict, dict):
                continue
            context = str(entry.get("context") or "")
            model_traits = entry.get("model_traits") or {}
            opening = model_traits.get("opening_behavior", "")
            closing = model_traits.get("conclusion_behavior", "")
            features = DocumentFeatures.from_dict(feat_dict)
            if features.words > 0:
                vectors.append(
                    features.to_structural_vector(
                        context=context,
                        opening_class=opening,
                        closing_class=closing,
                    )
                )
        return vectors

    def attach_structural_vectors(self, profile: VoiceProfile) -> None:
        """Re-attach cached structural vectors to a profile that lacks them.

        Structural vectors live in the feature cache rather than the profile
        file, so a profile loaded from JSON alone carries none. Both this store
        and the standalone loader in humanize/rewriter.py need the same
        re-attachment, so it lives here rather than being written twice.
        """
        if profile.structural_vectors:
            return
        vectors = self.load_structural_vectors()
        if not vectors:
            return
        profile.structural_vectors = vectors
        for ctx_name, ctx in profile.contexts.items():
            if not ctx.structural_vectors:
                ctx.structural_vectors = [v for v in vectors if v.context == ctx_name]

    def load_profile(self) -> VoiceProfile:
        path = self.directory / PROFILE_FILE
        if not path.is_file():
            raise FileNotFoundError(
                f"no voice named '{self.name}' in {self.root}. "
                f"Build one with: howlwriter voice build --name {self.name} --source <path>"
            )
        profile = VoiceProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
        self.attach_structural_vectors(profile)
        return profile

    def load_sources(self) -> dict[str, SourceRecord]:
        path = self.directory / SOURCES_FILE
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        return {
            key: SourceRecord.from_dict(value)
            for key, value in (data.get("sources") or {}).items()
        }

    def load_features(self) -> dict[str, dict]:
        path = self.directory / FEATURES_FILE
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("documents") or {}
        except (ValueError, OSError):
            return {}

    def load_overrides(self) -> VoiceOverrides:
        """Read user overrides, tolerating a hand-edited file.

        A malformed overrides file must never fail a rebuild silently in the
        other direction -- losing someone's corrections is worse than
        surfacing a parse error, so this raises rather than defaulting.
        """
        path = self.directory / OVERRIDES_FILE
        if not path.is_file():
            return VoiceOverrides()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            raise ValueError(f"{path} is not valid YAML: {error}") from error
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return VoiceOverrides(
            preserve=[str(x) for x in (data.get("preserve") or [])],
            avoid=[str(x) for x in (data.get("avoid") or [])],
            traits={str(k): str(v) for k, v in (data.get("traits") or {}).items()},
            notes=str(data.get("notes") or ""),
        )

    def load_build(self) -> BuildRecord:
        path = self.directory / BUILD_FILE
        if not path.is_file():
            return BuildRecord()
        try:
            return BuildRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            return BuildRecord()

    def load_roots(self) -> list[str]:
        """The source roots a previous build used, for `voice rebuild`."""
        return list(self.load_build().roots)

    # --- writing -----------------------------------------------------

    def stage(self) -> "StagedBuild":
        """Open a staging area for a new build of this voice."""
        return StagedBuild(self)

    def delete(self) -> bool:
        if not self.directory.exists():
            return False
        shutil.rmtree(self.directory)
        return True


class StagedBuild:
    """A complete new voice directory, assembled before it replaces the old.

    Used as a context manager. The staging directory is removed on the way
    out whether or not `commit` was called, so an abandoned or failed build
    leaves nothing behind and, critically, leaves any existing good profile
    exactly as it was.
    """

    def __init__(self, store: VoiceStore) -> None:
        self.store = store
        self.path: Path | None = None
        self._temp: tempfile.TemporaryDirectory | None = None
        self.committed = False

    def __enter__(self) -> "StagedBuild":
        self.store.root.mkdir(parents=True, exist_ok=True)
        # Staged beside the destination so the final move is a rename on the
        # same filesystem rather than a copy that could be interrupted.
        self._temp = tempfile.TemporaryDirectory(
            prefix=f".{self.store.name}.building.", dir=self.store.root
        )
        self.path = Path(self._temp.name)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._temp is not None:
            self._temp.cleanup()
            self._temp = None
        self.path = None

    # --- staged writes ---

    def write_profile(self, profile: VoiceProfile) -> None:
        self._write(PROFILE_FILE, profile.to_json())

    def write_sources(self, sources: dict[str, SourceRecord]) -> None:
        payload = {"sources": {key: asdict(record) for key, record in sorted(sources.items())}}
        self._write(SOURCES_FILE, json.dumps(payload, indent=2, sort_keys=True))

    def write_features(self, documents: dict[str, dict]) -> None:
        self._write(
            FEATURES_FILE,
            json.dumps({"documents": documents}, indent=2, sort_keys=True, default=str),
        )

    def write_build(self, record: BuildRecord) -> None:
        self._write(BUILD_FILE, json.dumps(asdict(record), indent=2, default=str))

    def write_overrides(self, overrides: VoiceOverrides, *, raw: str | None = None) -> None:
        """Persist overrides, preferring the user's own file verbatim.

        Round-tripping through the parser would drop their comments and
        formatting, so an existing file is copied through untouched and only
        a missing one is generated from the template.
        """
        if raw is not None:
            self._write(OVERRIDES_FILE, raw)
            return
        if overrides == VoiceOverrides():
            self._write(OVERRIDES_FILE, _OVERRIDES_TEMPLATE.format(name=self.store.name))
            return
        self._write(OVERRIDES_FILE, yaml.safe_dump(
            {
                "preserve": overrides.preserve,
                "avoid": overrides.avoid,
                "traits": overrides.traits,
                "notes": overrides.notes,
            },
            sort_keys=False, default_flow_style=False,
        ))

    def _write(self, filename: str, content: str) -> None:
        if self.path is None:
            raise RuntimeError("staged build is not open")
        atomic_write_text(self.path / filename, content)

    # --- commit ---

    def commit(self) -> Path:
        """Swap the staged directory in for the live one.

        The previous directory is moved aside first and only removed once the
        new one is in place, so an interruption leaves a recoverable state
        rather than no profile at all.
        """
        if self.path is None:
            raise RuntimeError("staged build is not open")
        if not (self.path / PROFILE_FILE).is_file():
            raise RuntimeError("refusing to commit a staged build with no profile.json")

        destination = self.store.directory
        previous = destination.with_name(f".{destination.name}.previous")

        if previous.exists():
            shutil.rmtree(previous)
        if destination.exists():
            destination.rename(previous)
        try:
            self.path.rename(destination)
        except OSError:
            if previous.exists() and not destination.exists():
                previous.rename(destination)
            raise
        finally:
            # The staged directory has moved; stop the context manager from
            # trying to clean up a path that no longer exists.
            if self._temp is not None:
                self._temp._finalizer.detach()  # type: ignore[attr-defined]
                self._temp = None
                self.path = None

        if previous.exists():
            shutil.rmtree(previous)
        self.committed = True
        return destination


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
