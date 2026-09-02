"""Plain text and Markdown extraction.

The simplest parser, but not a no-op: the bytes still have to be decoded
without guessing wildly, and a file that is really a log or a data dump
wearing a .txt suffix should not be handed on as prose.
"""

from __future__ import annotations

from pathlib import Path

from howlwriter.voice.corpus.extract import (
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_OK,
    ExtractionResult,
    read_bytes,
)

#: Tried in order. UTF-8 covers almost everything; the fallbacks cover files
#: exported by older Windows tooling. Latin-1 never fails, so it terminates
#: the chain rather than leaving us with an undecodable file.
_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


def decode_text(raw: bytes) -> str | None:
    """Decode bytes as text, or None if this is really binary content."""
    if b"\x00" in raw[:8192]:
        return None
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def extract_plain(path: Path) -> ExtractionResult:
    raw, failure = read_bytes(path)
    if failure is not None:
        failure.parser = "plain"
        return failure

    text = decode_text(raw or b"")
    if text is None:
        return ExtractionResult(
            parser="plain", status=STATUS_FAILED,
            reason="file contains binary data despite a text extension",
        )
    if not text.strip():
        return ExtractionResult(
            parser="plain", status=STATUS_EMPTY, reason="file is empty or whitespace only",
        )
    return ExtractionResult(text=text, parser="plain", status=STATUS_OK)
