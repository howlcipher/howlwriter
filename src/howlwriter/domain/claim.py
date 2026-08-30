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
