"""PDF text extraction through the optional `pypdf` dependency.

PDF is the one format where a competent stdlib parser is not realistic --
content streams, font encodings, and CID mappings are a real problem, not an
afternoon's regex. So `pypdf` is an optional extra (`pip install
howlwriter[corpus]`) and its absence is reported rather than worked around.

Only the embedded text layer is read. There is no OCR here and none is
planned: rasterising a drive's worth of scanned documents is expensive, slow,
and produces exactly the kind of noisy text that would corrupt a voice
profile. A scanned PDF is reported as scanned and excluded, which is the
honest outcome.
"""

from __future__ import annotations

from pathlib import Path
import re

from howlwriter.voice.corpus.extract import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SCANNED,
    STATUS_UNAVAILABLE,
    ExtractionResult,
    read_bytes,
)

#: Below this many extracted characters a PDF is treated as having no real
#: text layer. A scanned page often yields a few stray characters from a
#: header stamp, so zero is too strict a threshold to be useful.
_MIN_TEXT_LAYER_CHARS = 200

_INSTALL_HINT = (
    "PDF extraction needs the optional 'corpus' extra: pip install 'howlwriter[corpus]'"
)


def pypdf_available() -> bool:
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return False


def extract_pdf(path: Path) -> ExtractionResult:
    try:
        import pypdf
    except ImportError:
        return ExtractionResult(
            parser="pdf", status=STATUS_UNAVAILABLE, reason=_INSTALL_HINT,
        )

    raw, failure = read_bytes(path)
    if failure is not None:
        failure.parser = "pdf"
        return failure

    try:
        reader = pypdf.PdfReader(path)
        if getattr(reader, "is_encrypted", False):
            # An empty user password is common and harmless to try; a real
            # one means the document is not ours to open.
            try:
                if reader.decrypt("") == 0:
                    return ExtractionResult(
                        parser="pdf", status=STATUS_UNAVAILABLE,
                        reason="document is password protected",
                    )
            except Exception:
                return ExtractionResult(
                    parser="pdf", status=STATUS_UNAVAILABLE,
                    reason="document is encrypted and could not be opened",
                )
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as error:
        return ExtractionResult(
            parser="pdf", status=STATUS_FAILED,
            reason=f"could not read the PDF structure: {type(error).__name__}: {error}",
        )

    text = "\n\n".join(p.strip() for p in pages if p.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text.strip()) < _MIN_TEXT_LAYER_CHARS:
        return ExtractionResult(
            parser="pdf", status=STATUS_SCANNED,
            reason=(
                f"only {len(text.strip())} characters of embedded text across "
                f"{len(pages)} page(s); likely image-only or scanned. "
                "OCR is deliberately not attempted."
            ),
        )
    return ExtractionResult(text=text, parser="pdf", status=STATUS_OK)
