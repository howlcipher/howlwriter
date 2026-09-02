"""HTML extraction with the standard library's HTMLParser.

`html.parser` is a pure tokenizer: it does not fetch linked resources, does
not evaluate script or style content, and has no DOM to be manipulated. That
makes it the right tool for reading a saved web page or an exported document
out of someone's drive without the file getting a say in what happens next.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re

from howlwriter.voice.corpus.extract import (
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_OK,
    ExtractionResult,
    read_bytes,
)
from howlwriter.voice.corpus.extract.plain import decode_text

#: Elements whose text is never prose the author wrote.
_DROP_CONTENT = {"script", "style", "noscript", "template", "svg", "head"}

#: Elements that end a paragraph-level block.
_BLOCK = {
    "p", "div", "section", "article", "br", "tr", "table", "blockquote",
    "pre", "figure", "figcaption", "header", "footer", "main", "aside",
}

_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class _ProseParser(HTMLParser):
    """Collect visible text as markdown-ish blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._buffer: list[str] = []
        self._suppress_depth = 0
        self._pending_prefix = ""

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer.clear()
        if text:
            self.blocks.append(self._pending_prefix + text)
        self._pending_prefix = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _DROP_CONTENT:
            self._suppress_depth += 1
            return
        if self._suppress_depth:
            return
        if tag in _HEADINGS:
            self._flush()
            self._pending_prefix = "#" * _HEADINGS[tag] + " "
        elif tag == "li":
            self._flush()
            self._pending_prefix = "- "
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self._suppress_depth = max(0, self._suppress_depth - 1)
            return
        if self._suppress_depth:
            return
        if tag in _BLOCK or tag in _HEADINGS or tag == "li":
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._suppress_depth:
            self._buffer.append(data)

    def close(self) -> None:  # noqa: A003 - HTMLParser API
        super().close()
        self._flush()


def extract_html(path: Path) -> ExtractionResult:
    raw, failure = read_bytes(path)
    if failure is not None:
        failure.parser = "html"
        return failure

    source = decode_text(raw or b"")
    if source is None:
        return ExtractionResult(
            parser="html", status=STATUS_FAILED,
            reason="file contains binary data despite an html extension",
        )

    parser = _ProseParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as error:  # malformed markup should not abort a build
        return ExtractionResult(
            parser="html", status=STATUS_FAILED, reason=f"could not parse markup: {error}",
        )

    if not parser.blocks:
        return ExtractionResult(
            parser="html", status=STATUS_EMPTY, reason="document contained no visible text",
        )
    return ExtractionResult(
        text="\n\n".join(parser.blocks), parser="html", status=STATUS_OK,
    )
