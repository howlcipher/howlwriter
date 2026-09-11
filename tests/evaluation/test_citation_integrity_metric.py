"""Unit tests for citation integrity and source quality evaluators."""

from __future__ import annotations

from howlwriter.evaluation.metrics import (
    CitationIntegrityEvaluator,
    SourceQualityEvaluator,
)
from howlwriter.evaluation.models import BenchmarkCase, CandidateOutput


def test_citation_integrity_valid_resolvable_citations():
    case = BenchmarkCase(
        id="cite_case_1",
        requirements={"citations": "required"},
        source_corpus=[
            {
                "title": "NIST SP 800-207",
                "authors": ["Rose", "Borbor"],
                "year": 2020,
                "url": "https://csrc.nist.gov/publications/detail/sp/800-207/final",
                "doi": "10.6028/NIST.SP.800-207",
            }
        ],
    )
    text = (
        "Zero Trust principles dictate continuous evaluation (Rose, 2020). "
        "Further details available at https://csrc.nist.gov/publications/detail/sp/800-207/final."
    )
    cand = CandidateOutput(candidate_id="c1", system_id="hw", text=text)
    evaluator = CitationIntegrityEvaluator()
    score = evaluator.evaluate(case, cand)

    assert score.score >= 0.8
    assert score.details["citations_count"] >= 1
    assert score.details["resolution_rate"] == 1.0


def test_source_quality_tiering():
    case = BenchmarkCase(
        id="sq_case_1",
        source_corpus=[
            {
                "title": "NIST Special Publication",
                "url": "https://csrc.nist.gov/pubs/fips/203/final",
                "publisher": "NIST",
            },
            {
                "title": "Random Blog Post",
                "url": "https://medium.com/some-random-user/post",
                "publisher": "Medium",
            },
        ],
    )
    text = "Referencing https://csrc.nist.gov/pubs/fips/203/final for standards."
    cand_high = CandidateOutput(candidate_id="c1", system_id="hw", text=text)

    evaluator = SourceQualityEvaluator()
    score_high = evaluator.evaluate(case, cand_high)
    assert score_high.score >= 0.9

    text_low = "Referencing https://medium.com/some-random-user/post for analysis."
    cand_low = CandidateOutput(candidate_id="c2", system_id="baseline", text=text_low)
    score_low = evaluator.evaluate(case, cand_low)
    assert score_low.score < score_high.score
