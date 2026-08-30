"""Layered config loading: defaults -> mode -> user profile -> project -> request.

Each layer is a partial mapping; only the keys a layer actually sets are
applied, field by field, on top of the previous layer's full config. A
project config that only sets banned_words does not clobber a mode's
citation_style -- that per-field merge is the entire point of the layering
model in the spec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from howlwriter.config.defaults import default_config
from howlwriter.config.schema import BannedWord, HowlWriterConfig
from howlwriter.domain.modes import WritingMode

MODE_OVERRIDES: dict[WritingMode, dict[str, Any]] = {
    WritingMode.CASUAL: {"humanization_strength": "high", "editing_strength": "low"},
    WritingMode.PROFESSIONAL: {"humanization_strength": "medium", "editing_strength": "medium"},
    WritingMode.LINKEDIN: {
        "humanization_strength": "high",
        "editing_strength": "low",
        "research_depth": "none",
    },
    WritingMode.TECHNICAL: {"humanization_strength": "low", "fact_checking_strength": "high"},
    WritingMode.DOCUMENTATION: {"humanization_strength": "low", "editing_strength": "medium"},
    WritingMode.ACADEMIC: {
        "fact_checking_strength": "high",
        "research_depth": "deep",
        "citation_style": "apa7",
        "editing_strength": "high",
    },
    WritingMode.EMAIL: {"humanization_strength": "medium", "editing_strength": "low"},
    WritingMode.ARTICLE: {"humanization_strength": "medium", "fact_checking_strength": "medium"},
    WritingMode.CUSTOM: {},
}


def _normalize_banned_words(raw: list[Any]) -> list[BannedWord]:
    normalized: list[BannedWord] = []
    for entry in raw:
        if isinstance(entry, str):
            normalized.append(BannedWord(word=entry))
        elif isinstance(entry, dict):
            normalized.append(BannedWord(word=entry["word"], replacement=entry.get("replacement")))
        else:
            raise TypeError(f"banned_words entries must be a string or a mapping, got {entry!r}")
    return normalized


def apply_overrides(config: HowlWriterConfig, overrides: dict[str, Any]) -> HowlWriterConfig:
    """Returns a new config with only the keys present in `overrides` replaced."""
    valid_fields = set(HowlWriterConfig.__dataclass_fields__)
    unknown = set(overrides) - valid_fields
    if unknown:
        raise ValueError(f"unknown config field(s): {sorted(unknown)}")

    data = config.to_dict()
    data.update(overrides)

    banned_words_raw = data.pop("banned_words", [])
    rebuilt = HowlWriterConfig.from_dict(data)
    rebuilt.banned_words = _normalize_banned_words(banned_words_raw)
    return rebuilt


def _load_yaml(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    return loaded or {}


class ConfigLoader:
    """Runs the full defaults -> mode -> user -> project -> request pipeline."""

    def load(
        self,
        *,
        mode: WritingMode | None = None,
        user_profile_path: str | Path | None = None,
        project_config_path: str | Path | None = None,
        request_overrides: dict[str, Any] | None = None,
    ) -> HowlWriterConfig:
        config = default_config()

        if mode is not None:
            config = apply_overrides(config, MODE_OVERRIDES.get(mode, {}))

        if user_profile_path is not None:
            config = apply_overrides(config, _load_yaml(user_profile_path))

        if project_config_path is not None:
            config = apply_overrides(config, _load_yaml(project_config_path))

        if request_overrides:
            config = apply_overrides(config, request_overrides)

        return config
