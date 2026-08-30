import json

from howlwriter.cli.main import main


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
