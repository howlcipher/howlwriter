"""DOCX extraction using only the standard library.

A .docx is a zip archive whose `word/document.xml` holds the body. Reading it
with `zipfile` and `xml.etree` means no macro, embedded object, or external
reference is ever evaluated -- the archive is treated as inert data, which is
the whole point when the corpus is a stranger's document collection.

Structure that matters to voice is preserved: paragraphs become blank-line
separated blocks, list items keep a marker so list frequency stays
measurable, and headings keep their `#` prefix so heading rate can be counted
later. Everything else (styling, revision marks, comments) is dropped.
"""

from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from howlwriter.voice.corpus.extract import (
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_OK,
    ExtractionResult,
    read_bytes,
)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: Word writes heading levels as style ids like "Heading1"/"berschrift1".
_HEADING_STYLE = re.compile(r"heading\s*([1-6])", re.IGNORECASE)


def _paragraph_text(paragraph: ET.Element) -> str:
    """Concatenate the runs of one paragraph, honouring explicit breaks."""
    pieces: list[str] = []
    for node in paragraph.iter():
        tag = node.tag
        if tag == f"{_W}t":
            pieces.append(node.text or "")
        elif tag == f"{_W}tab":
            pieces.append("\t")
        elif tag == f"{_W}br":
            pieces.append("\n")
    return "".join(pieces)


def _paragraph_prefix(paragraph: ET.Element) -> str:
    """Return a markdown prefix so headings and list items stay identifiable.

    Heading and list frequency are real style signals, so they must survive
    extraction. Recovering them from the paragraph properties is more
    reliable than trying to infer them from the text afterwards.
    """
    props = paragraph.find(f"{_W}pPr")
    if props is None:
        return ""
    style = props.find(f"{_W}pStyle")
    if style is not None:
        value = style.get(f"{_W}val") or ""
        match = _HEADING_STYLE.search(value)
        if match:
            return "#" * min(6, int(match.group(1))) + " "
        if value.lower().startswith(("title", "subtitle")):
            return "# "
    if props.find(f"{_W}numPr") is not None:
        return "- "
    return ""


def extract_docx(path: Path) -> ExtractionResult:
    raw, failure = read_bytes(path)
    if failure is not None:
        failure.parser = "docx"
        return failure

    try:
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                return ExtractionResult(
                    parser="docx",
                    status=STATUS_FAILED,
                    reason="archive has no word/document.xml body part",
                )
            body_xml = archive.read("word/document.xml")
        root = ET.fromstring(body_xml)
    except (zipfile.BadZipFile, KeyError) as error:
        return ExtractionResult(
            parser="docx", status=STATUS_FAILED,
            reason=f"not a readable docx archive: {error}",
        )
    except ET.ParseError as error:
        return ExtractionResult(
            parser="docx", status=STATUS_FAILED,
            reason=f"document body is not well-formed XML: {error}",
        )

    blocks: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        text = _paragraph_text(paragraph).strip()
        if not text:
            continue
        blocks.append(_paragraph_prefix(paragraph) + text)

    if not blocks:
        return ExtractionResult(
            parser="docx", status=STATUS_EMPTY,
            reason="document body contained no text runs",
        )
    return ExtractionResult(text="\n\n".join(blocks), parser="docx", status=STATUS_OK)
