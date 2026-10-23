"""Choosing a voice, and proving which one was applied.

Before this module, a voice could be requested in four places (`--voice`,
`--voice-profile`, an assignment spec's `voice_profile`, an outline's
`voice_profile`) and resolved in three different ways. A spec or outline
naming a registry voice (`voice_profile: william_v2`) reached a loader that
only understood file paths, loaded nothing, and the run wrote generic prose
while its provenance said `configured_voice_profile`.

Every entry point now goes through `resolve_reference`, which:

* resolves a registry name (``william_v2``) through the voice registry;
* accepts an explicit path to a profile file, as before;
* refuses a value that is both an existing file and a registry name;
* fails with `VoiceSelectionError` when an explicitly requested name or path
  cannot be loaded -- including a profile file that does not parse;
* keeps the legacy meaning of a free-text value (``"Jane Doe"``): an author
  label with no profile, recorded as exactly that;
* returns a `VoiceSelection` that records what was requested, from where,
  what was applied, and why, for provenance.

`select_for_context` adds automatic selection from an identity's context
profiles. A missing or unvalidated context profile is an error unless the
caller explicitly allows a generic fallback, and an allowed fallback is
recorded. Nothing ever falls back to a different person's or an older
profile.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from howlwriter.voice.corpus.store import VoiceStore

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

KIND_REGISTRY = "registry"
KIND_FILE = "file"
KIND_AUTHOR_LABEL = "author_label"
KIND_NONE = "none"


class VoiceSelectionError(ValueError):
    """An explicitly requested voice could not be applied."""


@dataclass
class VoiceSelection:
    requested: str | None = None
    source: str = "none"  # flag | spec | outline | auto | none
    kind: str = KIND_NONE
    applied: str | None = None  # profile name actually loaded
    path: str | None = None  # local path; never exported in provenance
    identity: str | None = None
    context: str | None = None
    fallback: str | None = None  # set only when a generic fallback was allowed
    reason: str = ""

    @property
    def config_value(self) -> str | None:
        """What `config.voice_profile` should hold for this selection."""
        if self.kind in (KIND_REGISTRY, KIND_FILE):
            return self.path
        if self.kind == KIND_AUTHOR_LABEL:
            return self.requested
        return None

    def to_provenance(self) -> dict:
        """Provenance-safe summary: names and decisions, no local paths."""
        data = asdict(self)
        data.pop("path")
        data["profile_applied"] = self.kind in (KIND_REGISTRY, KIND_FILE)
        return data


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or value.endswith((".json", ".yaml", ".yml"))


def _verify_loads(path: Path, requested: str) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        from howlwriter.domain.voice import VoiceProfile

        profile = VoiceProfile.from_dict(data)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise VoiceSelectionError(
            f"voice {requested!r} resolved to {path.name}, which could not be loaded "
            f"({type(error).__name__}); refusing to continue without the requested voice"
        ) from error
    return profile.profile_name or path.parent.name


def resolve_reference(
    value: str | None, *, source: str = "flag", root: Path | None = None
) -> VoiceSelection:
    """Resolve one requested voice value, strictly."""
    if value is None or not str(value).strip():
        return VoiceSelection(reason="no voice requested")
    requested = str(value).strip()

    is_name = bool(_NAME.match(requested))
    registry = VoiceStore(requested, root=root) if is_name else None
    in_registry = bool(registry and registry.exists())
    as_path = Path(requested).expanduser()
    is_file = as_path.is_file()

    if in_registry and is_file:
        raise VoiceSelectionError(
            f"voice {requested!r} is ambiguous: it names both a registry voice and a file in the "
            "current directory. Pass a path containing a '/' or rename one of them."
        )
    if in_registry:
        path = registry.directory / "profile.json"
        applied = _verify_loads(path, requested)
        return VoiceSelection(
            requested=requested,
            source=source,
            kind=KIND_REGISTRY,
            applied=applied or requested,
            path=str(path),
            reason=f"registry voice '{requested}'",
        )
    if is_file:
        applied = _verify_loads(as_path, requested)
        return VoiceSelection(
            requested=requested,
            source=source,
            kind=KIND_FILE,
            applied=applied,
            path=str(as_path.resolve()),
            reason="explicit profile file",
        )
    if is_name or _looks_like_path(requested):
        available = VoiceStore.list_names(root)
        hint = (
            f" Available voices: {', '.join(available)}." if available else " No voices are built."
        )
        raise VoiceSelectionError(
            f"no personal voice named {requested!r} ({source}).{hint} The run was stopped "
            "rather than writing without the requested voice."
        )
    return VoiceSelection(
        requested=requested,
        source=source,
        kind=KIND_AUTHOR_LABEL,
        reason="free-text value treated as an author label; no profile is applied",
    )


def select_for_context(
    context: str,
    *,
    identity: str,
    allow_generic: bool = False,
    identities_root: Path | None = None,
    root: Path | None = None,
) -> VoiceSelection:
    """The identity's profile for a writing context, or a clear refusal."""
    from howlwriter.voice.identity.store import IdentityStore

    store = IdentityStore(identity, root=identities_root)
    config = store.load_config()
    spec = next((p for p in config.profiles.values() if p.context == context), None)
    problem = ""
    if spec is None:
        problem = f"identity '{store.identity}' has no {context} profile"
    elif not VoiceStore(spec.voice, root=root).exists():
        problem = f"the {context} profile '{spec.voice}' has not been built"
    if not problem and spec is not None:
        selection = resolve_reference(spec.voice, source="auto", root=root)
        selection.identity = store.identity
        selection.context = context
        selection.reason = (
            f"{context} context routes to '{spec.voice}' for identity '{store.identity}'"
        )
        return selection
    if allow_generic:
        return VoiceSelection(
            source="auto",
            identity=store.identity,
            context=context,
            fallback="generic",
            reason=f"{problem}; generic writing explicitly allowed (--allow-generic)",
        )
    raise VoiceSelectionError(
        f"{problem}. Automatic voice selection will not substitute another profile; build it "
        "(`howlwriter voice build-identity`), name a voice with --voice, or pass --allow-generic."
    )


