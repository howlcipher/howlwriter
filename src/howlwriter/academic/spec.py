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
    allow_historical_sources: bool = False
    historical_sources_allowed: list[str] = field(default_factory=list)


@dataclass
class LengthConstraints(DataClassSerializationMixin):
    """Optional hard/soft length limits layered on top of target_words.

    All fields default to None (or the conventional academic words-per-page
    estimate), so an assignment spec that only sets target_words/
    word_tolerance_percent behaves exactly as it did before this field existed.
    """

    max_words: int | None = None
    max_pages: float | None = None
    target_page_min: float | None = None
    target_page_max: float | None = None
    words_per_page: float = 275.0


@dataclass
class SectionSpec(DataClassSerializationMixin):
    id: str
    title: str
    prompt: str = ""
    target_words: int | None = None
    requirements: list[str] = field(default_factory=list)


@dataclass
class OutputLocalSpec(DataClassSerializationMixin):
    directory: str = "output"
    formats: list[str] = field(default_factory=list)
    overwrite: bool = False


@dataclass
class OutputPublishSpec(DataClassSerializationMixin):
    type: str = "google_docs"
    title: str = ""
    folder: str | None = None
    update_doc_id: str | None = None
    update_mode: str = "create"  # create | replace | append


@dataclass
class OutputSpec(DataClassSerializationMixin):
    local: OutputLocalSpec = field(default_factory=OutputLocalSpec)
    publish: OutputPublishSpec | None = None
    sections: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.local, dict):
            self.local = OutputLocalSpec.from_dict(self.local)
        if isinstance(self.publish, dict):
            self.publish = OutputPublishSpec.from_dict(self.publish)


@dataclass
class AssignmentSpec(DataClassSerializationMixin):
    title: str = ""
    topic: str = ""
    type: str = "academic"
    target_words: int = 2000
    word_tolerance_percent: float = 10.0
    citation_style: str = "apa7"
    source_requirements: SourceRequirements = field(default_factory=SourceRequirements)
    length_constraints: LengthConstraints = field(default_factory=LengthConstraints)
    requirements: list[str] = field(default_factory=list)
    # Exact technical identifiers (CVE IDs, ATT&CK technique IDs, etc.) known
    # to be legitimate for this assignment even if a source's retrieved_text
    # doesn't happen to quote them verbatim -- assignment-level "verified"
    # grounding, distinct from incidental prose overlap in requirements/topic.
    known_identifiers: list[str] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)
    voice_profile: str | None = None
    output: OutputSpec = field(default_factory=OutputSpec)
    sections: list[SectionSpec] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.source_requirements, dict):
            self.source_requirements = SourceRequirements.from_dict(self.source_requirements)
        if isinstance(self.length_constraints, dict):
            self.length_constraints = LengthConstraints.from_dict(self.length_constraints)
        if isinstance(self.output, dict):
            self.output = OutputSpec.from_dict(self.output)
        elif self.output is None:
            self.output = OutputSpec()
        if self.sections and isinstance(self.sections[0], dict):
            self.sections = [SectionSpec.from_dict(s) for s in self.sections]
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

    lc = spec.length_constraints
    if lc.max_words is not None and lc.max_words <= 0:
        errors.append(f"length_constraints.max_words must be positive, got {lc.max_words}.")
    if lc.max_pages is not None and lc.max_pages <= 0:
        errors.append(f"length_constraints.max_pages must be positive, got {lc.max_pages}.")
    if lc.words_per_page <= 0:
        errors.append(
            f"length_constraints.words_per_page must be positive, got {lc.words_per_page}."
        )
    if lc.target_page_min is not None and lc.target_page_min <= 0:
        errors.append(
            f"length_constraints.target_page_min must be positive, got {lc.target_page_min}."
        )
    if lc.target_page_max is not None and lc.target_page_max <= 0:
        errors.append(
            f"length_constraints.target_page_max must be positive, got {lc.target_page_max}."
        )
    if (
        lc.target_page_min is not None
        and lc.target_page_max is not None
        and lc.target_page_min > lc.target_page_max
    ):
        errors.append(
            "length_constraints.target_page_min must be <= target_page_max "
            f"(got {lc.target_page_min} > {lc.target_page_max})."
        )

    if not errors:
        # Cross-check that the hard ceiling doesn't conflict with the
        # requested soft target range (e.g. a max_words tighter than the
        # words a page-derived target_page_min would already require).
        from howlwriter.academic.length import resolve_length_bounds

        bounds = resolve_length_bounds(spec)
        if bounds.min_words > bounds.max_words:
            errors.append(
                "length_constraints produce a contradictory range: the resolved minimum "
                f"({bounds.min_words} words) exceeds the resolved maximum ({bounds.max_words} words)."
            )

    # Validate output specification if provided
    if spec.output and spec.output.local:
        supported_formats = {"md", "markdown", "docx", "pdf"}
        for fmt in spec.output.local.formats:
            if fmt.lower().lstrip(".") not in supported_formats:
                errors.append(
                    f"Unsupported output format '{fmt}'. Supported formats: {', '.join(sorted(supported_formats))}."
                )

    if spec.output and spec.output.publish:
        pub = spec.output.publish
        supported_types = {"google_docs", "gdocs", "google", "local"}
        if pub.type.lower() not in supported_types:
            errors.append(
                f"Unsupported publish destination '{pub.type}'. Supported types: {', '.join(sorted(supported_types))}."
            )
        if pub.update_mode.lower() not in ("create", "replace", "append"):
            errors.append(
                f"Invalid publish update_mode '{pub.update_mode}'. Supported modes: create, replace, append."
            )

    return errors


def load_assignment_spec(source: str | Path | dict[str, Any]) -> AssignmentSpec:
    """Loads and validates an AssignmentSpec from a YAML/JSON file path, string, or dict."""
    if isinstance(source, dict):
        raw_data = dict(source)
    else:
        text = str(source)
        if "\n" not in text:
            try:
                p = Path(source)
                if p.is_file():
                    text = p.read_text(encoding="utf-8")
            except (OSError, ValueError):
                pass

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

    # Parse length_constraints nested dict
    lc_data = raw_data.get("length_constraints")
    if isinstance(lc_data, dict):
        raw_data["length_constraints"] = LengthConstraints.from_dict(lc_data)
    elif lc_data is None:
        raw_data["length_constraints"] = LengthConstraints()

    # Parse output nested dict
    out_data = raw_data.get("output")
    if isinstance(out_data, dict):
        raw_data["output"] = OutputSpec.from_dict(out_data)
    elif out_data is None:
        raw_data["output"] = OutputSpec()

    spec = AssignmentSpec.from_dict(raw_data)
    errors = validate_assignment_spec(spec)
    if errors:
        raise ValueError(f"Invalid assignment spec: {'; '.join(errors)}")

    return spec
