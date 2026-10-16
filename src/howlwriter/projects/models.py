"""Records of a Source Intelligence project: sources, evidence, requirements, actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PROJECT_SCHEMA = "howlwriter.project/v1"

# --- source categories -------------------------------------------------------

INSTRUCTIONS = "assignment_instructions"
RUBRIC = "rubric"
REFERENCE = "supporting_reference"
EXPERIMENTAL = "experimental_evidence"
SCREENSHOT = "screenshot"
PACKET_CAPTURE = "packet_capture"
MULTIMEDIA = "multimedia"
USER_DRAFT = "user_draft"
OUTPUT_DOCUMENT = "output_document"
UNKNOWN = "unknown"

CATEGORIES = (
    INSTRUCTIONS,
    RUBRIC,
    REFERENCE,
    EXPERIMENTAL,
    SCREENSHOT,
    PACKET_CAPTURE,
    MULTIMEDIA,
    USER_DRAFT,
    OUTPUT_DOCUMENT,
    UNKNOWN,
)
#: Categories whose content defines what to produce. Never evidence of work.
REQUIREMENT_CATEGORIES = (INSTRUCTIONS, RUBRIC)
#: Categories that record what was actually observed in the user's work.
OBSERVATION_CATEGORIES = (EXPERIMENTAL, SCREENSHOT, PACKET_CAPTURE)

# --- evidence status ---------------------------------------------------------

DIRECTLY_OBSERVED = "directly_observed"  # measured from the user's own artefact
EXTRACTED = "extracted_from_source"  # stated by a document or recording
DERIVED = "derived_by_calculation"  # computed deterministically from evidence
INTERPRETATION = "supported_interpretation"  # a reading of evidence, with support named
INFERENCE = "tentative_inference"  # plausible, not established
CONTRADICTED = "contradicted"
MISSING = "unknown_or_missing"

EVIDENCE_STATUSES = (DIRECTLY_OBSERVED, EXTRACTED, DERIVED, INTERPRETATION, INFERENCE, CONTRADICTED, MISSING)
#: Statuses that may be written as fact.
FACTUAL_STATUSES = (DIRECTLY_OBSERVED, EXTRACTED, DERIVED)

# --- requirement status ------------------------------------------------------

SATISFIED = "satisfied_with_evidence"
PARTIAL = "partially_satisfied"
PENDING = "pending_user_work"
BLOCKED = "blocked"
NOT_APPLICABLE = "not_applicable"


def _from(cls, data: dict):
    names = {f for f in cls.__dataclass_fields__}
    return cls(**{k: v for k, v in (data or {}).items() if k in names})


@dataclass
class SourceRecord:
    source_id: str
    path: str  # relative to the project root, POSIX
    suffix: str
    size: int
    mtime: float
    sha256: str = ""
    category: str = UNKNOWN
    category_source: str = "heuristic"  # heuristic | user
    category_reason: str = ""
    adapter: str = ""
    status: str = "pending"  # pending | extracted | partial | unavailable | failed | skipped
    status_reason: str = ""
    evidence_count: int = 0
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    analysis_version: int = 0
    present: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SourceRecord":
        return _from(cls, data)


@dataclass
class EvidenceItem:
    evidence_id: str
    source_id: str
    source_path: str
    source_type: str  # pdf | docx | text | image | video | audio | pcap | web | browser
    category: str
    method: str  # e.g. pypdf-text, rapidocr, tshark-4.6.8, faster-whisper-base
    status: str
    location: str  # human-readable exact location ("page 4", "frames 216-240")
    locator: dict[str, Any] = field(default_factory=dict)  # machine-readable location
    excerpt: str = ""  # short supporting excerpt (bounded)
    observation: dict[str, Any] = field(default_factory=dict)  # structured finding
    confidence: str = ""  # high | medium | low, with limitations below
    limitations: list[str] = field(default_factory=list)
    extracted_at: str = ""
    source_sha256: str = ""
    citation: str = ""
    kind: str = ""  # text | requirement_text | ocr | transcript | frame | packet_summary | ...

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceItem":
        return _from(cls, data)


@dataclass
class Requirement:
    requirement_id: str
    text: str
    # section | experiment | evidence | screenshot | comparison | citation | formatting | deliverable | other
    kind: str
    source_id: str
    location: str
    status: str = PENDING
    status_reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    user_status: str = ""  # optional user override (e.g. not_applicable)
    user_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Requirement":
        return _from(cls, data)


@dataclass
class BrowserAction:
    action_id: str
    mode: str  # research | observe | interactive
    kind: str  # navigate | read | screenshot | click | fill | submit
    url: str
    target: str = ""
    value_redacted: bool = False
    requested_at: str = ""
    decided_at: str = ""
    decision: str = ""  # auto | approved | denied | pending
    performed_at: str = ""
    outcome: str = ""  # ok | failed | blocked
    page_title: str = ""
    changed_state: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BrowserAction":
        return _from(cls, data)
