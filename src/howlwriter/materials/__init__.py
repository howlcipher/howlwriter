"""Assignment-materials intake: inventory, extraction, requirements, evidence."""

from howlwriter.materials.convert import (
    derive_requirements,
    extract_requirement_lines,
    materials_to_sources,
)
from howlwriter.materials.models import (
    ExtractionStatus,
    MaterialLedger,
    MaterialRecord,
    MaterialRole,
    MaterialScan,
)
from howlwriter.materials.scan import scan_materials

__all__ = [
    "ExtractionStatus",
    "MaterialLedger",
    "MaterialRecord",
    "MaterialRole",
    "MaterialScan",
    "derive_requirements",
    "extract_requirement_lines",
    "materials_to_sources",
    "scan_materials",
]
