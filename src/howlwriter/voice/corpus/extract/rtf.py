"""RTF extraction by stripping control words.

RTF is a plain-text markup format, so this is a tokenizer rather than a
parser: control words are consumed, groups the spec marks as ignorable
(`\\*\\...`) are skipped whole, and what is left is the visible text.

Deliberately approximate. RTF can express things this will not reconstruct
perfectly, but voice profiling needs sentences and paragraphs rather than
faithful formatting, and being approximate here is much better than shelling
out to an office suite to open a file we do not trust.
"""

from __future__ import annotations

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

#: Control words that produce a paragraph or line break in the output.
_BREAK_WORDS = {"par", "line", "page", "sect"}

#: Groups whose entire contents are metadata, not body text.
_SKIP_GROUPS = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object",
    "themedata", "colorschememapping", "latentstyles", "datastore",
    "generator", "listtable", "listoverridetable", "rsidtbl", "xmlnstbl",
}

_CONTROL = re.compile(r"\\([a-zA-Z]+)(-?\d+)?[ ]?|\\([^a-zA-Z])|([{}])|([^\\{}]+)")


def _rtf_to_text(source: str) -> str:
    out: list[str] = []
    depth = 0
    skip_until_depth: int | None = None
    unicode_skip = 0

    for match in _CONTROL.finditer(source):
        word, _arg, symbol, brace, literal = match.groups()

        if brace == "{":
            depth += 1
            continue
        if brace == "}":
            depth -= 1
            if skip_until_depth is not None and depth < skip_until_depth:
                skip_until_depth = None
            continue

        if skip_until_depth is not None:
            continue

        if word is not None:
            if word in _SKIP_GROUPS:
                skip_until_depth = depth
                continue
            if word in _BREAK_WORDS:
                out.append("\n")
            elif word == "tab":
                out.append("\t")
            elif word == "u":
                # \uN produces one character; the following fallback char is
                # skipped so it does not appear twice.
                arg = match.group(2)
                if arg is not None:
                    try:
                        out.append(chr(int(arg) % 0x10000))
                    except (ValueError, OverflowError):
                        pass
                unicode_skip = 1
            continue

        if symbol is not None:
            if symbol == "*":
                skip_until_depth = depth
            elif symbol in ("\\", "{", "}"):
                out.append(symbol)
            elif symbol == "~":
                out.append(" ")
            continue

        if literal is not None:
            if unicode_skip:
                literal = literal[unicode_skip:]
                unicode_skip = 0
            out.append(literal)

    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def extract_rtf(path: Path) -> ExtractionResult:
    raw, failure = read_bytes(path)
    if failure is not None:
        failure.parser = "rtf"
        return failure

    source = decode_text(raw or b"")
    if source is None:
        return ExtractionResult(
            parser="rtf", status=STATUS_FAILED,
            reason="file contains binary data despite an rtf extension",
        )
    if not source.lstrip().startswith("{\\rt"):
        return ExtractionResult(
            parser="rtf", status=STATUS_FAILED, reason="missing RTF header",
        )

    text = _rtf_to_text(source)
    if not text.strip():
        return ExtractionResult(
            parser="rtf", status=STATUS_EMPTY, reason="document contained no body text",
        )
    return ExtractionResult(text=text, parser="rtf", status=STATUS_OK)