def context_for_mode(mode: str | None) -> str | None:
    from howlwriter.domain.genres import base_mode_name
    from howlwriter.evaluation.personal import MODE_PROFILE_CONTEXT

    return MODE_PROFILE_CONTEXT.get(base_mode_name(mode))


def apply_selection(
    config,
    *,
    voice: str | None = None,
    voice_profile: str | None = None,
    spec_value: str | None = None,
    spec_source: str = "spec",
    identity: str | None = None,
    auto_voice: bool = False,
    allow_generic: bool = False,
    mode: str | None = None,
    root: Path | None = None,
    identities_root: Path | None = None,
) -> VoiceSelection:
    """Choose the voice for a run and record the choice on `config`.

    Precedence: an explicit flag, then the spec's or outline's value, then
    automatic context selection (only when `auto_voice` or `identity` is
    given), then no voice. Any explicit request that cannot be honoured
    raises; nothing falls through to generic writing unless `allow_generic`
    was passed for automatic selection.
    """
    from howlwriter.voice.corpus.resolve import select_voice

    if voice or voice_profile:
        selection = select_voice(voice=voice, voice_profile=voice_profile, root=root)
    elif spec_value:
        selection = resolve_reference(spec_value, source=spec_source, root=root)
    elif identity or auto_voice:
        if not identity:
            from howlwriter.evaluation.personal import load_preferences

            identity = load_preferences().get("preferred_identity")
            if not identity:
                raise VoiceSelectionError(
                    "--auto-voice needs an identity: pass --identity or set preferred_identity in "
                    "~/.howlwriter/preferences.yaml"
                )
        context = context_for_mode(mode)
        if context is None:
            if not allow_generic:
                raise VoiceSelectionError(
                    f"mode {mode!r} has no context profile to select automatically; pass --mode "
                    "academic/professional/linkedin/technical/documentation, --voice, or --allow-generic"
                )
            selection = VoiceSelection(
                source="auto",
                identity=identity,
                fallback="generic",
                reason=f"mode {mode!r} has no context profile; generic writing explicitly allowed",
            )
        else:
            selection = select_for_context(
                context,
                identity=identity,
                allow_generic=allow_generic,
                identities_root=identities_root,
                root=root,
            )
    else:
        selection = VoiceSelection(reason="no voice requested")
    config.voice_profile = selection.config_value
    config.voice_selection = selection.to_provenance()
    return selection


def provenance_record(config, *, loaded: bool | None = None) -> dict | None:
    """The voice record for provenance.

    Uses the selection made at the entry point when there is one. A config
    whose `voice_profile` was set directly (programmatic callers) is recorded
    as unverified rather than resolved again here: recording is not the place
    to refuse a run. `loaded`, when known, is the pipeline's actual load
    outcome and overrides what resolution predicted.
    """
    if getattr(config, "voice_selection", None):
        record = dict(config.voice_selection)
    elif getattr(config, "voice_profile", None):
        try:
            record = resolve_reference(config.voice_profile, source="config").to_provenance()
        except VoiceSelectionError:
            record = {
                "requested": str(config.voice_profile).rsplit("/", 1)[-1],
                "source": "config",
                "kind": "unverified",
                "applied": None,
                "profile_applied": None,
                "reason": "set directly on the config and not resolved through the selection layer",
            }
    else:
        return None
    if loaded is not None:
        record["profile_loaded"] = loaded
        if loaded and record.get("profile_applied") is None:
            record["profile_applied"] = True
    return record


def add_selection_arguments(parser) -> None:
    """`--identity`, `--auto-voice`, `--allow-generic` for writing commands."""
    parser.add_argument(
        "--identity",
        default=None,
        help="Use this identity's context profile for the mode (e.g. william -> william-academic).",
    )
    parser.add_argument(
        "--auto-voice",
        action="store_true",
        help="Select the context profile automatically (uses preferred_identity if --identity is not given).",
    )
    parser.add_argument(
        "--allow-generic",
        action="store_true",
        help="If automatic selection finds no suitable profile, write without one (recorded in provenance).",
    )


def require_loaded(config, profile) -> None:
    """Stop a run whose selected profile resolved but did not load."""
    record = getattr(config, "voice_selection", None) or {}
    if profile is None and record.get("profile_applied"):
        raise VoiceSelectionError(
            f"voice {record.get('applied') or record.get('requested')!r} was selected but did not "
            "load; refusing to write without it"
        )
