"""Unit tests for the factuality and claim grounding metric."""

from __future__ import annotations

from howlwriter.evaluation.metrics import FactualityEvaluator
from howlwriter.evaluation.models import BenchmarkCase, CandidateOutput


def test_factuality_grounded_text():
    case = BenchmarkCase(
        id="fact_case_1",
        task="Explain GDPR administrative fines.",
        source_corpus=[
            {
                "title": "General Data Protection Regulation",
                "authors": ["European Parliament"],
                "snippet": "Article 83 imposes fines up to 20,000,000 EUR or 4% of total worldwide turnover.",
            }
        ],
    )
    text = "Under the GDPR, Article 83 imposes fines up to 20,000,000 EUR or 4% of total worldwide turnover."
    cand = CandidateOutput(candidate_id="c1", system_id="hw", text=text)
    evaluator = FactualityEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score >= 0.8
    assert len(score.details["fabricated_citations"]) == 0


def test_factuality_penalizes_fabricated_citations_and_invented_numbers():
    case = BenchmarkCase(
        id="fact_case_2",
        task="Explain GDPR administrative fines.",
        source_corpus=[
            {
                "title": "General Data Protection Regulation",
                "authors": ["European Parliament"],
                "snippet": "Article 83 establishes penalties.",
            }
        ],
    )
    # Cites unknown author (Smith, 2023) and includes invented numbers ($999,999)
    text = "According to (Smith, 2023), GDPR penalties are set at exactly $999,999 for 87% of all violations."
    cand = CandidateOutput(candidate_id="c2", system_id="baseline", text=text)
    evaluator = FactualityEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score < 0.7
    assert len(score.details["fabricated_citations"]) > 0
    assert "999,999" in score.details["unsupported_numbers"] or "87%" in score.details["unsupported_numbers"]
