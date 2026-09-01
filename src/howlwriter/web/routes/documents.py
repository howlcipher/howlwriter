"""Document management routes: open, save, and stats."""

from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException

from howlwriter.academic.length import count_body_words
from howlwriter.domain.document import Document
from howlwriter.domain.io import atomic_write_text
from howlwriter.web.models import (
    DocumentResponse,
    DocumentStatsResponse,
    OpenDocumentRequest,
    SaveDocumentRequest,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/open", response_model=DocumentResponse)
def open_document(req: OpenDocumentRequest) -> DocumentResponse:
    path = Path(req.path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.path}")
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a regular file: {req.path}")

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

    doc = Document.parse(content, title=path.stem)
    words = count_body_words(content)
    chars = len(content)
    lines = len(content.splitlines())

    return DocumentResponse(
        path=str(path),
        title=path.stem,
        content=content,
        word_count=words,
        char_count=chars,
        line_count=lines,
        mode=str(doc.mode.value) if doc.mode else "general",
    )


@router.post("/save", response_model=DocumentResponse)
def save_document(req: SaveDocumentRequest) -> DocumentResponse:
    path = Path(req.path).expanduser().resolve()
    try:
        atomic_write_text(path, req.content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write file safely: {exc}")

    words = count_body_words(req.content)
    chars = len(req.content)
    lines = len(req.content.splitlines())

    return DocumentResponse(
        path=str(path),
        title=path.stem,
        content=req.content,
        word_count=words,
        char_count=chars,
        line_count=lines,
    )


@router.post("/stats", response_model=DocumentStatsResponse)
def document_stats(req: SaveDocumentRequest) -> DocumentStatsResponse:
    words = count_body_words(req.content)
    chars = len(req.content)
    lines = len(req.content.splitlines())
    title = Path(req.path).stem if req.path else "Untitled"

    return DocumentStatsResponse(
        path=req.path if req.path else None,
        title=title,
        word_count=words,
        char_count=chars,
        line_count=lines,
    )
