"""Academic claim verification, quotation integrity, and provenance graph creation."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from howlwriter.academic.identifiers import find_ungrounded_identifiers
from howlwriter.domain.claim import Claim, ClaimType, VerificationStatus
from howlwriter.domain.document import Document
from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import (
    RELEVANCE_DIRECT,
    RELEVANCE_SUPPORTING,
    Evidence,
    Source,
)
from howlwriter.facts.extraction import HeuristicClaimExtractor


@dataclass
class VerificationSummary(DataClassSerializationMixin):
    total_claims: int = 0
    supported_claims: int = 0
    partially_supported_claims: int = 0
    unsupported_claims: int = 0
    contradicted_claims: int = 0
    opinion_or_inference_claims: int = 0
    quotation_claims: int = 0
    quotation_warnings: list[str] = field(default_factory=list)
    identifier_warnings: list[str] = field(default_factory=list)
    status: str = "PASS"  # "PASS" | "NEEDS_REVIEW" | "REJECTED"


# Markers that tend to escalate a claim beyond the evidence in a source.
# These are conservative, deterministic heuristics for common overreaches.
_CERTAINTY_ESC_MARKERS = frozenset({
    "will", "must", "always", "never", "all", "every", "entirely",
    "universally", "proves", "proven", "definitely", "certainly",
})
_CAUSAL_ESC_MARKERS = (
    "causes", "caused", "causing", "causation", "leads to",
    "resulted in", "produces", "produced",
)
_CORRELATIONAL_MARKERS = (
    "associated with", "correlated with", "correlation", "linked to",
    "related to", "connected to",
)
_SCOPE_ESC_MARKERS = frozenset({
    "all", "every", "always", "never", "none", "entire", "universal",
    "across all", "in every",
})


def _source_has_causal_language(source_text: str) -> bool:
    lowered = source_text.lower()
    return any(_has_marker(lowered, m) for m in _CAUSAL_ESC_MARKERS)


def _has_marker(text: str, marker: str) -> bool:
    """Word- or phrase-boundary match for an escalation marker."""
    return bool(re.search(rf"\b{re.escape(marker)}\b", text))


def _claim_escalates_evidence(claim: Claim, source_text: str) -> bool:
    """True if the claim uses stronger language than the retrieved source."""
    claim_lower = claim.text.lower()
    source_lower = source_text.lower()

    # Certainty escalation
    for marker in _CERTAINTY_ESC_MARKERS:
        if _has_marker(claim_lower, marker) and not _has_marker(source_lower, marker):
            return True

    # Scope expansion
    for marker in _SCOPE_ESC_MARKERS:
        if _has_marker(claim_lower, marker) and not _has_marker(source_lower, marker):
            return True

    # Correlation -> causation
    if any(_has_marker(claim_lower, m) for m in _CAUSAL_ESC_MARKERS):
        if not _source_has_causal_language(source_text):
            # If the source only uses correlational language, the claim may not
            # infer causation.
            if any(_has_marker(source_lower, m) for m in _CORRELATIONAL_MARKERS):
                return True

    return False


def _source_can_support(source: Source) -> bool:
    """A source may support a substantive factual claim only if it is relevant
    and has some real retrieved text (not metadata only)."""
    if not source.is_substantive_evidence:
        return False
    if source.relevance not in (RELEVANCE_DIRECT, RELEVANCE_SUPPORTING):
        return False
    return True


class AcademicVerifier:
    """Verifies claims against retrieved sources and generates a connected ProvenanceGraph."""

    def __init__(self, extractor: HeuristicClaimExtractor | None = None) -> None:
        self.extractor = extractor or HeuristicClaimExtractor()

    def build_provenance_and_verify(
        self,
        document: Document,
        sources: list[Source],
        stated_claims: list[dict] | None = None,
        additional_grounding_texts: list[str] | None = None,
    ) -> tuple[ProvenanceGraph, VerificationSummary]:
        """Extracts claims from paper, cross-references with sources, and verifies evidence.

        additional_grounding_texts widens the identifier-grounding corpus
        beyond the sources' retrieved_text (e.g. the assignment's own
        topic/requirements text), so an identifier the assignment itself
        legitimately names is never flagged as ungrounded.
        """
        graph = ProvenanceGraph()
        for s in sources:
            graph.add_source(s)

        # 1. Extract claims heuristically
        extracted = self.extractor.extract(document)
        claim_map: dict[str, Claim] = {}

        for c in extracted:
            claim_map[c.id] = c

        # 2. Add writer-stated claims if provided
        if stated_claims:
            for idx, sc in enumerate(stated_claims, start=len(claim_map) + 1):
                cid = f"C{idx:03d}"
                text = str(sc.get("claim") or "")
                if text and cid not in claim_map:
                    claim_map[cid] = Claim(
                        id=cid,
                        text=text,
                        claim_type=ClaimType.FACTUAL,
                        verification_status=VerificationStatus.UNVERIFIABLE,
                    )

        # 3. Check direct quotations
        quotation_warnings: list[str] = []
        quotes = re.findall(r'"([^"\n]{10,250})"', document.text)
        for quote_text in quotes:
            # Check if this quote exists verbatim in any source's retrieved text
            found_in_source = any(
                quote_text.lower() in (s.retrieved_text or "").lower()
                for s in sources
            )
            if not found_in_source:
                quotation_warnings.append(
                    f'Direct quotation "{quote_text[:60]}..." was not found verbatim in any retrieved source.'
                )

        # 3b. Check unsupported-specificity: precise technical identifiers /
        # figures that are not grounded in any source or additional
        # grounding text (e.g. the assignment's own topic/requirements).
        grounding_texts = [s.retrieved_text or "" for s in sources]
        grounding_texts.extend(additional_grounding_texts or [])
        identifier_findings = find_ungrounded_identifiers(document.text, grounding_texts)
        identifier_warnings = [
            f'Ungrounded {f.kind} "{f.identifier}" (context: "{f.context_snippet}") was not found '
            "in any retrieved source or assignment text."
            for f in identifier_findings
        ]

        evidence_counter = 1
        supported_count = 0
        partially_supported_count = 0
        unsupported_count = 0
        contradicted_count = 0
        opinion_count = 0
        quote_count = len(quotes)

        # 4. Verify each claim against source text
        for claim_id, claim in claim_map.items():
            graph.add_claim(claim)
            claim_lower = claim.text.lower()

            # Check if claim is opinion or framing
            if claim.claim_type == ClaimType.OPINION:
                claim.verification_status = VerificationStatus.OPINION
                opinion_count += 1
                continue

            # Look for matching source
            matched_source: Source | None = None
            matched_snippet: str | None = None

            # First check if explicit source ID is attached
            for s in sources:
                if s.id.lower() in claim_lower:
                    matched_source = s
                    break

            # Search source retrieved_text for keyword overlap
            if not matched_source:
                claim_words = set(re.findall(r"\b\w{4,}\b", claim_lower))
                best_overlap = 0
                for s in sources:
                    s_text = (s.retrieved_text or "").lower()
                    if not s_text:
                        continue
                    s_words = set(re.findall(r"\b\w{4,}\b", s_text))
                    overlap = len(claim_words & s_words)
                    if overlap > best_overlap and overlap >= 3:
                        best_overlap = overlap
                        matched_source = s
                        matched_snippet = s.retrieved_text[:200] if s.retrieved_text else ""

            if matched_source and matched_source.retrieved_text:
                if _source_can_support(matched_source) and not _claim_escalates_evidence(
                    claim, matched_source.retrieved_text
                ):
                    ev_id = f"E{evidence_counter:03d}"
                    evidence_counter += 1
                    ev = Evidence(
                        id=ev_id,
                        source_id=matched_source.id,
                        claim_id=claim.id,
                        snippet=matched_snippet or matched_source.retrieved_text[:150],
                        supports=True,
                        notes=f"Corroborated by {matched_source.title}",
                    )
                    graph.add_evidence(ev)
                    claim.supporting_sources.append(matched_source.id)
                    claim.verification_status = VerificationStatus.SUPPORTED
                    supported_count += 1
                else:
                    # A match was found, but the source is either metadata-only,
                    # tangential/irrelevant, or the claim escalates beyond the
                    # evidence. Attach a non-supporting evidence note so the
                    # provenance graph is truthful.
                    ev_id = f"E{evidence_counter:03d}"
                    evidence_counter += 1
                    ev = Evidence(
                        id=ev_id,
                        source_id=matched_source.id,
                        claim_id=claim.id,
                        snippet=matched_snippet or matched_source.retrieved_text[:150],
                        supports=False,
                        notes=(
                            f"Matched {matched_source.title} but evidence is "
                            "insufficient (metadata-only, tangential, or "
                            "escalated beyond the source)."
                        ),
                    )
                    graph.add_evidence(ev)
                    claim.verification_status = VerificationStatus.UNSUPPORTED
                    unsupported_count += 1
            else:
                # Factual claim without evidence is UNSUPPORTED
                if claim.claim_type in (ClaimType.STATISTICAL, ClaimType.FACTUAL):
                    claim.verification_status = VerificationStatus.UNSUPPORTED
                    unsupported_count += 1
                else:
                    claim.verification_status = VerificationStatus.INFERENCE
                    opinion_count += 1

        overall_status = "PASS"
        if (
            unsupported_count > 0
            or contradicted_count > 0
            or quotation_warnings
            or identifier_warnings
        ):
            overall_status = "NEEDS_REVIEW"

        summary = VerificationSummary(
            total_claims=len(claim_map),
            supported_claims=supported_count,
            partially_supported_claims=partially_supported_count,
            unsupported_claims=unsupported_count,
            contradicted_claims=contradicted_count,
            opinion_or_inference_claims=opinion_count,
            quotation_claims=quote_count,
            quotation_warnings=quotation_warnings,
            identifier_warnings=identifier_warnings,
            status=overall_status,
        )

        return graph, summary
