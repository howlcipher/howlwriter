"""Documents: PDF per page; DOCX, ODT, RTF, HTML, TXT, MD by section.

PDFs are read page by page so a citation can name the page. A page that
carries images but almost no extractable text (a screenshot pasted into the
PDF, a scanned page) is flagged, and when the local OCR engine is available
it is rendered and read; otherwise it is reported as visual content that was
not read. Text is never guessed for a page that could not be read.

Other formats go through the corpus extractors (stdlib parsing, bounded
archive reads, no macros) and are located by heading section.
"""

from __future__ import annotations

import io
from pathlib import Path
import re
import shutil
import subprocess

from howlwriter.projects.adapters import AdapterResult
from howlwriter.projects.resources import governed_run

EXCERPT_CHARS = 900
CHUNK_WORDS = 140
#: A page with fewer characters than this but with images is visual content.
VISUAL_PAGE_CHARS = 60
MAX_PDF_PAGES = 400
MAX_OCR_PAGES = 30
_HEADING = re.compile(r"^\s*#{1,6}\s+(.+)$")


def _chunks(text: str, words: int = CHUNK_WORDS) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    current: list[str] = []
    count = 0
    for paragraph in paragraphs:
        n = len(paragraph.split())
        if current and count + n > words:
            out.append("\n\n".join(current))
            current, count = [], 0
        current.append(paragraph)
        count += n
    if current:
        out.append("\n\n".join(current))
    return out


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1] + "…"


def extract_pdf(path: Path, data: bytes, *, cache_dir: Path | None, ocr=None) -> AdapterResult:
    result = AdapterResult(method="pypdf-page-text")
    try:
        import pypdf
    except ImportError:
        return AdapterResult(
            status="unavailable", reason="pypdf is not installed (pip install 'howlwriter[corpus]')"
        )
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            try:
                if reader.decrypt("") == 0:
                    return AdapterResult(status="unavailable", reason="PDF is password protected")
            except Exception:
                return AdapterResult(status="unavailable", reason="PDF is encrypted")
        pages = reader.pages
        if len(pages) > MAX_PDF_PAGES:
            return AdapterResult(
                status="failed", reason=f"{len(pages)} pages exceeds the {MAX_PDF_PAGES}-page limit"
            )
        title = ""
        try:
            title = str((reader.metadata or {}).get("/Title", "") or "")
        except Exception:
            title = ""
        result.metadata = {"pages": len(pages), "title": title[:200]}
    except Exception as error:
        return AdapterResult(status="failed", reason=f"unreadable PDF structure ({type(error).__name__})")

    texts: list[str] = []
    visual_pages: list[int] = []
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
            result.warnings.append(f"page {number}: text extraction failed")
        try:
            image_count = len(page.images)
        except Exception:
            image_count = 0
        if len(text.strip()) < VISUAL_PAGE_CHARS and image_count:
            visual_pages.append(number)
        if image_count and len(text.strip()) >= VISUAL_PAGE_CHARS:
            result.metadata.setdefault("pages_with_images", []).append(number)
        texts.append(text)
        for index, chunk in enumerate(_chunks(text)):
            result.items.append(
                {
                    "kind": "text",
                    "source_type": "pdf",
                    "method": "pypdf-page-text",
                    "status": "extracted_from_source",
                    "location": f"page {number}",
                    "locator": {"page": number, "chunk": index},
                    "excerpt": _excerpt(chunk),
                    "observation": {"text": chunk},
                    "confidence": "high",
                }
            )
    result.text = "\n\n".join(texts)
    result.metadata["visual_pages"] = visual_pages[:200]
    if visual_pages:
        ocr_done = _ocr_pages(path, visual_pages[:MAX_OCR_PAGES], cache_dir, ocr, result)
        unread = [p for p in visual_pages if p not in ocr_done]
        if unread:
            result.warnings.append(
                f"{len(unread)} page(s) are mostly images and were not read: pages "
                + ", ".join(str(p) for p in unread[:20])
            )
            result.status = "partial"
    pages_with_images = result.metadata.get("pages_with_images", [])
    if pages_with_images:
        result.warnings.append(
            f"{len(pages_with_images)} page(s) also contain images (screenshots or figures) whose "
            "content is not in the extracted text"
        )
    if not result.items and not visual_pages:
        return AdapterResult(status="failed", reason="no text layer", metadata=result.metadata)
    return result


def _ocr_pages(path: Path, pages: list[int], cache_dir: Path | None, ocr, result: AdapterResult) -> list[int]:
    if ocr is None or cache_dir is None or shutil.which("pdftoppm") is None:
        if pages:
            result.warnings.append("visual pages need OCR, but no OCR engine or pdftoppm is available")
        return []
    done: list[int] = []
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for number in pages:
        target = cache_dir / f"page-{number:04d}"
        try:
            governed_run(
                [
                    "pdftoppm",
                    "-f",
                    str(number),
                    "-l",
                    str(number),
                    "-r",
                    "150",
                    "-png",
                    "-singlefile",
                    str(path),
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        image = target.with_suffix(".png")
        try:
            lines = ocr.read(image)
        except Exception as error:
            result.warnings.append(f"page {number}: OCR stopped ({str(error)[:80]})")
            continue
        done.append(number)
        if lines:
            result.items.append(
                {
                    "kind": "ocr",
                    "source_type": "pdf",
                    "method": f"pdftoppm+{ocr.name}",
                    "status": "extracted_from_source",
                    "location": f"page {number} (image content, OCR)",
                    "locator": {"page": number, "rendered": image.name},
                    "excerpt": _excerpt(" ".join(line["text"] for line in lines)),
                    "observation": {"lines": lines[:200]},
                    "confidence": _band(lines),
                    "limitations": ["text read by OCR from an image; verify against the page"],
                }
            )
            result.text += "\n\n" + "\n".join(line["text"] for line in lines)
    return done


def _band(lines: list[dict]) -> str:
    if not lines:
        return "low"
    mean = sum(line.get("score", 0.0) for line in lines) / len(lines)
    return "high" if mean >= 0.9 else "medium" if mean >= 0.75 else "low"


def extract_text_document(path: Path, data: bytes) -> AdapterResult:
    from howlwriter.voice.corpus.extract import extract

    extraction = extract(path, data)
    if not extraction.ok:
        return AdapterResult(
            status="failed" if extraction.status != "extraction_unavailable" else "unavailable",
            reason=extraction.reason or extraction.status,
        )
    result = AdapterResult(method=f"{extraction.parser}-sections")
    result.text = extraction.text
    section = "start of document"
    buffer: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal index
        text = "\n\n".join(buffer).strip()
        if not text:
            return
        for chunk in _chunks(text):
            index += 1
            result.items.append(
                {
                    "kind": "text",
                    "source_type": path.suffix.lower().lstrip(".") or "text",
                    "method": result.method,
                    "status": "extracted_from_source",
                    "location": (
                        f"section “{section[:80]}”" if section != "start of document" else "start of document"
                    ),
                    "locator": {"section": section[:200], "chunk": index},
                    "excerpt": _excerpt(chunk),
                    "observation": {"text": chunk},
                    "confidence": "high",
                }
            )

    for block in re.split(r"\n\s*\n", extraction.text):
        heading = _HEADING.match(block.strip().splitlines()[0]) if block.strip() else None
        if heading:
            flush()
            buffer = []
            section = heading.group(1).strip()
            rest = "\n".join(block.strip().splitlines()[1:])
            if rest.strip():
                buffer.append(rest)
        else:
            buffer.append(block)
    flush()
    return result
