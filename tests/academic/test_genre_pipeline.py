"""The academic pipeline applies genre conventions to the finished text."""

from datetime import date

import pytest

from howlwriter.academic.pipeline import run_academic_pipeline
from howlwriter.academic.spec import AssignmentSpec
from howlwriter.config.defaults import default_config
from howlwriter.domain.source import Source, SourceType
from src.control_plane.agent_execution import FakeAgentBackend

_SOURCE = Source(
    id="S001",
    title="Zero Trust Governance for Autonomous AI Agents",
    authors=["Oladimeji, Ganiyu"],
    publication_date=date(2025, 3, 1),
    publisher="Elsevier BV",
    doi="10.2139/ssrn.7194038",
    access_date=date.today(),
    source_type=SourceType.JOURNAL_ARTICLE,
    retrieved_text=(
        "Autonomous AI agents represent an emerging paradigm in distributed computing. "
        "Dynamic delegated authorization reduces stale token privileges by 42% in multi-agent systems."
    ),
)


def _reply(body_lines):
    body = "\n".join("  " + line for line in body_lines)
    return f"""```yaml
body_markdown: |
{body}
claims_made:
  - claim: "Dynamic delegated authorization reduces stale token privileges by 42%"
    source_id: "S001"
verdict: "PASS"
differences: []
rationale: "Aligned."
warnings: []
```"""


def _run(tmp_path, monkeypatch, genre, body_lines):
    monkeypatch.setenv("HOWLWRITER_RUNS_DIR", str(tmp_path / "runs"))
    spec = AssignmentSpec(
        title="Reply", topic="Reply to a classmate about delegated authorization.", genre=genre,
        target_words=40, word_tolerance_percent=50.0, source_requirements=dict(minimum_sources=1))
    backend = FakeAgentBackend(agent_id="fake_genre_backend", default_stdout=_reply(body_lines))
    return run_academic_pipeline(spec, default_config(), existing_sources=[_SOURCE], custom_backend=backend)


GOOD = [
    "You are right that the contract is where a framework becomes enforceable.",
    "Dynamic delegated authorization reduces stale token privileges by 42% (Oladimeji, 2025).",
    "I would add that vendors change their agents after signing, which is what monitoring should catch.",
]


def test_conforming_peer_reply_is_ready_and_reports_zero_genre_findings(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, "academic_peer_reply", GOOD)
    assert result.report.genre_findings == 0
    assert result.report.status == "READY"


@pytest.mark.parametrize("body,expected", [
    (["## Response"] + GOOD, "headings"),
    (["Great post, Peter."] + GOOD, "formulaic opening"),
])
def test_wrong_genre_prose_holds_the_reply(tmp_path, monkeypatch, body, expected):
    result = _run(tmp_path, monkeypatch, "academic_peer_reply", body)
    assert result.report.genre_findings >= 1, expected
    assert result.report.status == "NEEDS_REVIEW"


def test_no_genre_leaves_the_report_field_empty(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, "", GOOD)
    assert result.report.genre_findings is None
