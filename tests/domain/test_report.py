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
