"""Bridge between the materials scan and the academic pipeline.

Precedence of what the writer may rely on:

1. The assignment's own requirements (spec + instructions/rubric text). These
   say what must be done and are never evidence.
2. Local material with extracted text, and user-supplied sources. These enter
   the same evidence pool and the same relevance/authority/freshness/citation
   gates as everything else.
3. Automatic external research, consulted only when the pool above does not
   already satisfy the minimum-source requirement.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from howlwriter.academic.research import classify_source_relevance
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.domain.source import Source
from howlwriter.materials import (
    MaterialScan,
    derive_requirements,
    materials_to_sources,
    scan_materials,
)


@dataclass
class MaterialsIntake:
    spec: AssignmentSpec
    sources: list[Source]
    scan: MaterialScan | None


def resolve_materials_dir(
    spec: AssignmentSpec,
    explicit: str | Path | None,
    base_dir: str | Path | None,
) -> Path | None:
    """CLI/explicit value wins; a spec value is relative to the spec's folder."""
    if explicit:
        return Path(explicit)
    if spec.materials.directory:
        p = Path(spec.materials.directory)
        return p if p.is_absolute() or base_dir is None else Path(base_dir) / p
    return None


def apply_materials(
    spec: AssignmentSpec,
    existing_sources: list[Source] | None,
    materials_dir: str | Path | None,
    *,
    exclude: list[str | Path] | None = None,
) -> MaterialsIntake:
    """Scan ``materials_dir`` and fold the result into the spec and source pool.

    Returns a copy of the spec (the caller's is not mutated) whose requirements
    gain the instruction/rubric lines, and the evidence pool in precedence
    order: local materials first, then caller-supplied sources.
    """
    existing = list(existing_sources or [])
    if materials_dir is None:
        return MaterialsIntake(spec=spec, sources=existing, scan=None)

    scan = scan_materials(materials_dir, overrides=spec.materials.roles, exclude=exclude)
    new_spec = copy.deepcopy(spec)
    new_spec.requirements = list(spec.requirements) + derive_requirements(scan, spec.requirements)

    def _relevance(src: Source) -> str:
        return classify_source_relevance(src, topic=spec.topic, query=spec.title)

    local = materials_to_sources(scan, classify_relevance=_relevance)
    return MaterialsIntake(spec=new_spec, sources=local + existing, scan=scan)
