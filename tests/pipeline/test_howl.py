from pathlib import Path

from howlwriter.config.defaults import default_config
from howlwriter.pipeline.howl import run_howl_pipeline

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_pipeline_completes_and_surfaces_real_findings():
    result = run_howl_pipeline(FIXTURES / "sample_llm_draft.md", default_config())

    assert result.report.banned_words == 2
    assert result.report.ai_style_warnings > 0
    assert len(result.red_pen_findings) > 0


def test_pipeline_reports_pass_when_no_rewrite_occurred():
    result = run_howl_pipeline(FIXTURES / "sample_llm_draft.md", default_config())
    assert result.meaning_result.status == "PASS"
    assert result.report.meaning_preservation == "PASS"
    assert result.report.status == "READY"


def test_pipeline_report_omits_unmeasured_metrics():
    result = run_howl_pipeline(FIXTURES / "sample_llm_draft.md", default_config())
    rendered = result.report.render_text()
    assert "Voice match" not in rendered
    assert "Unsupported claims" not in rendered
    assert "Sources used" not in rendered
    assert "Citation errors" not in rendered


def test_pipeline_on_clean_document_yields_no_lint_findings():
    result = run_howl_pipeline(FIXTURES / "sample_clean_human.md", default_config())
    assert result.lint_matches == []
    assert result.report.banned_words == 0
    assert result.report.ai_style_warnings == 0


def test_pipeline_final_document_preserves_word_content_when_no_safe_rewrite_applies():
    result = run_howl_pipeline(FIXTURES / "sample_llm_draft.md", default_config())
    original_words = set(result.original_document.text.split())
    final_words = set(result.final_document.text.split())
    assert original_words == final_words
