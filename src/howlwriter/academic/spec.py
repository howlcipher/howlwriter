"""Assignment specification and validator for academic paper workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import yaml

from howlwriter.domain.serialization import DataClassSerializationMixin


@dataclass
class SourceRequirements(DataClassSerializationMixin):
    minimum_sources: int = 4
    prefer_primary_sources: bool = True
    scholarly_or_authoritative: bool = True
    allowed_types: list[str] = field(default_factory=list)


@dataclass
class AssignmentSpec(DataClassSerializationMixin):
    title: str = ""
    topic: str = ""
    type: str = "academic"
    target_words: int = 2000
    word_tolerance_percent: float = 10.0
    citation_style: str = "apa7"
    source_requirements: SourceRequirements = field(default_factory=SourceRequirements)
    requirements: list[str] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)
    voice_profile: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.source_requirements, dict):
            self.source_requirements = SourceRequirements.from_dict(self.source_requirements)
        if not self.title and self.topic:
            # Use first line or up to 60 chars of topic as default title
            clean_topic = self.topic.strip().split("\n")[0]
            self.title = clean_topic[:60] + ("..." if len(clean_topic) > 60 else "")
        elif not self.topic and self.title:
            self.topic = self.title


def validate_assignment_spec(spec: AssignmentSpec) -> list[str]:
    """Validates an AssignmentSpec and returns a list of error messages (empty if valid)."""
    errors: list[str] = []

    if not spec.title and not spec.topic:
        errors.append("Assignment specification must include a title or topic.")

    if spec.target_words <= 0:
        errors.append(
            f"target_words must be a positive integer, got {spec.target_words}."
        )

    if spec.word_tolerance_percent < 0 or spec.word_tolerance_percent > 100:
        errors.append(
            f"word_tolerance_percent must be between 0 and 100, got {spec.word_tolerance_percent}."
        )

    if spec.citation_style.lower() not in ("apa7", "apa"):
        errors.append(
            f"Unsupported citation_style '{spec.citation_style}'. Currently supported: apa7."
        )

    if spec.source_requirements.minimum_sources < 0:
        errors.append(
            f"minimum_sources must be non-negative, got {spec.source_requirements.minimum_sources}."
        )

    return errors


def load_assignment_spec(source: str | Path | dict[str, Any]) -> AssignmentSpec:
    """Loads and validates an AssignmentSpec from a YAML/JSON file path, string, or dict."""
    if isinstance(source, dict):
        raw_data = dict(source)
    else:
        path = Path(source)
        if path.is_file():
            text = path.read_text(encoding="utf-8")
        else:
            text = str(source)

        try:
            raw_data = yaml.safe_load(text)
        except Exception:
            try:
                raw_data = json.loads(text)
            except Exception as exc:
                raise ValueError(f"Failed to parse assignment spec YAML/JSON: {exc}")

    if not isinstance(raw_data, dict):
        raise ValueError(
            f"Assignment spec must be a mapping/dict, got {type(raw_data).__name__}"
        )

    # Parse source_requirements nested dict
    sr_data = raw_data.get("source_requirements")
    if isinstance(sr_data, dict):
        sr = SourceRequirements.from_dict(sr_data)
        raw_data["source_requirements"] = sr
    elif sr_data is None:
        raw_data["source_requirements"] = SourceRequirements()

    spec = AssignmentSpec.from_dict(raw_data)
    errors = validate_assignment_spec(spec)
    if errors:
        raise ValueError(f"Invalid assignment spec: {'; '.join(errors)}")

    return spec
