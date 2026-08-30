import json
from pathlib import Path

import pytest

from howlwriter.cli.main import main

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_lint_command_runs_and_reports_findings(tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text("We need to delve into this topic. It's not just fast, it's efficient.")

    exit_code = main(["lint", str(draft)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "AI_STYLE_BANNED_WORD" in captured.out


def test_lint_command_json_output_is_valid_json(tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text("We need to delve into this topic.")

    exit_code = main(["lint", str(draft), "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    findings = json.loads(captured.out)
    assert any(f["rule_code"] == "AI_STYLE_BANNED_WORD" for f in findings)


def test_lint_command_reports_no_findings_cleanly(tmp_path, capsys):
    draft = tmp_path / "clean.md"
    draft.write_text("Nothing objectionable here at all.")

    exit_code = main(["lint", str(draft)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "No findings." in captured.out


def test_cite_command_renders_a_reference_page(tmp_path, capsys):
    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            [
                {
                    "id": "s1",
                    "title": "A Study of Things",
                    "authors": ["Jane Smith"],
                    "publication_date": "2024-03-01",
                    "url": "https://example.com/study",
                }
            ]
        )
    )

    exit_code = main(["cite", "apa7", str(sources)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Smith, J. (2024)." in captured.out
    assert "A Study of Things." in captured.out


def test_cite_command_warns_on_missing_metadata_via_stderr(tmp_path, capsys):
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps([{"id": "s1", "title": "Undated Piece", "authors": []}]))

    exit_code = main(["cite", "apa7", str(sources), "--form", "reference"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "CITATION_METADATA_MISSING" in captured.err


def test_voice_learn_command_writes_json_profile(tmp_path, capsys):
    corpus_file = tmp_path / "corpus.txt"
    corpus_file.write_text("I can't believe it works. This is amazing! Really?")

    exit_code = main(["voice", "learn", str(corpus_file), "--author", "Test Author"])
    captured = capsys.readouterr()

    assert exit_code == 0
    profile = json.loads(captured.out)
    assert profile["author_name"] == "Test Author"
    assert profile["generated_from"] == "corpus_stats"


def test_editor_command_normalizes_and_prints(tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text("#Heading\n\nBody   text.")

    exit_code = main(["editor", str(draft)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "# Heading" in captured.out


def test_humanize_command_reports_findings(tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text("We need to delve into this.")

    exit_code = main(["humanize", str(draft)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "AI_STYLE_BANNED_WORD" in captured.out


def test_fact_check_command_extracts_claims(tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text("90% of teams reported better outcomes. Nothing else notable.")

    exit_code = main(["fact-check", str(draft)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "unverifiable" in captured.out
    assert "90%" in captured.out


def test_fact_check_verify_flag_surfaces_clean_error(tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text("90% of teams reported better outcomes.")

    exit_code = main(["fact-check", str(draft), "--verify"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "error:" in captured.err
    assert "not configured" in captured.err


@pytest.mark.parametrize("command", ["writer", "research"])
def test_model_backed_only_commands_surface_clean_errors(command, capsys):
    argv = [command, "some prompt"] if command == "writer" else [command, "some query"]
    exit_code = main(argv)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "error:" in captured.err
    assert "not configured" in captured.err
    assert "Traceback" not in captured.err


def test_sources_command_reports_unaccessed_sources(capsys):
    exit_code = main(["sources", str(FIXTURES / "sample_sources.json")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "2 source(s) loaded." in captured.out
    assert "Never actually retrieved" in captured.out
    assert "State of Distributed Work" in captured.out


def test_references_command_writes_reference_page(capsys):
    exit_code = main(["references", "apa7", str(FIXTURES / "sample_sources.json")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Chen, M." in captured.out


def test_red_pen_command_and_critique_alias_report_findings(capsys):
    exit_code = main(["red-pen", str(FIXTURES / "sample_llm_draft.md")])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "RED_PEN_001" in captured.out

    exit_code = main(["critique", str(FIXTURES / "sample_llm_draft.md")])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "RED_PEN_001" in captured.out


def test_finalize_command_reports_pass_for_identical_files(tmp_path, capsys):
    original = tmp_path / "original.md"
    revised = tmp_path / "revised.md"
    original.write_text("Sales grew by 12 percent.")
    revised.write_text("Sales grew by 12 percent.")

    exit_code = main(["finalize", str(original), str(revised)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "MEANING PRESERVATION: PASS" in captured.out


def test_finalize_command_flags_changed_numbers(tmp_path, capsys):
    original = tmp_path / "original.md"
    revised = tmp_path / "revised.md"
    original.write_text("Sales grew by 12 percent.")
    revised.write_text("Sales grew by 40 percent.")

    exit_code = main(["finalize", str(original), str(revised)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "MEANING PRESERVATION: FLAGGED" in captured.out
    assert "number_removed" in captured.out or "number_added" in captured.out


def test_howl_command_runs_the_full_pipeline(tmp_path, capsys):
    out_path = tmp_path / "out.howled.md"
    exit_code = main(
        ["howl", str(FIXTURES / "sample_llm_draft.md"), "--out", str(out_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "LINT FINDINGS" in captured.out
    assert "RED PEN FINDINGS" in captured.out
    assert "HOWLWRITER REPORT" in captured.out
    assert "STATUS: READY" in captured.out
    assert out_path.exists()
