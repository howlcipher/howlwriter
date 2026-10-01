"""Turn a material scan into pipeline inputs: requirements and local sources.

Requirements come only from INSTRUCTIONS/RUBRIC text. Sources come only from
materials whose text was genuinely extracted and whose role permits evidence.
Both conversions are deterministic and make no model calls.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from howlwriter.domain.source import (
    DEPTH_FULL_TEXT,
    ORIGIN_ASSIGNMENT_MATERIALS,
    RELEVANCE_SUPPORTING,
    Source,
    SourceType,
)
from howlwriter.materials.models import MaterialRole, MaterialScan

MAX_REQUIREMENTS_PER_MATERIAL = 40
_BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)]|\([a-z0-9]\)|[a-z][.)])\s+(.*\S)\s*$", re.I)
_MODAL = re.compile(r"\b(must|shall|required? to|should|needs? to|is required|are required)\b", re.I)
_MIN_LEN, _MAX_LEN = 12, 300


def _clean(line: str) -> str:
    line = re.sub(r"^\s*#+\s*", "", line)
    return re.sub(r"\s+", " ", line).strip()


def extract_requirement_lines(text: str) -> list[str]:
    """Bullet/numbered lines and sentences with an obligation word, in order."""
    found: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        c = _clean(candidate)
        key = c.lower()
        if _MIN_LEN <= len(c) <= _MAX_LEN and key not in seen:
            seen.add(key)
            found.append(c)

    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = _BULLET.match(raw)
        if m:
            add(m.group(1))
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", raw.strip()):
            if _MODAL.search(sentence):
                add(sentence)
    return found[:MAX_REQUIREMENTS_PER_MATERIAL]


def derive_requirements(scan: MaterialScan, existing: list[str] | None = None) -> list[str]:
    """Return NEW requirement strings (not already in ``existing``) and record
    them on the ledger so each is traceable to its material."""
    have = {r.strip().lower() for r in (existing or [])}
    new: list[str] = []
    scan.ledger.derived_requirements = []
    for rec in scan.ledger.records:
        if not rec.may_be_requirements:
            continue
        for line in extract_requirement_lines(scan.texts.get(rec.material_id, "")):
            if line.lower() in have:
                continue
            have.add(line.lower())
            new.append(line)
            scan.ledger.derived_requirements.append(
                {"material_id": rec.material_id, "role": rec.role.value, "text": line}
            )
    return new


def _title_from(name: str, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            if len(stripped) <= 120 and line.lstrip().startswith("#"):
                return stripped
            break
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    return re.sub(r"[_\-]+", " ", stem).strip() or name


def materials_to_sources(
    scan: MaterialScan,
    *,
    classify_relevance: Callable[[Source], str] | None = None,
) -> list[Source]:
    """Evidence-eligible materials as Sources, in ledger order.

    Relevance is classified by the caller's classifier (the same one used for
    researched sources) so local files cannot skip the relevance gate. Without
    a classifier, relevance is SUPPORTING, never DIRECT.
    """
    sources: list[Source] = []
    for rec in scan.ledger.records:
        if not rec.may_be_evidence:
            continue
        text = scan.texts.get(rec.material_id, "")
        if not text.strip():
            continue
        src = Source(
            id=rec.material_id,
            title=_title_from(rec.name, text),
            authors=[],
            source_type=SourceType.DATASET if rec.role == MaterialRole.USER_DATA else SourceType.OTHER,
            retrieved_text=text,
            reliability_notes=(
                f"Local assignment material ({rec.role.value}): {rec.path}; "
                f"extracted via {rec.extraction_method}; sha256 {rec.sha256 or 'unknown'}"
            ),
            relevance=RELEVANCE_SUPPORTING,
            evidence_depth=rec.evidence_depth or DEPTH_FULL_TEXT,
            origin=ORIGIN_ASSIGNMENT_MATERIALS,
            material_id=rec.material_id,
            content_sha256=rec.sha256,
        )
        if classify_relevance is not None:
            src.relevance = classify_relevance(src)
        sources.append(src)
    return sources
