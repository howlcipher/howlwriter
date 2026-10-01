"""Typed, inspectable representation of an assignment's supporting materials.

The ledger answers, for every file in the materials directory: what it is,
what role it plays, whether text was really extracted, and whether that text
may be used as requirements and/or as evidence. A file's name is never
evidence; only extracted content is.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from howlwriter.domain.serialization import DataClassSerializationMixin

LEDGER_SCHEMA = "howlwriter.materials/v1"


class MaterialRole(str, enum.Enum):
    INSTRUCTIONS = "INSTRUCTIONS"
    RUBRIC = "RUBRIC"
    REFERENCE = "REFERENCE"
    USER_DATA = "USER_DATA"
    PRIOR_DRAFT = "PRIOR_DRAFT"
    AUXILIARY = "AUXILIARY"


class ExtractionStatus(str, enum.Enum):
    OK = "OK"
    EMPTY = "EMPTY"
    SCANNED_NO_TEXT = "SCANNED_NO_TEXT"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED_FOR_TEXT_EXTRACTION = "UNSUPPORTED_FOR_TEXT_EXTRACTION"
    REQUIRES_EXTERNAL_INSPECTION = "REQUIRES_EXTERNAL_INSPECTION"
    SKIPPED_TOO_LARGE = "SKIPPED_TOO_LARGE"
    SKIPPED_SYMLINK = "SKIPPED_SYMLINK"


# Roles whose content defines what must be done. They are requirements, never
# scholarly evidence.
REQUIREMENT_ROLES = (MaterialRole.INSTRUCTIONS, MaterialRole.RUBRIC)
# Roles whose extracted text may be cited as local evidence. A prior draft is
# the author's own earlier work, not a source, and is deliberately excluded.
EVIDENCE_ROLES = (MaterialRole.REFERENCE, MaterialRole.USER_DATA)

ROLE_SOURCE_EXPLICIT = "explicit"
ROLE_SOURCE_HEURISTIC = "heuristic"
ROLE_SOURCE_DEFAULT = "default"


@dataclass
class MaterialRecord(DataClassSerializationMixin):
    material_id: str
    path: str  # POSIX path relative to the materials root; never absolute
    name: str
    suffix: str
    size_bytes: int
    sha256: str | None
    role: MaterialRole
    role_source: str
    role_reason: str
    extraction_status: ExtractionStatus
    extraction_method: str = ""
    text_extracted: bool = False
    text_chars: int = 0
    truncated: bool = False
    may_be_requirements: bool = False
    may_be_evidence: bool = False
    evidence_depth: str | None = None  # a domain.source DEPTH_* value, or None
    warnings: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)


@dataclass
class MaterialLedger(DataClassSerializationMixin):
    root_label: str
    records: list[MaterialRecord] = field(default_factory=list)
    limits: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Requirement lines lifted from instructions/rubrics:
    # [{"material_id", "role", "text"}]. Present so they stay reviewable.
    derived_requirements: list[dict] = field(default_factory=list)
    schema: str = LEDGER_SCHEMA

    def counts(self) -> dict:
        by_role: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for r in self.records:
            by_role[r.role.value] = by_role.get(r.role.value, 0) + 1
            by_status[r.extraction_status.value] = by_status.get(r.extraction_status.value, 0) + 1
        return {
            "total": len(self.records),
            "text_extracted": sum(1 for r in self.records if r.text_extracted),
            "usable_as_evidence": sum(1 for r in self.records if r.may_be_evidence),
            "usable_as_requirements": sum(1 for r in self.records if r.may_be_requirements),
            "by_role": by_role,
            "by_status": by_status,
        }

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["counts"] = self.counts()
        return data


@dataclass
class MaterialScan:
    """Ledger plus the extracted text, which is deliberately kept out of the ledger."""

    ledger: MaterialLedger
    texts: dict[str, str] = field(default_factory=dict)  # material_id -> text
