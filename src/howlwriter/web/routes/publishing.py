"""Publishing endpoints: publish deliverables and inspect provider status."""

from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException

from howlwriter.diagnostic.run_record import compute_sha256, generate_run_id
from howlwriter.publishing import (
    PublicationArtifact,
    PublishContext,
    PublishDestination,
    get_publisher,
)
from howlwriter.publishing.google.auth import get_auth_status
from howlwriter.web.models import GoogleAuthStatusResponse, PublishRequest, PublishResponse

router = APIRouter(prefix="/api/publish", tags=["publishing"])


@router.get("/google/status", response_model=GoogleAuthStatusResponse)
def get_google_status() -> GoogleAuthStatusResponse:
    status = get_auth_status()
    return GoogleAuthStatusResponse(
        authenticated=status.get("authenticated", False),
        token_path=status.get("token_path", ""),
        scopes=status.get("scopes", []),
        client_secrets_found=status.get("client_secrets_found", False),
        client_secrets_path=status.get("client_secrets_path"),
        error=status.get("error"),
    )


@router.post("", response_model=PublishResponse)
def publish_document(req: PublishRequest) -> PublishResponse:
    path = Path(req.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    # Determine media type and read content
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt", ".markdown"):
        text_content = path.read_text(encoding="utf-8")
        media_type = "text/markdown" if suffix != ".txt" else "text/plain"
        binary_bytes = None
    elif suffix in (".docx", ".pdf"):
        binary_bytes = path.read_bytes()
        text_content = None
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if suffix == ".docx"
            else "application/pdf"
        )
    else:
        text_content = path.read_text(encoding="utf-8", errors="replace")
        media_type = "text/plain"
        binary_bytes = None

    sha = compute_sha256(path.read_bytes())
    title = req.title or path.stem.replace("_", " ").title()

    try:
        publisher = get_publisher(req.destination)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    artifact = PublicationArtifact(
        title=title,
        content=text_content if text_content is not None else (binary_bytes or b""),
        format=suffix.lstrip(".").lower() or "md",
        source_run_id=generate_run_id(),
        authorized_sha256=sha,
        metadata={
            "media_type": media_type,
            "status": "READY" if req.allow_unverified else "UNKNOWN",
            "allow_unverified": req.allow_unverified,
        },
    )

    dest = PublishDestination(
        destination_type=req.destination,
        target=req.folder or title,
        folder=req.folder,
        update_doc_id=req.update_doc_id,
        update_mode=req.update_mode,
        metadata={"title": title},
    )

    ctx = PublishContext(
        run_id=generate_run_id(),
        dry_run=False,
        allow_unverified=req.allow_unverified,
    )

    result = publisher.publish(artifact, dest, ctx)
    return PublishResponse(
        success=result.is_success,
        destination=result.destination_type,
        document_id=result.artifact_id,
        document_url=result.url,
        version_or_revision=result.revision_metadata.get("revision_id"),
        published_at=result.published_at,
        error_message="; ".join(result.diagnostics) if not result.is_success else None,
    )
