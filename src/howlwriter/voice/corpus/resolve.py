"""Turning `--voice jane` or `--voice-profile /path.json` into a profile.

One resolver so both spellings end up in the same place. `--voice-profile`
predates this feature and keeps working exactly as it did -- a path to a JSON
profile, or an author label that resolves to nothing -- while `--voice` names
a personal voice in the private registry.

Both funnel into `config.voice_profile`, which is the field the Humanizer
already reads, so nothing downstream needed a second way to receive a voice.
"""

from __future__ import annotations

from pathlib import Path

from howlwriter.domain.voice import VoiceProfile
from howlwriter.voice.corpus.store import VoiceStore, validate_name


def resolve_named_voice(name: str, *, root: Path | None = None) -> VoiceProfile:
    """Load a personal voice by name, or explain why it is not there."""
    store = VoiceStore(name, root=root)
    if not store.exists():
        available = VoiceStore.list_names(root)
        suffix = (
            f" Available voices: {', '.join(available)}."
            if available else
            " No voices have been built yet."
        )
        raise FileNotFoundError(
            f"no personal voice named '{store.name}'.{suffix} "
            f"Build one with: howlwriter voice build --name {store.name} --source <path>"
        )
    profile = store.load_profile()
    # Overrides live in their own file so a rebuild cannot clobber them, which
    # means they have to be re-attached on every load.
    profile.overrides = store.load_overrides()
    return profile


def profile_reference(name: str, *, root: Path | None = None) -> str:
    """The value to put in `config.voice_profile` for a named voice.

    A path rather than a bare name, so the existing loader resolves it with no
    change and a profile built here behaves identically to one a user wrote by
    hand and passed with --voice-profile.
    """
    store = VoiceStore(validate_name(name), root=root)
    if not store.exists():
        resolve_named_voice(name, root=root)   # raises with the helpful message
    return str(store.directory / "profile.json")


def resolve_voice_option(
    *,
    voice: str | None,
    voice_profile: str | None,
    root: Path | None = None,
) -> str | None:
    """Reconcile the two flags into one config value.

    Passing both is a mistake worth surfacing rather than silently resolving:
    the two could point at different profiles, and quietly picking one would
    make the output impossible to explain.
    """
    if voice and voice_profile:
        raise ValueError(
            "--voice and --voice-profile are alternatives; pass one. "
            "--voice names a personal voice in your local registry, "
            "--voice-profile points at a specific profile file."
        )
    if voice:
        return profile_reference(voice, root=root)
    return voice_profile
