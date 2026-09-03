"""Factual claim tracking.

A Claim never starts life SUPPORTED. Extraction only ever proposes UNVERIFIABLE
claims; a status of SUPPORTED/CONTRADICTED/PARTIALLY_SUPPORTED can only be
reached by attaching real Evidence through the provenance graph (see
domain/provenance.py). This is the mechanism, not just a convention, behind
"never invent a statistic merely because the existing one can't be verified."
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from howlwriter.domain.serialization import DataClassSerializationMixin


class ClaimType(enum.Enum):
    FACTUAL = "factual"
    STATISTICAL = "statistical"
    QUOTATION = "quotation"
    OPINION = "opinion"
    PREDICTION = "prediction"
    DEFINITION = "definition"


class VerificationStatus(enum.Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"
    OPINION = "opinion"
    INFERENCE = "inference"


class ClaimTemporalContext(str, enum.Enum):
    CURRENT_STATE = "CURRENT_STATE"
    HISTORICAL = "HISTORICAL"
    VERSION_SPECIFIC = "VERSION_SPECIFIC"
    TIME_INSENSITIVE = "TIME_INSENSITIVE"
    UNKNOWN = "UNKNOWN"


@dataclass
class DocumentSpan(DataClassSerializationMixin):
    paragraph_index: int
    sentence_index: int


@dataclass
class Claim(DataClassSerializationMixin):
    id: str
    text: str
    claim_type: ClaimType = ClaimType.FACTUAL
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIABLE
    confidence: float | None = None
    supporting_sources: list[str] = field(default_factory=list)
    contradicting_sources: list[str] = field(default_factory=list)
    notes: str = ""
    document_span: DocumentSpan | None = None
    temporal_context: ClaimTemporalContext = ClaimTemporalContext.UNKNOWN
    target_version: str | None = None
    target_family: str | None = None
    intentional_historical_use: bool = False
    historical_use_reason: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Claim:
        data = dict(data)
        if "claim_type" in data and isinstance(data["claim_type"], str):
            data["claim_type"] = ClaimType(data["claim_type"])
        if "verification_status" in data and isinstance(data["verification_status"], str):
            data["verification_status"] = VerificationStatus(data["verification_status"])
        if "temporal_context" in data and isinstance(data["temporal_context"], str):
            try:
                data["temporal_context"] = ClaimTemporalContext(data["temporal_context"])
            except ValueError:
                data["temporal_context"] = ClaimTemporalContext.UNKNOWN
        if "document_span" in data and isinstance(data["document_span"], dict):
            data["document_span"] = DocumentSpan.from_dict(data["document_span"])
        return super().from_dict(data)
