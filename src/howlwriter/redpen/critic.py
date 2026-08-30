"""Red Pen: criticism, not rewriting.

Deterministic heuristics for the MVP: generic filler/canned-conclusion
sentences (reusing linting's phrase lists so there's one source of truth,
not two drifting ones), sentence-length outliers within their paragraph,
and -- when a caller supplies extracted claims -- unhedged claims that are
still UNSUPPORTED/UNVERIFIABLE. Red Pen almost always recommends deletion
or a human decision, never an automatic rewrite.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal

from howlwriter.domain.claim import Claim, VerificationStatus
from howlwriter.domain.document import Document
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.linting.builtin_rules.banned_patterns import (
    CANNED_CONCLUSION_PHRASES,
    EMPTY_TRANSITION_PHRASES,
)

Recommendation = Literal["delete", "revise", "flag"]

_FILLER_PHRASES = EMPTY_TRANSITION_PHRASES + CANNED_CONCLUSION_PHRASES
_LENGTH_OUTLIER_MULTIPLIER = 2.5
_MIN_PARAGRAPH_SENTENCES_FOR_OUTLIER_CHECK = 3
_HEDGE_WORDS = ("may", "might", "could", "suggests", "appears", "likely", "reportedly", "according to")


@dataclass
class RedPenFinding(DataClassSerializationMixin):
    id: str
    paragraph_index: int
    sentence_index: int
    quoted_text: str
    reason: str
    recommendation: Recommendation


class RedPenEngine:
    def critique(self, document: Document, claims: list[Claim] | None = None) -> list[RedPenFinding]:
        findings: list[RedPenFinding] = []
        findings.extend(self._filler_findings(document))
        findings.extend(self._length_outlier_findings(document))
        findings.extend(self._unsupported_claim_findings(document, claims or []))

        for index, finding in enumerate(findings, start=1):
            finding.id = f"RED_PEN_{index:03d}"
        return findings

    @staticmethod
    def _filler_findings(document: Document) -> list[RedPenFinding]:
        findings = []
        for p_index, s_index, sentence in document.all_sentences():
            lowered = sentence.text.lower()
            for phrase in _FILLER_PHRASES:
                if phrase in lowered:
                    findings.append(
                        RedPenFinding(
                            id="",
                            paragraph_index=p_index,
                            sentence_index=s_index,
                            quoted_text=sentence.text,
                            reason=f'Generic filler phrase ("{phrase}") that adds no information.',
                            recommendation="delete",
                        )
                    )
                    break
        return findings

    @staticmethod
    def _length_outlier_findings(document: Document) -> list[RedPenFinding]:
        findings = []
        for paragraph in document.paragraphs:
            if len(paragraph.sentences) < _MIN_PARAGRAPH_SENTENCES_FOR_OUTLIER_CHECK:
                continue
            lengths = [len(s.text.split()) for s in paragraph.sentences]
            mean_length = statistics.mean(lengths)
            for sentence, length in zip(paragraph.sentences, lengths):
                if mean_length > 0 and length > mean_length * _LENGTH_OUTLIER_MULTIPLIER:
                    findings.append(
                        RedPenFinding(
                            id="",
                            paragraph_index=paragraph.index,
                            sentence_index=sentence.index,
                            quoted_text=sentence.text,
                            reason="Runs much longer than its neighboring sentences in this paragraph.",
                            recommendation="revise",
                        )
                    )
        return findings

    @staticmethod
    def _unsupported_claim_findings(document: Document, claims: list[Claim]) -> list[RedPenFinding]:
        unresolved = {VerificationStatus.UNSUPPORTED, VerificationStatus.UNVERIFIABLE}
        findings = []
        for claim in claims:
            if claim.verification_status not in unresolved:
                continue
            if claim.document_span is None:
                continue
            if any(hedge in claim.text.lower() for hedge in _HEDGE_WORDS):
                continue
            findings.append(
                RedPenFinding(
                    id="",
                    paragraph_index=claim.document_span.paragraph_index,
                    sentence_index=claim.document_span.sentence_index,
                    quoted_text=claim.text,
                    reason="Unverified claim stated without a hedge or a source.",
                    recommendation="flag",
                )
            )
        return findings
