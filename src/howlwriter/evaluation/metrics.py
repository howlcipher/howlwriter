"""Independent evaluation metric families for empirical benchmarking.

Measures:
1. Requirement Satisfaction (deterministic)
2. Factuality & Grounding (claims, dates, numbers, citations)
3. Citation Integrity (ACCESS, METADATA, AUTHORITY, EVIDENCE, FRESHNESS)
4. Source Quality (semantic authority tiering)
5. Meaning Preservation (numbers, polarity, hedges, causal drift)
6. Voice Fidelity (multidimensional distributions -- NO fake single percentage)
7. Structural Diversity (coefficient of variation, convergence detection)
8. Writing Quality Signals (AI-slop, redundancy, linting, red pen)
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Sequence

from howlwriter.academic.redundancy import detect_redundancy
from howlwriter.domain.document import Document
from howlwriter.domain.source import Source, SourceAuthority
from howlwriter.evaluation.entailment import (
    DeterministicEntailmentEvaluator,
    EntailmentEvaluator,
    EntailmentVerdict,
)
from howlwriter.evaluation.models import BenchmarkCase, CandidateOutput, MetricScore
from howlwriter.facts.extraction import HeuristicClaimExtractor
from howlwriter.linting.engine import LintEngine
from howlwriter.linting.rules import AI_STYLE_BANNED_WORD
from howlwriter.redpen.critic import RedPenEngine
from howlwriter.research.authority import classify_source_authority
from howlwriter.review.meaning import MeaningPreservationReviewer
from howlwriter.voice.corpus.diversity import (
    FAIL,
    NOT_EVALUATED,
    PASS,
    WARNING,
    _coefficient_of_variation,
)
from howlwriter.voice.corpus.features import (
    DocumentFeatures,
    extract_features,
)

_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+(.*)$", re.MULTILINE)
_CITATION_PAREN_RE = re.compile(r"\(([A-Z][A-Za-z\s&–-]+?(?: et al\.)?(?:,\s*[12]\d{3})?)\)")
_CITATION_INLINE_RE = re.compile(r"\b([A-Z][A-Za-z\s&–-]+?(?: et al\.)?)\s+\(([12]\d{3})\)")
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_URL_RE = re.compile(r"https?://[^\s)\]>]+")
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")


# --- 1. Requirement Satisfaction Evaluator ----------------------------------

class RequirementSatisfactionEvaluator:
    """Evaluates whether the candidate satisfied all explicit task requirements."""

    metric_name = "requirement_satisfaction"

    def evaluate(self, case: BenchmarkCase, candidate: CandidateOutput) -> MetricScore:
        text = candidate.text or ""
        reqs = case.requirements or {}
        details: dict[str, Any] = {}
        checks_passed = 0
        total_checks = 0

        # Word count compliance
        words = len(text.split())
        min_words = reqs.get("min_words")
        max_words = reqs.get("max_words")
        target_words = reqs.get("target_words")
        if min_words is not None or max_words is not None or target_words is not None:
            total_checks += 1
            if min_words is not None and words < min_words:
                length_ok = False
            elif max_words is not None and words > max_words:
                length_ok = False
            elif target_words is not None and abs(words - target_words) > (target_words * 0.25):
                length_ok = False
            else:
                length_ok = True
            details["length_compliance"] = {
                "words": words,
                "min": min_words,
                "max": max_words,
                "target": target_words,
                "passed": length_ok,
            }
            if length_ok:
                checks_passed += 1

        # Required sections present
        req_sections = reqs.get("required_sections", [])
        if req_sections:
            total_checks += 1
            headings = [h.strip().lower() for h in _HEADING_RE.findall(text)]
            found_sections = []
            missing_sections = []
            for sec in req_sections:
                sec_lower = sec.lower().strip()
                if any(sec_lower in h or h in sec_lower for h in headings) or sec_lower in text.lower():
                    found_sections.append(sec)
                else:
                    missing_sections.append(sec)
            section_ratio = len(found_sections) / len(req_sections) if req_sections else 1.0
            details["required_sections"] = {
                "required": req_sections,
                "found": found_sections,
                "missing": missing_sections,
                "ratio": section_ratio,
                "passed": len(missing_sections) == 0,
            }
            if len(missing_sections) == 0:
                checks_passed += 1
            else:
                checks_passed += section_ratio

        # Required points covered
        req_points = reqs.get("required_points", [])
        if req_points:
            total_checks += 1
            covered_points = []
            missing_points = []
            lower_text = text.lower()
            for pt in req_points:
                pt_words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", pt) if len(w) > 3]
                if not pt_words:
                    pt_words = [w.lower() for w in pt.split()]
                # If majority of key terms are present
                hits = sum(1 for w in pt_words if w in lower_text)
                if hits >= max(1, int(len(pt_words) * 0.6)):
                    covered_points.append(pt)
                else:
                    missing_points.append(pt)
            point_ratio = len(covered_points) / len(req_points) if req_points else 1.0
            details["required_points"] = {
                "required": req_points,
                "covered": covered_points,
                "missing": missing_points,
                "ratio": point_ratio,
                "passed": len(missing_points) == 0,
            }
            if len(missing_points) == 0:
                checks_passed += 1
            else:
                checks_passed += point_ratio

        # Verbatim phrases
        verbatim_phrases = reqs.get("verbatim_phrases", [])
        if verbatim_phrases:
            total_checks += 1
            preserved = [p for p in verbatim_phrases if p in text]
            lost = [p for p in verbatim_phrases if p not in text]
            retention_ratio = len(preserved) / len(verbatim_phrases) if verbatim_phrases else 1.0
            details["verbatim_retention"] = {
                "required": verbatim_phrases,
                "preserved": preserved,
                "lost": lost,
                "ratio": retention_ratio,
                "passed": len(lost) == 0,
            }
            if len(lost) == 0:
                checks_passed += 1
            else:
                checks_passed += retention_ratio

        # Citation requirement
        citation_req = reqs.get("citations")
        min_sources = reqs.get("min_sources", 0)
        if citation_req == "required" or min_sources > 0:
            total_checks += 1
            paren_cites = _CITATION_PAREN_RE.findall(text)
            inline_cites = _CITATION_INLINE_RE.findall(text)
            total_cites = len(paren_cites) + len(inline_cites)
            cites_ok = total_cites >= max(1, min_sources)
            details["citation_compliance"] = {
                "required": citation_req,
                "min_sources": min_sources,
                "found_citations_count": total_cites,
                "passed": cites_ok,
            }
            if cites_ok:
                checks_passed += 1
        elif citation_req == "prohibited":
            total_checks += 1
            paren_cites = _CITATION_PAREN_RE.findall(text)
            cites_absent = len(paren_cites) == 0
            details["citation_compliance"] = {
                "prohibited": True,
                "found_citations_count": len(paren_cites),
                "passed": cites_absent,
            }
            if cites_absent:
                checks_passed += 1

        # Forbidden words / AI slop
        forbidden_words = reqs.get("forbidden_words", [])
        if forbidden_words:
            total_checks += 1
            found_forbidden = [w for w in forbidden_words if re.search(r"\b" + re.escape(w) + r"\b", text, re.IGNORECASE)]
            details["forbidden_words"] = {
                "forbidden": forbidden_words,
                "found": found_forbidden,
                "passed": len(found_forbidden) == 0,
            }
            if len(found_forbidden) == 0:
                checks_passed += 1

        score = (checks_passed / total_checks) if total_checks > 0 else 1.0
        details["checks_passed"] = checks_passed
        details["total_checks"] = total_checks

        return MetricScore(
            metric_name=self.metric_name,
            score=round(score, 4),
            details=details,
            deterministic=True,
        )


# --- 2. Factuality & Grounding Evaluator (v2-semantic) -----------------------

class FactualityEvaluator:
    """Evaluates factual grounding via deterministic checks and semantic entailment."""

    metric_name = "factuality"
    metric_version = "factuality/v2-semantic"

    def __init__(self, entailment_evaluator: EntailmentEvaluator | None = None) -> None:
        self.entailment_evaluator = entailment_evaluator or DeterministicEntailmentEvaluator()

    def evaluate(self, case: BenchmarkCase, candidate: CandidateOutput) -> MetricScore:
        text = candidate.text or ""
        doc = Document.parse(text)
        extractor = HeuristicClaimExtractor()
        claims = extractor.extract(doc)

        known_corpus_text = " ".join([
            str(src.get("title", "")) + " " + str(src.get("snippet", "")) + " " + str(src.get("summary", ""))
            for src in case.source_corpus
        ])
        known_context_text = " ".join([str(v) for v in case.context.values()]) + " " + (case.input_text or "")
        ground_truth = (known_corpus_text + " " + known_context_text + " " + case.task).strip()
        ground_truth_lower = ground_truth.lower()

        # Deterministic checks: numbers, dates, citations
        candidate_numbers = set(_NUMBER_RE.findall(text))
        ground_numbers = set(_NUMBER_RE.findall(ground_truth))

        # Check for numeric contradictions: numbers in text that directly contradict numbers in evidence
        contradicted_numbers = []
        for n in candidate_numbers:
            if n not in ground_numbers and not n.startswith("202") and not n.startswith("199"):
                # If ground truth has numbers of similar length or percentage
                if "%" in n and any("%" in gn for gn in ground_numbers):
                    contradicted_numbers.append(n)
                elif any(gn.isdigit() and len(gn) == len(n) and gn != n for gn in ground_numbers):
                    contradicted_numbers.append(n)

        # Citation grounding check
        valid_authors = set()
        for src in case.source_corpus:
            for auth in src.get("authors", []):
                for part in auth.split():
                    if len(part) > 2:
                        valid_authors.add(part.lower())
            title = src.get("title", "")
            for word in title.split():
                if len(word) > 4:
                    valid_authors.add(word.lower())

        paren_cites = _CITATION_PAREN_RE.findall(text)
        fabricated_citations = []
        if case.source_corpus:
            for cite in paren_cites:
                cite_author = cite.split(",")[0].replace("et al.", "").strip().lower()
                first_name = cite_author.split()[0] if cite_author.split() else ""
                if first_name and first_name not in valid_authors:
                    fabricated_citations.append(cite)

        # Semantic entailment evaluation across extracted claims
        entailed_count = 0
        partially_entailed_count = 0
        not_entailed_count = 0
        contradicted_count = 0
        entailment_records = []

        if not claims:
            # Fallback if no specific atomic claims extracted: evaluate text paragraphs directly
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip().split()) >= 8]
            for p in paragraphs[:5]:
                res = self.entailment_evaluator.evaluate(p, ground_truth)
                if res.verdict == EntailmentVerdict.ENTAILED:
                    entailed_count += 1
                elif res.verdict == EntailmentVerdict.PARTIALLY_ENTAILED:
                    partially_entailed_count += 1
                elif res.verdict == EntailmentVerdict.CONTRADICTED:
                    contradicted_count += 1
                else:
                    not_entailed_count += 1
                entailment_records.append({"text": p[:60], "verdict": res.verdict.value, "rationale": res.rationale})
        else:
            for claim in claims:
                res = self.entailment_evaluator.evaluate(claim.text, ground_truth)
                if res.verdict == EntailmentVerdict.ENTAILED:
                    entailed_count += 1
                elif res.verdict == EntailmentVerdict.PARTIALLY_ENTAILED:
                    partially_entailed_count += 1
                elif res.verdict == EntailmentVerdict.CONTRADICTED:
                    contradicted_count += 1
                else:
                    not_entailed_count += 1
                entailment_records.append({"claim": claim.text[:80], "verdict": res.verdict.value, "rationale": res.rationale})

        total_evaluated = max(1, entailed_count + partially_entailed_count + not_entailed_count + contradicted_count)
        base_support_rate = ((entailed_count * 1.0) + (partially_entailed_count * 0.6)) / total_evaluated

        unsupported_numbers = [n for n in candidate_numbers if n not in ground_numbers and not n.startswith("202") and not n.startswith("199")]

        # Penalties: severe for contradiction or fabricated citations, moderate for contradicted numbers
        penalties = (contradicted_count * 0.20) + (len(contradicted_numbers) * 0.10) + (len(fabricated_citations) * 0.15)
        score = max(0.0, min(1.0, base_support_rate - penalties))

        return MetricScore(
            metric_name=self.metric_name,
            score=round(score, 4),
            details={
                "total_claims": total_evaluated,
                "entailed_claims": entailed_count,
                "partially_entailed_claims": partially_entailed_count,
                "not_entailed_claims": not_entailed_count,
                "contradicted_claims": contradicted_count,
                "unsupported_numbers": unsupported_numbers[:10],
                "contradicted_numbers": contradicted_numbers[:5],
                "fabricated_citations": fabricated_citations,
                "base_support_rate": round(base_support_rate, 4),
                "sample_entailments": entailment_records[:5],
            },
            deterministic=True,
            metric_version=self.metric_version,
        )


# --- 3. Citation Integrity Evaluator (v2) -----------------------------------

class CitationIntegrityEvaluator:
    """Evaluates citation resolution, metadata matching, DOI validity, and source support against the case corpus."""

    metric_name = "citation_integrity"
    metric_version = "citation-integrity/v2"

    def evaluate(self, case: BenchmarkCase, candidate: CandidateOutput) -> MetricScore:
        text = candidate.text or ""
        reqs = case.requirements or {}
        if reqs.get("citations") == "prohibited":
            return MetricScore(
                metric_name=self.metric_name,
                score=1.0,
                details={"citations_prohibited": True},
                deterministic=True,
                metric_version=self.metric_version,
            )

        paren_cites = _CITATION_PAREN_RE.findall(text)
        dois = [d.rstrip(".,;:!?)>]") for d in _DOI_RE.findall(text)]
        urls = [u.rstrip(".,;:!?)>]") for u in _URL_RE.findall(text)]

        corpus_urls = {src.get("url").strip() for src in case.source_corpus if src.get("url")}
        corpus_dois = {src.get("doi").strip().lower() for src in case.source_corpus if src.get("doi")}

        if case.source_corpus and (corpus_urls or corpus_dois):
            resolvable_urls = [u for u in urls if u in corpus_urls]
            resolvable_dois = [d for d in dois if d.lower() in corpus_dois]
        else:
            resolvable_urls = [u for u in urls if u in corpus_urls or "doi.org" in u or "gov" in u]
            resolvable_dois = [d for d in dois if d.lower() in corpus_dois or (d.startswith("10.") and len(d) > 8)]

        total_sources_cited = len(paren_cites) + len(dois) + len(urls)
        if total_sources_cited == 0:
            score = 0.5 if reqs.get("citations") != "required" else 0.0
            return MetricScore(
                metric_name=self.metric_name,
                score=score,
                details={"total_citations": 0, "status": "NO_CITATIONS"},
                deterministic=True,
                metric_version=self.metric_version,
            )

        resolution_rate = (len(resolvable_urls) + len(resolvable_dois)) / max(1, len(urls) + len(dois)) if (urls or dois) else 1.0

        metadata_match_rate = 1.0
        if paren_cites and case.source_corpus:
            matches = 0
            for c in paren_cites:
                c_low = c.lower()
                c_tokens = [tok for tok in re.findall(r"[A-Za-z0-9]+", c_low) if len(tok) > 2]
                for s in case.source_corpus:
                    title_or_author = (s.get("title", "") + " " + " ".join(s.get("authors", []))).lower()
                    if any(part in title_or_author for part in c_tokens):
                        matches += 1
                        break
            metadata_match_rate = matches / len(paren_cites)

        if (urls or dois) and paren_cites:
            score = (resolution_rate * 0.5) + (metadata_match_rate * 0.5)
        elif (urls or dois):
            score = resolution_rate
        else:
            score = metadata_match_rate

        return MetricScore(
            metric_name=self.metric_name,
            score=round(score, 4),
            details={
                "citations_count": len(paren_cites),
                "urls_count": len(urls),
                "dois_count": len(dois),
                "resolvable_urls_count": len(resolvable_urls),
                "resolvable_dois_count": len(resolvable_dois),
                "resolution_rate": round(resolution_rate, 4),
                "metadata_match_rate": round(metadata_match_rate, 4),
            },
            deterministic=True,
            metric_version=self.metric_version,
        )


# --- 4. Source Quality Evaluator -------------------------------------------

class SourceQualityEvaluator:
    """Evaluates semantic authority of cited sources (e.g. PRIMARY_LAW/STANDARD vs BLOG)."""

    metric_name = "source_quality"

    _TIER_SCORES = {
        SourceAuthority.PRIMARY_LAW: 1.0,
        SourceAuthority.STANDARD: 1.0,
        SourceAuthority.GOVERNMENT: 0.9,
        SourceAuthority.SCHOLARLY: 0.85,
        SourceAuthority.VENDOR_PRIMARY: 0.8,
        SourceAuthority.INDUSTRY: 0.75,
        SourceAuthority.NEWS: 0.6,
        SourceAuthority.SECONDARY: 0.5,
        SourceAuthority.COMMUNITY: 0.2,
        SourceAuthority.UNKNOWN: 0.3,
    }

    def evaluate(self, case: BenchmarkCase, candidate: CandidateOutput) -> MetricScore:
        text = candidate.text or ""
        urls = _URL_RE.findall(text)
        dois = _DOI_RE.findall(text)

        if not urls and not dois:
            # Fall back to inspecting source corpus if candidate cites by author
            used_sources = []
            for src_dict in case.source_corpus:
                title = src_dict.get("title", "")
                authors = src_dict.get("authors", [])
                if title and title.lower() in text.lower():
                    used_sources.append(src_dict)
                elif any(a.split()[-1].lower() in text.lower() for a in authors if a.split()):
                    used_sources.append(src_dict)
        else:
            used_sources = [
                src for src in case.source_corpus
                if (src.get("url") in urls) or (src.get("doi") in dois)
            ]

        if not used_sources:
            return MetricScore(
                metric_name=self.metric_name,
                score=0.5,
                details={"sources_evaluated": 0, "note": "No direct source URLs or DOIs matched."},
                deterministic=True,
            )

        authority_scores = []
        tier_counts: dict[str, int] = {}
        for idx, s in enumerate(used_sources, start=1):
            src_obj = Source(
                id=s.get("id", f"src-{idx:03d}"),
                authors=s.get("authors", []),
                url=s.get("url", ""),
                doi=s.get("doi"),
                publisher=s.get("publisher", ""),
                title=s.get("title", ""),
            )
            auth_tier = classify_source_authority(src_obj)
            score = self._TIER_SCORES.get(auth_tier, 0.4)
            authority_scores.append(score)
            tier_counts[auth_tier.value] = tier_counts.get(auth_tier.value, 0) + 1

        avg_score = statistics.mean(authority_scores) if authority_scores else 0.5
        return MetricScore(
            metric_name=self.metric_name,
            score=round(avg_score, 4),
            details={
                "sources_evaluated": len(used_sources),
                "tier_counts": tier_counts,
                "average_authority_score": round(avg_score, 4),
            },
            deterministic=True,
        )


# --- 5. Meaning Preservation Evaluator -------------------------------------

class MeaningPreservationEvaluator:
    """Evaluates meaning preservation for rewrite/editing tasks using deterministic diffing."""

    metric_name = "meaning_preservation"

    def evaluate(self, case: BenchmarkCase, candidate: CandidateOutput) -> MetricScore:
        original = case.input_text or ""
        final = candidate.text or ""

        if not original:
            return MetricScore(
                metric_name=self.metric_name,
                score=1.0,
                details={"not_applicable": True, "reason": "No original input_text to compare against."},
                deterministic=True,
            )

        reviewer = MeaningPreservationReviewer()
        orig_doc = Document.parse(original)
        final_doc = Document.parse(final)
        result = reviewer.compare(orig_doc, final_doc)

        diff_count = len(result.diffs)
        # Severity weighting: polarity drops or number drops are severe
        severe_diffs = sum(1 for d in result.diffs if "polarity" in d.kind or "number" in d.kind or "negation" in d.kind)
        score = max(0.0, 1.0 - (diff_count * 0.1) - (severe_diffs * 0.15))

        return MetricScore(
            metric_name=self.metric_name,
            score=round(score, 4),
            details={
                "status": result.status,
                "diff_count": diff_count,
                "severe_diff_count": severe_diffs,
                "diffs": [{"kind": d.kind, "description": d.description} for d in result.diffs[:10]],
            },
            deterministic=True,
        )


# --- 6. Multidimensional Voice Fidelity Evaluator (v2-distance) ------------

class VoiceFidelityEvaluator:
    """Measures stylistic distribution distances against reference author writing without fabricating a single percentage."""

    metric_name = "voice_fidelity"
    metric_version = "voice-fidelity/v2-distance"

    def evaluate(
        self,
        case: BenchmarkCase,
        candidate: CandidateOutput,
        reference_features: DocumentFeatures | None = None,
    ) -> MetricScore:
        text = candidate.text or ""
        features = extract_features(text)

        if reference_features is None:
            ref_text = case.input_text or case.context.get("reference_text") or case.context.get("voice_reference")
            if ref_text and len(str(ref_text).split()) >= 8:
                reference_features = extract_features(str(ref_text))

        cand_profile = {
            "sentence_length_mean": round(features.sentence_length_mean, 2),
            "sentence_length_stdev": round(features.sentence_length_stdev, 2),
            "paragraph_words_mean": round(features.paragraph_words_mean, 2),
            "first_person_rate": round(features.first_person_rate, 4),
            "lexical_diversity": round(features.lexical_diversity, 4),
            "transition_rate": round(features.transition_rate, 4),
            "passive_rate": round(features.passive_rate, 4),
            "parenthetical_rate": round(features.parenthetical_rate, 4),
        }

        if reference_features is None:
            return MetricScore(
                metric_name=self.metric_name,
                score=0.5,
                details={
                    "verdict": "NO_DEMONSTRATED_VOICE_EFFECT",
                    "reason": "No reference author writing or profile provided for this case.",
                    "reference_available": False,
                    "multidimensional_profile": cand_profile,
                },
                deterministic=True,
                metric_version=self.metric_version,
            )

        # Multidimensional distance comparison against reference distribution
        dims = (
            ("sentence_length_mean", 10.0),
            ("sentence_length_stdev", 6.0),
            ("paragraph_words_mean", 30.0),
            ("first_person_rate", 0.05),
            ("lexical_diversity", 0.15),
            ("transition_rate", 0.1),
            ("passive_rate", 0.1),
            ("parenthetical_rate", 0.05),
            ("contraction_rate", 0.05),
        )

        dimension_deltas = {}
        normalized_errors = []
        for dim_name, scale in dims:
            cand_val = getattr(features, dim_name, 0.0)
            ref_val = getattr(reference_features, dim_name, 0.0)
            delta = abs(cand_val - ref_val)
            norm_err = min(2.0, delta / scale)
            dimension_deltas[dim_name] = {
                "candidate": round(cand_val, 4),
                "reference": round(ref_val, 4),
                "delta": round(delta, 4),
                "normalized_error": round(norm_err, 4),
            }
            normalized_errors.append(norm_err)

        mean_err = statistics.mean(normalized_errors) if normalized_errors else 0.0
        bounded_score = max(0.0, 1.0 - (mean_err * 0.5))
        verdict = "MATCHED_VOICE" if bounded_score >= 0.70 else ("DEVIATED_VOICE" if bounded_score >= 0.45 else "MISMATCHED_VOICE")

        return MetricScore(
            metric_name=self.metric_name,
            score=round(bounded_score, 4),
            details={
                "verdict": verdict,
                "multidimensional_dimensions": dimension_deltas,
                "multidimensional_profile": cand_profile,
                "mean_normalized_error": round(mean_err, 4),
                "reference_available": True,
            },
            deterministic=True,
            metric_version=self.metric_version,
        )


# --- 7. Structural Diversity Evaluator (v2) ---------------------------------

class StructuralDiversityEvaluator:
    """Measures structural variation across repeated runs to detect template convergence without conflating raw CV with normalized score."""

    metric_name = "structural_diversity"
    metric_version = "structural-diversity/v2"

    def evaluate_batch(self, outputs: Sequence[CandidateOutput]) -> MetricScore:
        valid_texts = [c.text for c in outputs if c.text and len(c.text.split()) >= 6]
        if len(valid_texts) < 3:
            return MetricScore(
                metric_name=self.metric_name,
                score=0.5,
                details={"verdict": NOT_EVALUATED, "samples": len(valid_texts), "reason": "Insufficient samples (< 3)."},
                deterministic=True,
                metric_version=self.metric_version,
            )

        feature_vectors = [extract_features(t) for t in valid_texts]
        cv_metrics = {}
        converged_dims = []

        target_dims = (
            "sentence_length_mean",
            "sentence_length_stdev",
            "paragraph_words_mean",
            "lexical_diversity",
            "transition_rate",
            "first_person_rate",
        )

        for dim in target_dims:
            values = [getattr(fv, dim, 0.0) for fv in feature_vectors]
            cv = _coefficient_of_variation(values)
            cv_metrics[dim] = round(cv, 4)
            if cv < 0.15:  # Low variation across distinct prompts indicates template convergence
                converged_dims.append(dim)

        verdict = PASS
        if len(converged_dims) >= 4:
            verdict = FAIL
        elif len(converged_dims) >= 2:
            verdict = WARNING

        mean_raw_cv = statistics.mean(cv_metrics.values()) if cv_metrics else 0.0

        # Calibrated normalized score: penalizes both rigid collapse (< 0.15) and extreme structural chaos (> 1.20)
        if mean_raw_cv < 0.15:
            score = max(0.1, (mean_raw_cv / 0.15) * 0.5)
        elif mean_raw_cv <= 0.85:
            score = 0.85 + (0.15 * max(0.0, 1.0 - (abs(mean_raw_cv - 0.40) / 0.45)))
        else:
            # Penalize excessive structural instability (> 0.85 CV)
            score = max(0.40, 1.0 - ((mean_raw_cv - 0.85) * 0.5))

        return MetricScore(
            metric_name=self.metric_name,
            score=round(score, 4),
            details={
                "verdict": verdict,
                "samples": len(valid_texts),
                "raw_cv": cv_metrics,
                "mean_raw_cv": round(mean_raw_cv, 4),
                "converged_dimensions": converged_dims,
            },
            deterministic=True,
            metric_version=self.metric_version,
        )


# --- 8. Writing Quality Signals Evaluator -----------------------------------

class WritingQualitySignalsEvaluator:
    """Evaluates deterministic writing quality signals: AI slop, redundancy, lint, and red pen."""

    metric_name = "writing_quality_signals"

    def evaluate(self, case: BenchmarkCase, candidate: CandidateOutput) -> MetricScore:
        text = candidate.text or ""
        words = len(text.split())
        if words == 0:
            return MetricScore(metric_name=self.metric_name, score=0.0, details={}, deterministic=True)

        doc = Document.parse(text)

        # 1. Lint engine
        from howlwriter.config.defaults import default_config
        linter = LintEngine()
        matches = linter.run(doc, default_config())
        ai_style_matches = [m for m in matches if m.rule_code == AI_STYLE_BANNED_WORD]

        # 2. Redundancy
        redundancy_result = detect_redundancy(doc)

        # 3. Red Pen critic
        critic = RedPenEngine()
        findings = critic.critique(doc)

        # Calculate signal score: starts at 1.0, penalized by density of slop/lint/redundancy
        ai_slop_rate = (len(ai_style_matches) / words) * 100  # matches per 100 words
        lint_penalty = min(0.3, len(matches) * 0.02)
        slop_penalty = min(0.4, ai_slop_rate * 0.2)
        redundancy_penalty = min(0.3, len(redundancy_result.findings) * 0.1)
        redpen_penalty = min(0.2, len(findings) * 0.03)

        score = max(0.0, 1.0 - (lint_penalty + slop_penalty + redundancy_penalty + redpen_penalty))

        return MetricScore(
            metric_name=self.metric_name,
            score=round(score, 4),
            details={
                "word_count": words,
                "lint_violations_count": len(matches),
                "ai_slop_matches_count": len(ai_style_matches),
                "redundancy_findings_count": len(redundancy_result.findings),
                "redpen_findings_count": len(findings),
            },
            deterministic=True,
        )


# Global registry of evaluators
EVALUATORS = {
    "requirement_satisfaction": RequirementSatisfactionEvaluator(),
    "factuality": FactualityEvaluator(),
    "citation_integrity": CitationIntegrityEvaluator(),
    "source_quality": SourceQualityEvaluator(),
    "meaning_preservation": MeaningPreservationEvaluator(),
    "voice_fidelity": VoiceFidelityEvaluator(),
    "structural_diversity": StructuralDiversityEvaluator(),
    "writing_quality_signals": WritingQualitySignalsEvaluator(),
}


def get_evaluator(name: str) -> Any:
    return EVALUATORS.get(name)
