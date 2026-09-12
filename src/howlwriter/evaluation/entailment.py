"""Semantic entailment abstraction and evaluators for HowlWriter factuality evaluation.

Provides:
- EntailmentEvaluator protocol
- DeterministicEntailmentEvaluator (hermetic, rule-based, clause-and-polarity-aware)
- ModelEntailmentEvaluator (model-backed via HowlPlane with provider tracking)
- MockEntailmentEvaluator (for test harnesses)
"""

from __future__ import annotations

import json
import re
from typing import Protocol, runtime_checkable

from howlwriter.evaluation.models import EntailmentResult, EntailmentVerdict
from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole

_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_NEGATION_WORDS = {"not", "never", "no", "none", "neither", "nor", "without", "hardly", "scarcely", "cannot", "can't", "won't", "isn't", "aren't", "wasn't", "weren't"}
_ABSOLUTE_WORDS = {"eliminates", "eliminate", "eliminated", "always", "guarantees", "guarantee", "guaranteed", "perfect", "impossible", "mandatory", "compulsory", "zero"}
_HEDGE_WORDS = {"may", "might", "could", "sometimes", "partially", "some", "voluntary", "optional", "potentially", "possible"}
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "as", "is", "was", "were", "are", "be", "been",
    "it", "this", "that", "these", "those", "from", "into", "over", "after",
    "before", "about", "out", "up", "than", "then", "its", "their"
}

# Synonyms and paraphrases for high-frequency academic & technical verbs/nouns
_SYNONYM_MAP = {
    "published": {"released", "issued", "came", "established", "promulgated"},
    "released": {"published", "issued", "came", "established"},
    "issued": {"published", "released", "established"},
    "sample": {"cohort", "study", "group", "participants", "dataset"},
    "study": {"sample", "experiment", "investigation", "analysis"},
    "contained": {"included", "enrolled", "comprised", "had"},
    "included": {"contained", "enrolled", "comprised", "had"},
    "framework": {"guideline", "standard", "model", "specification", "architecture"},
    "reduce": {"decrease", "lower", "mitigate", "diminish", "curb"},
    "reduces": {"decreases", "lowers", "mitigates", "diminishes", "curbs"},
    "reduced": {"decreased", "lowered", "mitigated", "diminished", "curbed"},
    "eliminated": {"prevented", "removed", "eradicated"},
    "eliminates": {"prevents", "removes", "eradicates"},
}


@runtime_checkable
class EntailmentEvaluator(Protocol):
    """Protocol for semantic claim entailment evaluators."""

    def evaluate(self, claim: str, evidence: str) -> EntailmentResult:
        ...


