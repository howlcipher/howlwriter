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
_ENUM_PREFIX = re.compile(r"(?:^\s*|[\n:]\s*)(?:\(?\d+[\.\)]|\[\d+\])\s*")
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
_WORD_NUMBERS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"twenty|thirty|forty|fifty|hundred|thousand|million)\s+"
    r"(?:minutes?|hours?|days?|weeks?|months?|years?|seconds?|percent|dollars?|steps?|folds?)\b",
    re.IGNORECASE,
)
_EXPERIENTIAL_MARKERS = re.compile(
    r"\b(?:we|i)\s+(?:replaced|eliminated|saved|built|migrated|reduced|increased|"
    r"automated|deployed|rewrote|cut|slashed|decreased|overhauled|triaged|resolved)\b",
    re.IGNORECASE,
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
            text = sentence.text
            # Strip list item enumeration prefixes (e.g., "1.", "(2)", "[3]") to avoid false positives
            clean_text = _ENUM_PREFIX.sub("", text)

            has_number = bool(_NUMBER.search(clean_text))
            word_number_match = _WORD_NUMBERS.search(clean_text)
            marker = next((m for m in _STAT_MARKERS if m in clean_text.lower()), None)
            experiential = _EXPERIENTIAL_MARKERS.search(clean_text)

            if not has_number and not word_number_match and marker is None and not experiential:
                continue

            if has_number or word_number_match:
                claim_type = ClaimType.STATISTICAL
                matched_word = word_number_match.group(0) if word_number_match else ""
                reason = "numeric content" if has_number else f'quantitative phrase "{matched_word}"'
            elif experiential:
                claim_type = ClaimType.FACTUAL
                reason = f'first-person experiential claim "{experiential.group(0)}"'
            else:
                claim_type = ClaimType.FACTUAL
                reason = f'attribution marker "{marker}"'

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
