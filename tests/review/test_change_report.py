"""Change accountability: what changed, why, whether meaning and citations held."""

from __future__ import annotations

import json

from howlwriter.cli.main import main
from howlwriter.review.change_report import NOT_DETERMINABLE, build_change_report

ORIGINAL = (
    "Backups belong inside the risk program because recovery is a business decision (Moreno, 2025). "
    "I would test restores against a stated downtime tolerance and assign an owner to each system. "
    "Vendors need the same scrutiny, so ask where copies live and who can delete them. "
    "This is my recommendation, not a cited result.\n\n"
    "**References**\n\n"
    "Moreno, D. (2025). *Backup resilience in ransomware response*. Example Press. https://doi.org/10.1234/example.1\n"
)


def test_a_clean_document_produces_a_zero_change_revision():
    report = build_change_report(ORIGINAL, ORIGINAL)
    assert not report.changed and report.changes == [] and report.summary == "No changes."
    assert report.meaning_status == "PASS" and report.citation_changes == []


def test_removed_workflow_note_is_explained_and_not_a_citation_change():
    revised = ORIGINAL.replace(" This is my recommendation, not a cited result.", "")
    report = build_change_report(ORIGINAL, revised)
    (change,) = report.changes
    assert change.kind == "removed" and "the sentence was removed" in change.reasons
    assert change.citation_effect == "none"


def test_a_reworded_sentence_with_unchanged_meaning():
    revised = ORIGINAL.replace("I would test restores against", "I would test every restore against")
    (change,) = build_change_report(ORIGINAL, revised).changes
    assert change.kind == "reworded" and change.meaning == "PASS"
    assert change.reasons == [NOT_DETERMINABLE]  # no invented rationale


def test_citation_change_is_attributed_to_the_sentence_that_carried_it():
    revised = ORIGINAL.replace("(Moreno, 2025)", "(Moreno, 2024)").replace("Moreno, D. (2025)", "Moreno, D. (2024)")
    report = build_change_report(ORIGINAL, revised)
    assert report.changes[0].citation_effect == "citation changed"
    assert "the citation changed" in report.changes[0].reasons
    assert any(c.code == "CITATION_YEAR_CHANGED" for c in report.citation_changes)


def test_a_dropped_citation_is_visible_in_both_views():
    revised = ORIGINAL.replace(" (Moreno, 2025)", "")
    report = build_change_report(ORIGINAL, revised)
    assert report.changes[0].citation_effect == "citation removed"
    assert any(c.severity == "error" for c in report.citation_changes)


def test_changed_number_flags_meaning_and_names_the_reason():
    original = "The program cut recovery time by 40% in the surveyed teams last year."
    revised = "The program cut recovery time by 60% in the surveyed teams last year."
    (change,) = build_change_report(original, revised).changes
    assert change.meaning == "FLAGGED" and "a number changed" in change.reasons


def test_requirements_report_the_word_count_before_and_after():
    revised = ORIGINAL.replace(" This is my recommendation, not a cited result.", "")
    report = build_change_report(ORIGINAL, revised, min_words=20, max_words=60)
    assert report.word_count_after < report.word_count_before
    assert "within 20-60" in report.requirements[0]


def test_voice_is_not_scored_unless_requested_and_unavailable_is_honest(tmp_path):
    assert build_change_report(ORIGINAL, ORIGINAL).voice["status"] == "NOT_REQUESTED"
    report = build_change_report(ORIGINAL, ORIGINAL.replace("Vendors", "Suppliers"), identity="nobody-here")
    assert report.voice["status"] == "UNAVAILABLE"  # no profile: never a made-up score


def test_finalize_cli_without_changes_is_unchanged(tmp_path, capsys):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(ORIGINAL), b.write_text(ORIGINAL)
    assert main(["finalize", str(a), str(b)]) == 0
    assert capsys.readouterr().out.strip() == "MEANING PRESERVATION: PASS"


def test_finalize_changes_cli_json_and_text(tmp_path, capsys):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(ORIGINAL), b.write_text(ORIGINAL.replace(" This is my recommendation, not a cited result.", ""))
    assert main(["finalize", str(a), str(b), "--changes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["changes"][0]["kind"] == "removed"
    assert main(["finalize", str(a), str(a), "--changes"]) == 0
    assert "No changes." in capsys.readouterr().out
