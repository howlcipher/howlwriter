"""Source adapters: located evidence, honest limitations, nothing invented."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

from howlwriter.projects.adapters import documents, images, media, pcap
from howlwriter.projects.adapters.images import OcrEngine, extract_image

from tests.projects.conftest import INSTRUCTIONS_PAGE_1, INSTRUCTIONS_PAGE_2, FakeOcr, Off, line
from tests.projects.fixtures import make_docx, make_pcap, make_pdf, make_png

# --- documents ------------------------------------------------------------------


def test_pdf_evidence_names_real_pages(tmp_path):
    pytest.importorskip("pypdf")
    path = make_pdf(tmp_path / "a.pdf", [INSTRUCTIONS_PAGE_1, INSTRUCTIONS_PAGE_2], title="Lab 3")
    result = documents.extract_pdf(path, path.read_bytes(), cache_dir=None, ocr=None)
    assert result.status == "extracted" and result.metadata["pages"] == 2
    pages = {item["locator"]["page"] for item in result.items}
    assert pages == {1, 2}
    page2 = [i for i in result.items if i["locator"]["page"] == 2]
    assert any("APA" in i["excerpt"] for i in page2)
    assert all(i["location"] == f"page {i['locator']['page']}" for i in result.items)


def test_pdf_image_only_page_is_flagged_not_guessed(tmp_path):
    pytest.importorskip("pypdf")
    path = make_pdf(tmp_path / "a.pdf", [INSTRUCTIONS_PAGE_1, None])
    result = documents.extract_pdf(path, path.read_bytes(), cache_dir=None, ocr=None)
    assert result.status == "partial"
    assert any("mostly images" in w and "2" in w for w in result.warnings)
    assert not [i for i in result.items if i["locator"].get("page") == 2]


def test_pdf_image_page_is_read_by_ocr_when_available(tmp_path):
    pytest.importorskip("pypdf")
    if shutil.which("pdftoppm") is None:
        pytest.skip("pdftoppm not installed")
    path = make_pdf(tmp_path / "a.pdf", [INSTRUCTIONS_PAGE_1, None])
    ocr = FakeOcr({"page-0002.png": [line("Alert count: 4"), line("blurry", 0.4)]})
    result = documents.extract_pdf(path, path.read_bytes(), cache_dir=tmp_path / "cache", ocr=ocr)
    ocr_items = [i for i in result.items if i["kind"] == "ocr"]
    assert len(ocr_items) == 1 and ocr_items[0]["locator"]["page"] == 2
    assert "OCR" in ocr_items[0]["location"]
    assert ocr_items[0]["limitations"]


def test_corrupt_and_encrypted_pdfs(tmp_path):
    pytest.importorskip("pypdf")
    result = documents.extract_pdf(tmp_path / "x.pdf", b"%PDF-1.4 nonsense", cache_dir=None)
    assert result.status == "failed" and not result.items


def test_docx_sections(tmp_path):
    path = make_docx(
        tmp_path / "r.docx",
        [
            ("Heading1", "Setup"),
            ("", "Install Suricata 7."),
            ("Heading2", "Rules"),
            ("", "Use tls.sni in the rule."),
        ],
    )
    result = documents.extract_text_document(path, path.read_bytes())
    locations = [i["location"] for i in result.items]
    assert "section “Setup”" in locations and "section “Rules”" in locations
    rules = next(i for i in result.items if i["locator"]["section"] == "Rules")
    assert "tls.sni" in rules["excerpt"]


def test_markdown_and_html(tmp_path):
    md = tmp_path / "n.md"
    md.write_text("# Intro\n\nHello there.\n\n## Method\n\nWe captured 12 packets.\n", encoding="utf-8")
    result = documents.extract_text_document(md, md.read_bytes())
    assert [i["locator"]["section"] for i in result.items] == ["Intro", "Method"]
    html = tmp_path / "p.html"
    html.write_text("<html><body><script>alert(1)</script><p>Plain fact.</p></body></html>", encoding="utf-8")
    result = documents.extract_text_document(html, html.read_bytes())
    text = " ".join(i["excerpt"] for i in result.items)
    assert "Plain fact." in text and "alert(1)" not in text


# --- images -------------------------------------------------------------------


def test_screenshot_ocr_preserves_regions_and_uncertainty(tmp_path):
    path = make_png(tmp_path / "alerts.png", 300, 120)
    ocr = FakeOcr(
        {
            "alerts.png": [
                line("ET POLICY TLS SNI lab.example.test", 0.97, (5, 5, 280, 25)),
                line("sid 1000001", 0.92, (5, 30, 120, 50)),
                line("smudge", 0.5),
            ]
        }
    )
    result = extract_image(path, path.read_bytes(), ocr=ocr)
    item = result.items[0]
    assert item["kind"] == "ocr" and item["observation"]["width"] == 300
    assert item["observation"]["lines"][0]["box"] == [5, 5, 280, 25]
    assert "smudge" not in item["excerpt"]
    assert any("uncertain" in limit for limit in item["limitations"])


def test_screenshot_without_ocr_is_inventoried_not_read(tmp_path):
    path = make_png(tmp_path / "a.png")
    result = extract_image(path, path.read_bytes(), ocr=Off())
    assert result.status == "partial" and not result.items and "not read" in result.reason


def test_screenshot_ocr_timeout_is_a_failure(tmp_path):
    path = make_png(tmp_path / "slow.png")
    result = extract_image(path, path.read_bytes(), ocr=FakeOcr(fail={"slow.png"}))
    assert result.status == "failed" and "OCR stopped" in result.reason


def test_blank_screenshot_reports_no_text(tmp_path):
    path = make_png(tmp_path / "blank.png")
    result = extract_image(path, path.read_bytes(), ocr=FakeOcr())
    assert result.items[0]["observation"]["text_found"] is False


def test_image_dimensions_from_headers(tmp_path):
    assert images.dimensions(make_png(tmp_path / "d.png", 7, 9).read_bytes()) == (7, 9)
    assert images.dimensions(b"not an image") is None


def test_real_ocr_engine_reads_rendered_text(tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    pil = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw, ImageFont

    image = pil.new("RGB", (640, 120), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=36)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((10, 30), "ALERT TLS SNI 1000001", fill="black", font=font)
    path = tmp_path / "text.png"
    image.save(path)
    engine = OcrEngine()
    try:
        lines = engine.read(path)
    finally:
        engine.close()
    assert any("1000001" in entry["text"] for entry in lines)


# --- packet captures -------------------------------------------------------------


def test_dpkt_fallback_cites_frames(tmp_path):
    pytest.importorskip("dpkt")
    path = make_pcap(tmp_path / "c.pcap")
    result = pcap._analyze_dpkt(path)
    summary = result.items[0]
    assert summary["kind"] == "packet_summary" and summary["observation"]["frames"] == 13
    assert summary["location"] == "frames 1–13"
    dns = [i for i in result.items if i["kind"] == "dns"]
    assert dns and dns[0]["observation"]["query"] == "lab.example.test"
    assert any("limited" in w for w in result.warnings)


def _tshark():
    engine = pcap.TShark()
    if not engine.available:
        pytest.skip("TShark not installed")
    return engine


def test_tshark_tls_handshake_and_payload_visibility(tmp_path):
    pytest.importorskip("dpkt")
    path = make_pcap(tmp_path / "c.pcap")
    result = pcap.analyze(path, tshark=_tshark())
    tls = [i for i in result.items if i["kind"] == "tls_handshake"]
    assert len(tls) == 1
    observation = tls[0]["observation"]
    assert observation["sni"] == "lab.example.test" and observation["negotiated_version"] == "TLS 1.3"
    assert "not visible" in observation["certificate"]
    assert re.fullmatch(r"frames \d+–\d+", tls[0]["location"])
    assert any("not decrypted" in limit for limit in tls[0]["limitations"])
    visibility = {
        i["observation"]["tcp_stream"]: i["observation"]["assessment"]
        for i in result.items
        if i["kind"] == "payload_visibility"
    }
    assert visibility["0"].startswith("high-entropy") and visibility["1"].startswith("cleartext")


def test_tshark_redacts_query_strings_and_stores_no_payload(tmp_path):
    pytest.importorskip("dpkt")
    path = make_pcap(tmp_path / "c.pcap")
    result = pcap.analyze(path, tshark=_tshark())
    blob = repr(result.items) + repr(result.metadata)
    assert "SECRET123" not in blob and "[query redacted]" in blob


def test_capture_comparison_is_derived_from_packets(tmp_path):
    pytest.importorskip("dpkt")
    engine = _tshark()
    before = pcap.analyze(make_pcap(tmp_path / "a.pcap", tls13=False, http=False), tshark=engine).items
    after = pcap.analyze(make_pcap(tmp_path / "b.pcap", tls13=True, http=False), tshark=engine).items
    findings = pcap.compare(before, after, before_name="a.pcap", after_name="b.pcap")
    tls = next(f for f in findings if f["aspect"] == "TLS")
    assert tls["before"]["versions"] == ["TLS 1.2"] and tls["after"]["versions"] == ["TLS 1.3"]


def test_corrupt_capture_fails_cleanly(tmp_path):
    pytest.importorskip("dpkt")
    path = tmp_path / "bad.pcap"
    path.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 3)
    result = pcap.analyze(path, tshark=type("NoTShark", (), {"available": False})())
    assert result.status == "failed"


# --- video and audio -----------------------------------------------------------


def _ffmpeg():
    exe = media.ffmpeg_exe()
    if exe is None:
        pytest.skip("ffmpeg not available")
    return exe


class FakeTranscriber:
    available = True
    name = "fake-whisper"
    policy = None

    def __init__(self, segments):
        self.segments = segments
        self.calls = 0

    def transcribe(self, audio, timeout=None):
        self.calls += 1
        assert Path(audio).stat().st_size > 0
        return self.segments


def _video(tmp_path, audio: bool) -> Path:
    exe = _ffmpeg()
    out = tmp_path / ("talk.mp4" if audio else "silent.mp4")
    command = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=5",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440"]
    command += ["-t", "65", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast"]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    try:
        subprocess.run(command + [str(out)], check=True, capture_output=True, timeout=120)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg build cannot synthesize test video")
    return out


def test_video_transcript_has_timestamps_and_is_cached(tmp_path):
    path = _video(tmp_path, audio=True)
    transcriber = FakeTranscriber(
        [
            {
                "start": 3.2,
                "end": 7.9,
                "text": "Start the capture on the sensor.",
                "no_speech_prob": 0.01,
                "avg_logprob": -0.2,
            },
            {
                "start": 63.0,
                "end": 64.5,
                "text": "Two alerts fire.",
                "no_speech_prob": 0.02,
                "avg_logprob": -0.3,
            },
        ]
    )
    ocr = FakeOcr({"frame-0001.png": [line("Suricata"), line("eve.json"), line("alert")]})
    result = media.extract_media(
        path, sha256="ab" * 32, cache_dir=tmp_path / "cache", transcriber=transcriber, ocr=ocr
    )
    transcripts = [i for i in result.items if i["kind"] == "transcript"]
    assert [t["location"] for t in transcripts] == ["00:03–00:07", "01:03–01:04"]
    frames = [i for i in result.items if i["kind"] == "frame"]
    assert frames and frames[0]["location"] == "frame at 00:00"
    again = media.extract_media(
        path, sha256="ab" * 32, cache_dir=tmp_path / "cache", transcriber=transcriber, ocr=ocr
    )
    assert transcriber.calls == 1 and again.metadata.get("transcript_cached")


def test_silent_video_is_not_claimed_as_understood(tmp_path):
    path = _video(tmp_path, audio=False)
    transcriber = FakeTranscriber([])
    result = media.extract_media(
        path, sha256="cd" * 32, cache_dir=tmp_path / "cache", transcriber=transcriber, ocr=FakeOcr()
    )
    assert transcriber.calls == 0
    assert any("no audio stream" in w for w in result.warnings)
    assert any("visual content is not described" in w for w in result.warnings)
    assert result.status == "partial"


def test_unreadable_media_fails(tmp_path):
    _ffmpeg()
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"not a video at all")
    result = media.extract_media(
        path, sha256="ef" * 32, cache_dir=tmp_path / "c", transcriber=Off(), ocr=Off()
    )
    assert result.status == "failed"