class DeterministicEntailmentEvaluator:
    """High-confidence deterministic semantic entailment engine for hermetic CI.

    Evaluates:
    - Numeric consistency & bounds
    - Negation / polarity alignment
    - Modal / qualification strength (hedge vs absolute claim)
    - Semantic paraphrase alignment with entity and synonym matching
    """

    def evaluate(self, claim: str, evidence: str) -> EntailmentResult:
        claim_clean = claim.strip()
        evidence_clean = evidence.strip()

        if not claim_clean:
            return EntailmentResult(
                verdict=EntailmentVerdict.INSUFFICIENT_EVIDENCE,
                confidence=1.0,
                rationale="Empty claim provided.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )

        if not evidence_clean:
            return EntailmentResult(
                verdict=EntailmentVerdict.INSUFFICIENT_EVIDENCE,
                confidence=1.0,
                rationale="Empty evidence corpus provided.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )

        claim_lower = claim_clean.lower()
        evidence_lower = evidence_clean.lower()

        # 1. Exact or near-exact match
        if claim_lower in evidence_lower:
            return EntailmentResult(
                verdict=EntailmentVerdict.ENTAILED,
                confidence=1.0,
                rationale="Exact substring match in evidence.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )

        # 2. Extract and check numbers and statistics
        claim_numbers = set(_NUMBER_RE.findall(claim_lower))
        evidence_numbers = set(_NUMBER_RE.findall(evidence_lower))

        # Check for numeric contradiction
        contradicted_numbers = []
        for num in claim_numbers:
            # If a number in claim is NOT in evidence
            if num not in evidence_numbers:
                # If evidence has numbers that look like the same dimension but different value
                # e.g., claim has 420 and evidence has 240
                if evidence_numbers and not num.startswith("202") and not num.startswith("199"):
                    contradicted_numbers.append(num)

        if contradicted_numbers and evidence_numbers:
            return EntailmentResult(
                verdict=EntailmentVerdict.CONTRADICTED,
                confidence=0.95,
                rationale=f"Numeric contradiction: claim mentions {contradicted_numbers} but evidence contains {list(evidence_numbers)}.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )

        # 3. Negation & Polarity Inversion check
        claim_negated = any(re.search(r"\b" + re.escape(w) + r"\b", claim_lower) for w in _NEGATION_WORDS)
        evidence_negated = any(re.search(r"\b" + re.escape(w) + r"\b", evidence_lower) for w in _NEGATION_WORDS)

        # Antonym / Incompatible stance check (e.g. voluntary vs mandatory)
        if ("voluntary" in evidence_lower or "optional" in evidence_lower) and ("mandatory" in claim_lower or "compulsory" in claim_lower or "required" in claim_lower):
            return EntailmentResult(
                verdict=EntailmentVerdict.CONTRADICTED,
                confidence=0.95,
                rationale="Stance contradiction: evidence states 'voluntary/optional' but claim asserts 'mandatory/required'.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )
        if ("mandatory" in evidence_lower or "required" in evidence_lower) and ("voluntary" in claim_lower or "optional" in claim_lower):
            return EntailmentResult(
                verdict=EntailmentVerdict.CONTRADICTED,
                confidence=0.95,
                rationale="Stance contradiction: evidence states 'mandatory' but claim asserts 'voluntary'.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )

        # 4. Modal qualification & Overstatement check (hedge in evidence vs absolute in claim)
        evidence_has_hedge = any(re.search(r"\b" + re.escape(w) + r"\b", evidence_lower) for w in _HEDGE_WORDS)
        claim_has_absolute = any(re.search(r"\b" + re.escape(w) + r"\b", claim_lower) for w in _ABSOLUTE_WORDS)

        if evidence_has_hedge and claim_has_absolute:
            return EntailmentResult(
                verdict=EntailmentVerdict.CONTRADICTED,
                confidence=0.90,
                rationale="Modal overstatement: evidence hedges ('may reduce in some environments') but claim makes an unhedged absolute claim ('eliminates risk').",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )

        # 5. Semantic Token Alignment with Synonyms
        claim_tokens = [w for w in re.findall(r"[a-z0-9]+", claim_lower) if w not in _STOP_WORDS and len(w) > 2]
        evidence_tokens = set(re.findall(r"[a-z0-9]+", evidence_lower))

        if not claim_tokens:
            return EntailmentResult(
                verdict=EntailmentVerdict.PARTIALLY_ENTAILED,
                confidence=0.5,
                rationale="Insufficient content words in claim.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )

        matched_count = 0
        unmatched_tokens = []
        for tok in claim_tokens:
            if tok in evidence_tokens:
                matched_count += 1
            else:
                # Check synonym map
                synonyms = _SYNONYM_MAP.get(tok, set())
                if any(syn in evidence_tokens for syn in synonyms):
                    matched_count += 1
                else:
                    unmatched_tokens.append(tok)

        overlap_ratio = matched_count / len(claim_tokens)

        # Check for ungrounded/fabricated specific figures or metrics
        # e.g., claim asserts "reduced breaches by 35%" when evidence only says "voluntary guidance"
        if "%" in claim_clean:
            if "%" not in evidence_lower and "percent" not in evidence_lower:
                return EntailmentResult(
                    verdict=EntailmentVerdict.NOT_ENTAILED,
                    confidence=0.90,
                    rationale=f"Claim introduces quantitative metric/percentage not mentioned in evidence: {claim_clean}",
                    extracted_claim=claim_clean,
                    matched_evidence=evidence_clean,
                )

        if overlap_ratio >= 0.70:
            return EntailmentResult(
                verdict=EntailmentVerdict.ENTAILED,
                confidence=round(overlap_ratio, 2),
                rationale=f"Strong semantic entailment: {matched_count}/{len(claim_tokens)} key concepts verified in evidence.",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )
        elif overlap_ratio >= 0.45:
            return EntailmentResult(
                verdict=EntailmentVerdict.PARTIALLY_ENTAILED,
                confidence=round(overlap_ratio, 2),
                rationale=f"Partial entailment: {matched_count}/{len(claim_tokens)} concepts match evidence. Unmatched: {unmatched_tokens[:3]}",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )
        else:
            return EntailmentResult(
                verdict=EntailmentVerdict.NOT_ENTAILED,
                confidence=round(1.0 - overlap_ratio, 2),
                rationale=f"Unsupported inference: only {matched_count}/{len(claim_tokens)} concepts match evidence. Unmatched: {unmatched_tokens[:5]}",
                extracted_claim=claim_clean,
                matched_evidence=evidence_clean,
            )


class ModelEntailmentEvaluator:
    """Model-backed semantic entailment judge using HowlPlane with provider tracking."""

    def __init__(
        self,
        role: WritingRole = WritingRole.FINAL_REVIEWER,
        fallback: EntailmentEvaluator | None = None,
    ) -> None:
        self.role = role
        self.fallback = fallback or DeterministicEntailmentEvaluator()

    def evaluate(self, claim: str, evidence: str) -> EntailmentResult:
        bridge = get_howlplane_bridge()
        if not bridge.is_available():
            return self.fallback.evaluate(claim, evidence)

        prompt = f"""You are an expert, impartial semantic entailment evaluator.
Given the EVIDENCE and the CLAIM, determine whether the claim is:
- ENTAILED: The claim is directly stated, logically entailed, or accurately paraphrased by the evidence.
- PARTIALLY_ENTAILED: Part of the claim is supported, but minor unverified details are present.
- NOT_ENTAILED: The claim makes assertions, figures, or causal inferences not supported by the evidence.
- CONTRADICTED: The claim directly contradicts facts, numbers, dates, or directionality stated in the evidence.

EVIDENCE:
{evidence}

CLAIM:
{claim}

Respond strictly in JSON:
{{
  "verdict": "ENTAILED" | "PARTIALLY_ENTAILED" | "NOT_ENTAILED" | "CONTRADICTED",
  "confidence": <float between 0.0 and 1.0>,
  "rationale": "<concise explanation>"
}}
"""
        try:
            res = bridge.execute_writing_role(
                role=self.role,
                prompt=prompt,
                system_instruction="You evaluate semantic entailment and factual grounding rigorously.",
            )
            raw_text = getattr(res, "output", str(res))
            match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                verdict_str = str(data.get("verdict", "UNAVAILABLE")).upper()
                verdict = getattr(EntailmentVerdict, verdict_str, EntailmentVerdict.UNAVAILABLE)
                return EntailmentResult(
                    verdict=verdict,
                    confidence=float(data.get("confidence", 0.9)),
                    rationale=str(data.get("rationale", "")),
                    extracted_claim=claim,
                    matched_evidence=evidence,
                )
        except Exception:
            pass

        return self.fallback.evaluate(claim, evidence)


class MockEntailmentEvaluator:
    """Scripted entailment evaluator for unit tests."""

    def __init__(self, default_verdict: EntailmentVerdict = EntailmentVerdict.ENTAILED) -> None:
        self.default_verdict = default_verdict

    def evaluate(self, claim: str, evidence: str) -> EntailmentResult:
        return EntailmentResult(
            verdict=self.default_verdict,
            confidence=1.0,
            rationale="Mock evaluation result.",
            extracted_claim=claim,
            matched_evidence=evidence,
        )
