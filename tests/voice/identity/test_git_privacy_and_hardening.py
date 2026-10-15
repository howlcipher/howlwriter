"""Git protection for private data, and hardened extraction of untrusted files."""

from __future__ import annotations

import io
from pathlib import Path
import subprocess
import zipfile

import pytest

from howlwriter.domain.document import Document
from howlwriter.voice.corpus.extract import STATUS_FAILED, MAX_COMPRESSION_RATIO, extract

REPO = Path(__file__).resolve().parents[3]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )


pytestmark = pytest.mark.skipif(not (REPO / ".git").exists(), reason="not a git checkout")


@pytest.mark.parametrize(
    "path",
    [
        "voices/william-academic/profile.json",
        "voices/william-professional/calibration.json",
        "identities/william/inventory.json",
        ".howlwriter/identities/william/decisions.json",
        "anywhere/review_queue.yaml",
        "chatgpt-export-2026/conversations.json",
        "conversations.json",
        "credentials/google_client_secret.json",
        "google_token.json",
        "report.voice-eval.json",
        "profiles/private/me.yaml",
    ],
)
def test_private_paths_are_ignored(path):
    assert _git("check-ignore", "-q", "--no-index", path).returncode == 0, path


@pytest.mark.parametrize(
    "path",
    [
        "frontend/src/components/voices/VoicesPanel.tsx",
        "frontend/src/components/voices/VoiceIntelligencePanel.tsx",
        "src/howlwriter/voice/identity/store.py",
        "src/howlwriter/evaluation/voice_match.py",
        "tests/voice/identity/test_scanner.py",
    ],
)
def test_source_is_not_ignored(path):
    assert _git("check-ignore", "-q", "--no-index", path).returncode == 1, path


def test_no_private_artifact_is_tracked():
    tracked = _git("ls-files").stdout.splitlines()
    forbidden = (
        "inventory.json",
        "decisions.json",
        "review_queue.yaml",
        "scan_report.json",
        "chat_evidence.json",
        "conversations.json",
        "calibration.json",
        "supporting_evidence.json",
    )
    hits = [
        p
        for p in tracked
        if p.rsplit("/", 1)[-1] in forbidden or p.startswith(("voices/", "identities/"))
    ]
    assert hits == []


def test_zip_bomb_shaped_docx_is_refused(tmp_path):
    path = tmp_path / "bomb.docx"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<a>" + "A" * (MAX_COMPRESSION_RATIO * 2000) + "</a>")
    path.write_bytes(buffer.getvalue())
    result = extract(path)
    assert result.status == STATUS_FAILED and "decompression bomb" in result.reason


def test_extract_uses_supplied_bytes_without_rereading(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("on disk", encoding="utf-8")
    result = extract(path, b"supplied bytes, read once")
    assert result.text.startswith("supplied")


def test_abbreviation_split_across_a_newline_does_not_crash_parsing():
    document = Document.parse("The U.S.\nGovernment said so. Then e.g.   this. Done.")
    sentences = [s for _, _, s in document.all_sentences()]
    raw = document.paragraphs[0].raw_text
    assert all(raw[s.char_start:s.char_end] == s.text for s in sentences)
    assert sentences[0].text == "The U.S.\nGovernment said so."
