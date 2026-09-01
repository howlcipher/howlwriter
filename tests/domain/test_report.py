from howlwriter.domain.report import WritingReport


def test_render_text_omits_unset_metrics():
    report = WritingReport(status="READY", banned_words=0, ai_style_warnings=1, meaning_preservation="PASS")
    text = report.render_text()
    assert "Banned words" in text
    assert "AI-style warnings" in text
    assert "Voice match" not in text
    assert "Unsupported claims" not in text
    assert "Sources used" not in text


def test_render_text_includes_voice_match_when_present():
    report = WritingReport(status="READY", voice_match=0.91)
    text = report.render_text()
    assert "Voice match" in text
    assert "91%" in text


def test_render_text_shows_status_line():
    report = WritingReport(status="BLOCKED")
    assert "STATUS: BLOCKED" in report.render_text()


def test_render_text_lists_changes_and_sources():
    from howlwriter.domain.report import ChangeRecord
    from howlwriter.domain.source import Source

    report = WritingReport(
        status="READY",
        changes=[ChangeRecord(description="removed 3 words")],
        sources=[Source(id="s1", title="Example Source", authors=[])],
    )
    text = report.render_text()
    assert "removed 3 words" in text
    assert "[1] Example Source" in text


def test_render_text_omits_new_sections_when_fields_none():
    report = WritingReport(status="READY")
    text = report.render_text()
    assert "Requirements Coverage" not in text
    assert "Consistency Review" not in text
    assert "Hard Maximum Words" not in text
    assert "Identifier Warnings" not in text


def test_render_text_includes_new_sections_when_populated():
    report = WritingReport(
        status="NEEDS_REVIEW",
        target_words=1980,
        min_words=1650,
        max_words=2200,
        hard_max_words=2750,
        target_pages_min=6,
        target_pages_max=9,
        max_pages=10,
        required_criteria_count=4,
        present_criteria_count=3,
        requirements_coverage_status="FAIL",
        quotation_warnings=0,
        identifier_warnings=1,
        redundancy_findings_count=2,
        consistency_review_status="PASS_WITH_WARNINGS",
        consistency_findings_count=1,
    )
    text = report.render_text()
    assert "Target Pages:        6–9" in text
    assert "Maximum Pages:       10" in text
    assert "Hard Maximum Words:  2750" in text
    assert "Requirements Coverage:" in text
    assert "Coverage:            3/4" in text
    assert "Identifier Warnings: 1" in text
    assert "Redundancy findings" in text
    assert "Consistency Review:" in text
    assert "Verdict:             PASS_WITH_WARNINGS" in text
