from __future__ import annotations

from pathlib import Path

import pytest

from tests.projects.fixtures import make_docx, make_pdf


class FakeOcr:
    """Stands in for the OCR engine: returns configured lines per file name."""

    name = "fake-ocr"
    available = True

    def __init__(self, lines: dict[str, list[dict]] | None = None, fail: set[str] | None = None) -> None:
        self.lines = lines or {}
        self.fail = fail or set()
        self.calls: list[str] = []

    def read(self, image: Path) -> list[dict]:
        from howlwriter.projects.adapters.images import OcrFailed

        self.calls.append(Path(image).name)
        if Path(image).name in self.fail:
            raise OcrFailed("ocr exceeded 90 s and was stopped")
        return self.lines.get(Path(image).name, [])

    def close(self) -> None:
        pass


class Off:
    available = False
    name = "disabled"

    def close(self) -> None:
        pass


def line(text: str, score: float = 0.95, box=(0, 0, 100, 20)) -> dict:
    return {"text": text, "score": score, "box": list(box), "uncertain": score < 0.75}


@pytest.fixture(autouse=True)
def private_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWLWRITER_PROJECTS_DIR", str(tmp_path / "private" / "projects"))
    monkeypatch.setenv("HOWLWRITER_IDENTITIES_DIR", str(tmp_path / "private" / "identities"))
    monkeypatch.setenv("HOWLWRITER_VOICES_DIR", str(tmp_path / "private" / "voices"))
    monkeypatch.setenv("HOWLWRITER_PREFERENCES_FILE", str(tmp_path / "private" / "prefs.yaml"))
    return tmp_path / "private"


INSTRUCTIONS_PAGE_1 = """Lab 3 - Detection versus Encryption
In this lab you will compare what an IDS can see in cleartext and encrypted traffic.
You must complete the following steps and submit a report.
1. Capture traffic to the lab server with TLS 1.3 enabled.
2. Take a screenshot of the Suricata alerts for the encrypted capture.
3. Compare the TLS handshake between the TLS 1.2 and TLS 1.3 captures.
"""
INSTRUCTIONS_PAGE_2 = """Report requirements
Include a section that discusses the limitations of signature detection.
Cite at least two sources in APA format.
Submit the report as a .docx file.
"""


@pytest.fixture
def lab_folder(tmp_path) -> Path:
    """A representative assignment folder made only of synthetic materials."""
    root = tmp_path / "lab-03"
    (root / "materials").mkdir(parents=True)
    (root / "evidence").mkdir()
    make_pdf(
        root / "materials" / "Lab 03 instructions.pdf",
        [INSTRUCTIONS_PAGE_1, INSTRUCTIONS_PAGE_2],
        title="Lab 3 instructions",
    )
    make_docx(
        root / "materials" / "tls-reference.docx",
        [
            ("Heading1", "TLS visibility"),
            (
                "",
                "An IDS without session keys sees the ClientHello and its SNI, "
                "but TLS 1.3 encrypts the certificate.",
            ),
            ("Heading1", "Rule keywords"),
            ("", "The tls.sni keyword matches the server name in the ClientHello."),
        ],
    )
    (root / "evidence" / "suricata-eve.log").write_text(
        '{"event_type":"alert","alert":{"signature":"TLS SNI lab.example.test","signature_id":1000001},'
        '"src_ip":"10.0.0.5","dest_ip":"10.0.0.9","dest_port":443}\n'
        '{"event_type":"alert","alert":{"signature":"TLS SNI lab.example.test","signature_id":1000001},'
        '"src_ip":"10.0.0.5","dest_ip":"10.0.0.9","dest_port":443}\n'
        "capture traffic TLS 1.3 lab server: 2 alerts generated\n",
        encoding="utf-8",
    )
    (root / "draft notes.md").write_text(
        "# My notes\n\nStart with the handshake comparison.\n", encoding="utf-8"
    )
    return root
