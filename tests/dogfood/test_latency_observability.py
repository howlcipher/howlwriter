"""Latency observability tests ensuring duration metadata is properly tracked and rendered."""

from howlwriter.domain.report import ChangeRecord, WritingReport


def test_writing_report_renders_latency_section_when_durations_present():
    report = WritingReport(
        status="READY",
        mode="standard",
        humanizer_provider="codex",
        meaning_reviewer_provider="agy",
        reviewer_independence="INDEPENDENT",
        humanizer_duration_seconds=28.4,
        meaning_reviewer_duration_seconds=19.2,
        total_duration_seconds=48.1,
        changes=[ChangeRecord(description="Tightened phrasing")],
    )

    rendered = report.render_text()

    assert "Latency:" in rendered
    assert "Humanizer:           28.4s" in rendered
    assert "Meaning Review:      19.2s" in rendered
    assert "Total:               48.1s" in rendered


def test_writing_report_omits_latency_section_when_no_durations():
    report = WritingReport(
        status="READY",
        mode="standard",
    )

    rendered = report.render_text()
    assert "Latency:" not in rendered
