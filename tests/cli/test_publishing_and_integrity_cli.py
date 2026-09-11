"""Tests for publishing, Google Docs auth, and source verification CLI commands."""

from pathlib import Path

from howlwriter.cli.main import main
from howlwriter.publishing.google.fake import FakeGoogleDocsAdapter
from howlwriter.publishing.google.publisher import GoogleDocsPublisher
from howlwriter.publishing.registry import register_publisher


def test_cli_google_status(capsys, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOWLWRITER_CREDENTIALS_DIR", str(tmp_path / "creds"))
    exit_code = main(["google", "status"])
    # Not authenticated returns exit code 1
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Google OAuth Authentication Status" in captured.out
    assert "Authenticated:       False" in captured.out


def test_cli_sources_verify_and_alias(capsys, tmp_path: Path):
    doc_path = tmp_path / "paper.md"
    doc_path.write_text(
        "# Cybersecurity Analysis\n\n"
        "According to research [NIST Guidelines](https://example.com/nist-guide), "
        "frameworks require periodic review.\n"
    )

    # Test 'howlwriter sources verify <path>' (broken links return exit code 1)
    exit_code_1 = main(["sources", "verify", str(doc_path)])
    assert exit_code_1 == 1
    captured_1 = capsys.readouterr()
    assert "SOURCE INTEGRITY VERIFICATION REPORT" in captured_1.out
    assert "NIST Guidelines" in captured_1.out

    # Test alias 'howlwriter verify-sources <path>'
    exit_code_2 = main(["verify-sources", str(doc_path)])
    assert exit_code_2 == 1
    captured_2 = capsys.readouterr()
    assert "SOURCE INTEGRITY VERIFICATION REPORT" in captured_2.out


def test_cli_publish_command(capsys, tmp_path: Path):
    fake = FakeGoogleDocsAdapter()
    pub = GoogleDocsPublisher(adapter=fake)
    register_publisher("google_docs", pub)

    doc_path = tmp_path / "deliverable.md"
    doc_path.write_text("# Final Deliverable\n\nVerified text for publication.")

    exit_code = main([
        "publish",
        str(doc_path),
        "--to", "google_docs",
        "--title", "Final Cloud Document",
        "--allow-unverified",
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Publication Successful!" in captured.out
    assert "Document ID:" in captured.out
    assert "URL:" in captured.out
