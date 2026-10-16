"""Screenshots and images: the original is the evidence; OCR is a reading of it.

Text is read with a local OCR engine (RapidOCR on ONNX Runtime, CPU, models
bundled with the package). Each line keeps its bounding box and confidence,
so evidence can point at the region of the image it came from, and lines
below the confidence floor are kept but marked uncertain rather than
presented as what the screenshot says.

Describing what an image *shows* (a chart's trend, an alert's colour) needs a
vision model. That is never done here; it is a separate, explicitly
authorized step. Without OCR the image is still inventoried, with its
dimensions, and reported as visual content that was not read.
"""

from __future__ import annotations

from pathlib import Path
import struct

from howlwriter.projects.adapters import AdapterResult

LOW_CONFIDENCE = 0.75
MAX_IMAGE_PIXELS = 60_000_000


class OcrFailed(RuntimeError):
    pass


class OcrEngine:
    """Local OCR (RapidOCR) run in the governed worker process.

    `available` is checked without importing the engine, so a scan that never
    meets an image never loads ONNX Runtime. `read` raises `OcrFailed` when a
    job times out or crashes; an image with no text returns an empty list.
    """

    name = "rapidocr-onnxruntime"

    def __init__(self, worker=None, policy=None) -> None:
        import importlib.util

        self.available = importlib.util.find_spec("rapidocr_onnxruntime") is not None
        self._worker = worker
        self._policy = policy

    @property
    def worker(self):
        if self._worker is None:
            from howlwriter.projects.resources import HeavyWorker

            self._worker = HeavyWorker(self._policy)
        return self._worker

    def read(self, image: Path) -> list[dict]:
        if not self.available:
            return []
        try:
            return self.worker.run("ocr", str(image))
        except Exception as error:
            raise OcrFailed(str(error)) from error

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()


_ENGINE: OcrEngine | None = None


def default_ocr() -> OcrEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = OcrEngine()
    return _ENGINE


def dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height from PNG/JPEG/GIF headers without decoding pixels."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + length
    return None


def extract_image(path: Path, data: bytes, *, ocr: OcrEngine | None = None) -> AdapterResult:
    size = dimensions(data)
    result = AdapterResult(
        method="image-metadata", metadata={"width": size[0], "height": size[1]} if size else {}
    )
    if size and size[0] * size[1] > MAX_IMAGE_PIXELS:
        result.status = "partial"
        result.warnings.append("image too large for OCR; inventoried only")
        return result
    engine = ocr or default_ocr()
    if not engine.available:
        result.status = "partial"
        result.reason = (
            "no local OCR engine installed (pip install 'howlwriter[sources]'); the image was not read"
        )
        return result
    try:
        lines = engine.read(path)
    except OcrFailed as error:
        result.status = "failed"
        result.reason = f"OCR stopped: {error}"
        return result
    result.method = engine.name
    if not lines:
        result.warnings.append("no text was found in the image")
        result.items.append(
            {
                "kind": "image",
                "source_type": "image",
                "method": engine.name,
                "status": "directly_observed",
                "location": "whole image",
                "locator": {"region": "full"},
                "excerpt": "",
                "observation": {"text_found": False, **result.metadata},
                "confidence": "high",
                "limitations": ["no visible text detected; visual content not described"],
            }
        )
        return result
    certain = [line for line in lines if not line["uncertain"]]
    mean = sum(line["score"] for line in lines) / len(lines)
    result.text = "\n".join(line["text"] for line in lines)
    result.items.append(
        {
            "kind": "ocr",
            "source_type": "image",
            "method": engine.name,
            "status": "extracted_from_source",
            "location": "whole image (OCR)",
            "locator": {"region": "full", "lines": len(lines)},
            "excerpt": " ".join(line["text"] for line in certain)[:900],
            "observation": {"lines": lines[:300], **result.metadata},
            "confidence": "high" if mean >= 0.9 else "medium" if mean >= LOW_CONFIDENCE else "low",
            "limitations": (
                [
                    f"{len(lines) - len(certain)} line(s) below {LOW_CONFIDENCE} confidence "
                    "are marked uncertain"
                ]
                if len(certain) < len(lines)
                else []
            )
            + ["OCR reads text only; layout, colours and non-text content are not described"],
        }
    )
    return result
