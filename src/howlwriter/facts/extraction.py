"""Claim extraction.

HeuristicClaimExtractor is real, deterministic code: it finds candidate
factual claims by pattern (numbers/percentages, or statistical-attribution
markers like "according to") and returns them all as UNVERIFIABLE. It never
guesses SUPPORTED -- that requires real Evidence attached through the
provenance graph (see domain/provenance.py), which requires either a human
supplying sources or a configured ClaimVerifier/Researcher. This is the
mechanism, not a promise, behind "never invent a statistic."
"""

from __future__ import annotations

import re
from typing import Protocol

from howlwriter.domain.claim import Claim, ClaimType, DocumentSpan, VerificationStatus
from howlwriter.domain.document import Document
from howlwriter.integration.model_role import NotConfiguredRole, WritingRole

_NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")
_STAT_MARKERS = (
    "according to",
    "studies show",
    "study shows",
    "research shows",
    "data shows",
    "reports indicate",
    "study found",
    "survey found",
)


class HeuristicClaimExtractor:
    def extract(self, document: Document, *, include_non_body: bool = False) -> list[Claim]:
        claims: list[Claim] = []
        sentence_stream = (
            document.all_sentences()
            if include_non_body
            else document.body_sentences()
        )
        for p_index, s_index, sentence in sentence_stream:
            has_number = bool(_NUMBER.search(sentence.text))
            marker = next((m for m in _STAT_MARKERS if m in sentence.text.lower()), None)
            if not has_number and marker is None:
                continue

            claim_type = ClaimType.STATISTICAL if has_number else ClaimType.FACTUAL
            reason = "numeric content" if has_number else f'attribution marker "{marker}"'
            claims.append(
                Claim(
                    id=f"claim-{len(claims) + 1:03d}",
                    text=sentence.text,
                    claim_type=claim_type,
                    verification_status=VerificationStatus.UNVERIFIABLE,
                    document_span=DocumentSpan(paragraph_index=p_index, sentence_index=s_index),
                    notes=f"Flagged by heuristic extractor ({reason}).",
                )
            )
        return claims


class ModelClaimExtractor(Protocol):
    role: WritingRole

    def extract(self, document: Document) -> list[Claim]: ...


class NotConfiguredClaimExtractor(NotConfiguredRole):
    def __init__(self) -> None:
        super().__init__(WritingRole.FACT_CHECKER)

    def extract(self, document: Document) -> list[Claim]:
        return self.run(document)
