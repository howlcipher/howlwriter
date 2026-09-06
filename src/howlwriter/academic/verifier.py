"""Academic claim verification, quotation integrity, and provenance graph creation."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from howlwriter.academic.attack import validate_attack_mapping
from howlwriter.academic.freshness import (
    FreshnessFinding,
    FreshnessSeverity,
    evaluate_source_freshness_for_claim,
)
from howlwriter.academic.identifiers import find_ungrounded_identifiers
from howlwriter.academic.telemetry import find_telemetry_mismatches_in_text
from howlwriter.domain.claim import Claim, ClaimTemporalContext, ClaimType, VerificationStatus
from howlwriter.domain.document import Document
from howlwriter.domain.provenance import ProvenanceGraph
from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import (
    DEPTH_ABSTRACT,
    DEPTH_FULL_TEXT,
    DEPTH_METADATA_ONLY,
    DEPTH_PARTIAL_TEXT,
    DEPTH_UNAVAILABLE,
    RELEVANCE_DIRECT,
    RELEVANCE_SUPPORTING,
    Evidence,
    Source,
)
from howlwriter.facts.extraction import HeuristicClaimExtractor

_PAGE_NUMBER_RE = re.compile(r"\b(?:p\.|pp\.|page|pages)\s*\d+\b", re.IGNORECASE)


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
    freshness_findings: list[FreshnessFinding] = field(default_factory=list)
    freshness_warnings: list[str] = field(default_factory=list)
    status: str = "PASS"  # "PASS" | "NEEDS_REVIEW" | "BLOCKED" | "REJECTED"

    @classmethod
    def from_dict(cls, data: dict) -> VerificationSummary:
        data = dict(data)
        if "freshness_findings" in data and isinstance(data["freshness_findings"], list):
            data["freshness_findings"] = [
                FreshnessFinding.from_dict(f) if isinstance(f, dict) else f
                for f in data["freshness_findings"]
            ]
        return super().from_dict(data)


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


_PERCENTAGE = re.compile(
    r"(\d*\.?\d+)\s*(?:%|percent\b|percentage points?\b)", re.IGNORECASE
)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_ANY_NUMBER = re.compile(r"\d*\.?\d+")


def _percentages(text: str) -> list[float]:
    """Every value in the text written as a percentage."""
    cleaned = _THOUSANDS.sub("", text)
    values = []
    for match in _PERCENTAGE.finditer(cleaned):
        try:
            values.append(float(match.group(1)))
        except ValueError:
            continue
    return values


def _rounds_to(candidate: float, claimed: str) -> bool:
    """Does the candidate round to the claimed figure at its own precision?

    Papers round: a source reporting 41.2% supports a claim of 41%. Comparing
    the strings rejected that, so the tolerance is taken from how precisely the
    claim was stated.
    """
    decimals = len(claimed.split(".")[1]) if "." in claimed else 0
    return abs(candidate - float(claimed)) <= 0.5 * (10 ** -decimals)


def _claim_asserts_ungrounded_quantity(claim: Claim, source_text: str) -> bool:
    """True if the claim states a percentage the source does not report.

    Claims are matched to sources by shared vocabulary, so a sentence about the
    right subject matter matches a source whether or not the source contains
    the figure it reports. A fabricated statistic therefore inherited the
    source's authority: "mTLS cut insider breaches 41 percent (Author, 2026)"
    was marked SUPPORTED against an abstract holding no such number. A figure
    is the whole substance of a statistical claim, so if the evidence does not
    report it, the claim is not supported by it.

    The claimed figure is matched against percentages in the source, or against
    its decimal equivalent (a source reporting 0.05 supports a claim of 5%).
    Matching bare numbers instead let a reference marker like "[41]" or a
    "Section 4.1" heading stand in for a statistic that was never measured.

    Scope: percentages only. Fabricated counts, currencies, durations and
    multipliers are not covered here -- checking every number would reject
    claims for years, page counts and sample sizes -- so this narrows the gap
    rather than closing it.
    """
    cleaned_claim = _THOUSANDS.sub("", claim.text)
    claimed = [m.group(1) for m in _PERCENTAGE.finditer(cleaned_claim)]
    if not claimed:
        return False

    source_percentages = _percentages(source_text)
    # A source stating a rate as a decimal ("0.05") reports the same fact as a
    # claim stating it as a percentage ("5%").
    cleaned_source = _THOUSANDS.sub("", source_text)
    decimal_equivalents = []
    for token in _ANY_NUMBER.findall(cleaned_source):
        try:
            value = float(token)
        except ValueError:
            continue
        if 0 < value < 1:
            decimal_equivalents.append(value * 100)

    candidates = source_percentages + decimal_equivalents
    return any(
        not any(_rounds_to(candidate, value) for candidate in candidates)
        for value in claimed
    )


_INCREASE_MARKERS = (
    "increase", "increased", "increases", "rose", "rise", "risen", "grew",
    "grow", "growth", "gain", "gained", "higher", "boost", "boosted",
    "up", "more", "greater", "accelerated", "surge", "surged",
)
_DECREASE_MARKERS = (
    "decrease", "decreased", "decreases", "reduce", "reduced", "reduction",
    "drop", "dropped", "fell", "fall", "decline", "declined", "lower",
    "cut", "fewer", "less", "slowed", "shrank", "down",
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PARENTHETICAL = re.compile(r"\([^()]*\)")


def _direction_of(text: str) -> str | None:
    """Which way a passage says a quantity moved, if it says at all.

    Returns "up", "down", or None when the passage carries neither or both.
    Ambiguous words are left out on purpose: "improved latency" means down
    while "improved throughput" means up, so treating either as directional
    would invent a disagreement.

    Parentheticals are dropped first. Direction belongs to the prose, and an
    author named Rose in "(Rose, 2024)" otherwise reads as the verb "rose".
    """
    lowered = _PARENTHETICAL.sub(" ", text).lower()
    up = any(_has_marker(lowered, m) for m in _INCREASE_MARKERS)
    down = any(_has_marker(lowered, m) for m in _DECREASE_MARKERS)
    if up == down:
        return None
    return "up" if up else "down"


def _claim_reverses_source_direction(claim: Claim, source_text: str) -> bool:
    """True if the claim moves a figure the opposite way from its source.

    The figure and the subject matter can both match while the claim says the
    opposite of what was found: a source reporting that enforcement increased
    deployment velocity 15% supported a claim that it decreased it 15%. The
    citation resolves, the number checks out, and the sentence asserts the
    reverse of the evidence.

    Direction is compared only within the source sentence that reports the
    same figure, so an unrelated trend elsewhere in an abstract cannot
    manufacture a disagreement.
    """
    claimed = _percentages(claim.text)
    if not claimed:
        return False
    claim_direction = _direction_of(claim.text)
    if claim_direction is None:
        return False

    for sentence in _SENTENCE_SPLIT.split(source_text):
        sentence_values = _percentages(sentence)
        if not sentence_values:
            continue
        if not any(
            _rounds_to(candidate, f"{value:g}")
            for value in claimed
            for candidate in sentence_values
        ):
            continue
        source_direction = _direction_of(sentence)
        if source_direction is not None and source_direction != claim_direction:
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
        spec: Any | None = None,
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
                    t_ctx = sc.get("temporal_context")
                    if t_ctx and isinstance(t_ctx, str):
                        try:
                            t_ctx = ClaimTemporalContext(t_ctx)
                        except ValueError:
                            t_ctx = ClaimTemporalContext.UNKNOWN
                    elif isinstance(t_ctx, ClaimTemporalContext):
                        pass
                    else:
                        t_ctx = ClaimTemporalContext.UNKNOWN
                    claim_map[cid] = Claim(
                        id=cid,
                        text=text,
                        claim_type=ClaimType.FACTUAL,
                        verification_status=VerificationStatus.UNVERIFIABLE,
                        temporal_context=t_ctx,
                        target_version=sc.get("target_version"),
                        target_family=sc.get("target_family"),
                        intentional_historical_use=bool(sc.get("intentional_historical_use")),
                        historical_use_reason=sc.get("historical_use_reason"),
                    )

        # 3. Check direct quotations
        quotation_warnings: list[str] = []
        quotes = re.findall(r'"([^"\n]{10,250})"', document.body_text)
        for quote_text in quotes:
            # Check if this quote exists verbatim in any source's retrieved text with sufficient depth
            found_in_source = any(
                quote_text.lower() in (s.retrieved_text or "").lower()
                for s in sources
                if s.evidence_depth in (DEPTH_FULL_TEXT, DEPTH_PARTIAL_TEXT, "OTHER")
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
        identifier_findings = find_ungrounded_identifiers(document.body_text, grounding_texts)
        identifier_warnings = [
            f'Ungrounded {f.kind} "{f.identifier}" (context: "{f.context_snippet}") was not found '
            "in any retrieved source or assignment text."
            for f in identifier_findings
        ]

        # Check telemetry source/event misattributions
        telemetry_mismatches = find_telemetry_mismatches_in_text(document.body_text)
        identifier_warnings.extend(telemetry_mismatches)

        # Check deep semantic grounding for any ATT&CK techniques in body
        attack_ids = list(re.findall(r"\bT\d{4}(?:\.\d{3})?\b", document.body_text))
        for t_id in set(attack_ids):
            snippet = ""
            for p in document.body_paragraphs():
                if t_id.lower() in p.raw_text.lower():
                    snippet = p.raw_text
                    break
            val = validate_attack_mapping(
                t_id,
                snippet,
                sources=sources,
                additional_grounding_texts=grounding_texts,
                all_mapped_techniques=attack_ids,
            )
            if not val.is_verified:
                identifier_warnings.append(
                    f'ATT&CK Semantic Grounding failure for "{t_id}": {val.notes}'
                )

        evidence_counter = 1
        supported_count = 0
        partially_supported_count = 0
        unsupported_count = 0
        contradicted_count = 0
        opinion_count = 0
        quote_count = len(quotes)
        freshness_findings: list[FreshnessFinding] = []
        freshness_warnings: list[str] = []

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
                has_page_spec = bool(_PAGE_NUMBER_RE.search(claim.text))
                depth_inadequate_for_page = (
                    has_page_spec
                    and matched_source.evidence_depth in (DEPTH_ABSTRACT, DEPTH_METADATA_ONLY, DEPTH_UNAVAILABLE)
                )
                if (
                    _source_can_support(matched_source)
                    and not depth_inadequate_for_page
                    and not _claim_escalates_evidence(
                        claim, matched_source.retrieved_text
                    )
                    and not _claim_asserts_ungrounded_quantity(
                        claim, matched_source.retrieved_text
                    )
                    and not _claim_reverses_source_direction(
                        claim, matched_source.retrieved_text
                    )
                ):
                    freshness_sev, f_finding = evaluate_source_freshness_for_claim(
                        claim, matched_source, spec=spec
                    )
                    if f_finding:
                        freshness_findings.append(f_finding)
                        freshness_warnings.append(f_finding.render_diagnostic())

                    if freshness_sev == FreshnessSeverity.BLOCKED:
                        ev_id = f"E{evidence_counter:03d}"
                        evidence_counter += 1
                        ev = Evidence(
                            id=ev_id,
                            source_id=matched_source.id,
                            claim_id=claim.id,
                            snippet=matched_snippet or matched_source.retrieved_text[:150],
                            supports=False,
                            notes=(
                                f"Version mismatch with {matched_source.title}: "
                                f"{f_finding.reason if f_finding else 'Source version does not match claim requirement'}."
                            ),
                        )
                        graph.add_evidence(ev)
                        claim.verification_status = VerificationStatus.UNSUPPORTED
                        unsupported_count += 1
                    else:
                        ev_id = f"E{evidence_counter:03d}"
                        evidence_counter += 1
                        note = f"Corroborated by {matched_source.title}"
                        if f_finding:
                            status_str = (
                                f_finding.freshness_status.value
                                if hasattr(f_finding.freshness_status, "value")
                                else str(f_finding.freshness_status)
                            )
                            note += f" [Freshness: {status_str}]"
                        ev = Evidence(
                            id=ev_id,
                            source_id=matched_source.id,
                            claim_id=claim.id,
                            snippet=matched_snippet or matched_source.retrieved_text[:150],
                            supports=True,
                            notes=note,
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
                    # Naming the specific reason matters: "the source does not
                    # report this figure" and "the source is metadata-only" ask
                    # the writer to do completely different things.
                    if _claim_reverses_source_direction(
                        claim, matched_source.retrieved_text
                    ):
                        reason = (
                            "the source reports this figure moving the "
                            "opposite way"
                        )
                    elif _claim_asserts_ungrounded_quantity(
                        claim, matched_source.retrieved_text
                    ):
                        reason = (
                            "the source does not report the figure this claim "
                            "states"
                        )
                    elif not _source_can_support(matched_source):
                        reason = (
                            "the source is metadata-only, tangential or "
                            "irrelevant"
                        )
                    elif depth_inadequate_for_page:
                        reason = (
                            "the claim cites a page but the source was only "
                            "retrieved at abstract depth"
                        )
                    else:
                        reason = "the claim is stronger than the source supports"
                    ev = Evidence(
                        id=ev_id,
                        source_id=matched_source.id,
                        claim_id=claim.id,
                        snippet=matched_snippet or matched_source.retrieved_text[:150],
                        supports=False,
                        notes=(
                            f"Matched {matched_source.title} but {reason}."
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
            or any(
                f.severity in (FreshnessSeverity.NEEDS_REVIEW, FreshnessSeverity.WARNING)
                for f in freshness_findings
            )
        ):
            overall_status = "NEEDS_REVIEW"
        if any(f.severity == FreshnessSeverity.BLOCKED for f in freshness_findings):
            overall_status = "BLOCKED"

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
            freshness_findings=freshness_findings,
            freshness_warnings=freshness_warnings,
            status=overall_status,
        )

        return graph, summary

    verify = build_provenance_and_verify
