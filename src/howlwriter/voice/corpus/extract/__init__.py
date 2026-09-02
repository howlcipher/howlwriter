"""Stage 2: pull plain prose out of a document file, safely.

Every parser here obeys the same three rules.

Nothing is executed. A .docx is a zip of XML and is read as one; macros,
embedded objects, and external references are never evaluated, and no office
application is launched. A document is data.

Nothing is written. Files are opened in binary read mode. No converted copy
is saved beside the original, no temporary file is created in the source
directory, and no timestamp is touched.

Failure is reported, not guessed at. A scanned PDF with no text layer, a
legacy .doc, and a Google Docs placeholder that the filesystem refuses to
read are three different outcomes with three different reasons, and each is
counted honestly in the corpus report rather than silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Extraction outcomes. Only OK carries usable text.
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNSUPPORTED = "unsupported_format"
STATUS_UNAVAILABLE = "extraction_unavailable"
STATUS_SCANNED = "scanned_no_text_layer"
STATUS_FAILED = "extraction_failed"


@dataclass
class ExtractionResult:
    """The text of one document, or an honest account of why there is none."""

    text: str = ""
    parser: str = ""
    status: str = STATUS_FAILED
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and bool(self.text.strip())


def extract(path: Path) -> ExtractionResult:
    """Dispatch to the parser for this file's suffix.

    Imports are deferred so that a missing optional dependency (pypdf) only
    affects PDFs, and so importing this package stays cheap.
    """
    suffix = path.suffix.lower()

    if suffix in (".txt", ".text", ".md", ".markdown"):
        from howlwriter.voice.corpus.extract.plain import extract_plain
        return extract_plain(path)
    if suffix == ".docx":
        from howlwriter.voice.corpus.extract.docx import extract_docx
        return extract_docx(path)
    if suffix == ".odt":
        from howlwriter.voice.corpus.extract.odt import extract_odt
        return extract_odt(path)
    if suffix == ".rtf":
        from howlwriter.voice.corpus.extract.rtf import extract_rtf
        return extract_rtf(path)
    if suffix in (".html", ".htm"):
        from howlwriter.voice.corpus.extract.html import extract_html
        return extract_html(path)
    if suffix == ".pdf":
        from howlwriter.voice.corpus.extract.pdf import extract_pdf
        return extract_pdf(path)
    if suffix == ".doc":
        return ExtractionResult(
            parser="none",
            status=STATUS_UNSUPPORTED,
            reason="legacy binary .doc format is not parsed; re-save as .docx to include it",
        )
    return ExtractionResult(
        parser="none",
        status=STATUS_UNSUPPORTED,
        reason=f"no parser for {suffix or 'extensionless file'}",
    )


def read_bytes(path: Path) -> tuple[bytes | None, ExtractionResult | None]:
    """Read a file read-only, converting the usual failures into results.

    A cloud-drive placeholder for a file whose content lives server side
    raises PermissionError or OSError here. That is a real, reportable state
    ("the filesystem will not give us the bytes"), not a parse failure, so it
    is distinguished from a document we read but could not understand.
    """
    try:
        return path.read_bytes(), None
    except PermissionError:
        return None, ExtractionResult(
            parser="none",
            status=STATUS_UNAVAILABLE,
            reason="filesystem denied read access (cloud placeholder or restricted file)",
        )
    except OSError as error:
        return None, ExtractionResult(
            parser="none",
            status=STATUS_UNAVAILABLE,
            reason=f"filesystem could not supply the file contents: {error.strerror or error}",
        )
