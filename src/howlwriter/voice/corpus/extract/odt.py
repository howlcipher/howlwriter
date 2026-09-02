"""ODT extraction using only the standard library.

Structurally the same story as DOCX: an OpenDocument text file is a zip whose
`content.xml` holds the body, so `zipfile` plus `xml.etree` is enough and
nothing embedded is ever executed.
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

_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"

_HEADING_LEVEL = f"{_TEXT_NS}outline-level"
_PARA = f"{_TEXT_NS}p"
_HEAD = f"{_TEXT_NS}h"
_LIST = f"{_TEXT_NS}list"


def _node_text(node: ET.Element) -> str:
    """All descendant text of a paragraph or heading, in document order."""
    return "".join(node.itertext())


def extract_odt(path: Path) -> ExtractionResult:
    raw, failure = read_bytes(path)
    if failure is not None:
        failure.parser = "odt"
        return failure

    try:
        with zipfile.ZipFile(path) as archive:
            if "content.xml" not in archive.namelist():
                return ExtractionResult(
                    parser="odt", status=STATUS_FAILED,
                    reason="archive has no content.xml body part",
                )
            content = archive.read("content.xml")
        root = ET.fromstring(content)
    except (zipfile.BadZipFile, KeyError) as error:
        return ExtractionResult(
            parser="odt", status=STATUS_FAILED,
            reason=f"not a readable odt archive: {error}",
        )
    except ET.ParseError as error:
        return ExtractionResult(
            parser="odt", status=STATUS_FAILED,
            reason=f"content.xml is not well-formed XML: {error}",
        )

    # Paragraphs inside a list get a marker so list frequency survives.
    in_list: set[ET.Element] = set()
    for list_node in root.iter(_LIST):
        for paragraph in list_node.iter(_PARA):
            in_list.add(paragraph)

    blocks: list[str] = []
    for node in root.iter():
        if node.tag == _HEAD:
            text = _node_text(node).strip()
            if text:
                level = node.get(_HEADING_LEVEL) or "1"
                depth = min(6, max(1, int(level) if level.isdigit() else 1))
                blocks.append("#" * depth + " " + text)
        elif node.tag == _PARA:
            text = _node_text(node).strip()
            if text:
                blocks.append(("- " if node in in_list else "") + text)

    if not blocks:
        return ExtractionResult(
            parser="odt", status=STATUS_EMPTY,
            reason="document body contained no text",
        )
    text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(blocks))
    return ExtractionResult(text=text, parser="odt", status=STATUS_OK)
