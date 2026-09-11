"""Google Docs publication adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from howlwriter.publishing.base import (
    ArtifactPublisher,
    PublicationArtifact,
    PublishContext,
    PublishDestination,
    PublishResult,
)
from howlwriter.publishing.google.auth import get_auth_status, load_credentials


class GoogleDocsPublisher(ArtifactPublisher):
    """Publishes authorized deliverables to Google Docs with semantic formatting."""

    def __init__(self, adapter: Any | None = None) -> None:
        self.adapter = adapter

    def _get_client(self) -> Any:
        """Obtains Google Docs & Drive service client or custom adapter."""
        if self.adapter is not None:
            return self.adapter

        creds = load_credentials()
        if not creds:
            status = get_auth_status()
            raise PermissionError(
                f"Google authentication not available. {status.get('message', '')} "
                f"(error: {status.get('error', 'token missing')})"
            )

        try:
            from googleapiclient.discovery import build  # type: ignore

            docs_service = build("docs", "v1", credentials=creds)
            drive_service = build("drive", "v3", credentials=creds)
            return _RealGoogleApiAdapter(docs_service, drive_service)
        except ImportError as exc:
            raise RuntimeError(
                "Google client libraries not installed. Run: pip install 'howlwriter[gdocs]'"
            ) from exc

    def publish(
        self,
        artifact: PublicationArtifact,
        destination: PublishDestination,
        context: PublishContext,
    ) -> PublishResult:
        # 1. Authority Boundary: Refuse unverified artifacts unless explicitly permitted
        artifact_status = artifact.metadata.get("status")
        if (
            not context.allow_unverified
            and artifact_status
            and artifact_status not in ("READY", "PASS")
        ):
            diag = (
                f"Human authority boundary violated: artifact status is '{artifact_status}', "
                f"which is not authorized for publication. Pass allow_unverified=True or --allow-unverified to force."
            )
            return PublishResult(
                destination_type="google_docs",
                destination_target=destination.target or destination.folder or "",
                artifact_title=artifact.title,
                published_at=datetime.now(timezone.utc).isoformat(),
                content_hash=artifact.content_hash,
                source_run_id=context.run_id,
                status="FAILED",
                diagnostics=[diag],
            )

        # 2. Obtain client/adapter
        try:
            client = self._get_client()
        except Exception as exc:
            return PublishResult(
                destination_type="google_docs",
                destination_target=destination.target or "",
                artifact_title=artifact.title,
                published_at=datetime.now(timezone.utc).isoformat(),
                content_hash=artifact.content_hash,
                source_run_id=context.run_id,
                status="FAILED",
                diagnostics=[f"Google Docs connection failure: {exc}"],
            )

        title = destination.metadata.get("title") or artifact.title or "HowlWriter Document"
        text_content = (
            artifact.content.decode("utf-8")
            if isinstance(artifact.content, bytes)
            else str(artifact.content)
        )

        try:
            doc_id: str
            revision_meta: dict[str, Any] = {}

            # 3. Existing Document Update vs New Document Creation
            if destination.update_doc_id:
                doc_id = destination.update_doc_id.strip()
                # Verify document exists
                existing = client.get_document(doc_id)
                revision_meta["prior_title"] = existing.get("title")

                update_mode = (destination.update_mode or "").lower().strip()
                if update_mode not in ("replace", "append"):
                    return PublishResult(
                        destination_type="google_docs",
                        destination_target=doc_id,
                        artifact_title=title,
                        artifact_id=doc_id,
                        published_at=datetime.now(timezone.utc).isoformat(),
                        content_hash=artifact.content_hash,
                        source_run_id=context.run_id,
                        status="FAILED",
                        diagnostics=[
                            f"Ambiguous update intent: update_mode must be explicitly 'replace' or 'append', got '{update_mode}'."
                        ],
                    )

                end_index = _get_doc_end_index(existing)
                requests = _build_update_requests(
                    text_content,
                    title=title,
                    mode=update_mode,
                    existing_body_length=end_index,
                )
                res = client.batch_update(doc_id, requests)
                revision_meta.update(res)
            else:
                # Create brand new document
                doc = client.create_document(title)
                doc_id = doc.get("documentId") or doc.get("id")
                requests = _build_insert_requests(text_content, title=title)
                res = client.batch_update(doc_id, requests)
                revision_meta.update(res)

            # 4. Folder Targeting
            target_folder = destination.folder or destination.target
            if target_folder and hasattr(client, "move_to_folder"):
                client.move_to_folder(doc_id, target_folder)
                revision_meta["folder"] = target_folder

            url = f"https://docs.google.com/document/d/{doc_id}/edit"

            return PublishResult(
                destination_type="google_docs",
                destination_target=target_folder or doc_id,
                artifact_title=title,
                artifact_id=doc_id,
                url=url,
                published_at=datetime.now(timezone.utc).isoformat(),
                content_hash=artifact.content_hash,
                source_run_id=context.run_id,
                revision_metadata=revision_meta,
                status="SUCCESS",
                diagnostics=[],
            )
        except Exception as exc:
            return PublishResult(
                destination_type="google_docs",
                destination_target=destination.target or "",
                artifact_title=title,
                published_at=datetime.now(timezone.utc).isoformat(),
                content_hash=artifact.content_hash,
                source_run_id=context.run_id,
                status="FAILED",
                diagnostics=[f"Google Docs publish failed: {type(exc).__name__}: {exc}"],
            )


class _RealGoogleApiAdapter:
    """Wrapper around real Google Docs and Drive API clients."""

    def __init__(self, docs_service: Any, drive_service: Any) -> None:
        self.docs = docs_service
        self.drive = drive_service

    def create_document(self, title: str) -> dict[str, Any]:
        return self.docs.documents().create(body={"title": title}).execute()

    def get_document(self, doc_id: str) -> dict[str, Any]:
        return self.docs.documents().get(documentId=doc_id).execute()

    def batch_update(
        self, doc_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not requests:
            return {}
        return (
            self.docs.documents()
            .batchUpdate(documentId=doc_id, body={"requests": requests})
            .execute()
        )

    def move_to_folder(self, doc_id: str, folder_name_or_id: str) -> dict[str, Any]:
        folder_id = folder_name_or_id
        # Search if folder_name_or_id is a name rather than an ID
        try:
            q = (
                f"mimeType='application/vnd.google-apps.folder' and "
                f"name='{folder_name_or_id}' and trashed=false"
            )
            res = self.drive.files().list(q=q, fields="files(id, name)").execute()
            files = res.get("files", [])
            if files:
                folder_id = files[0]["id"]
            else:
                # Create folder if it doesn't exist
                meta = {
                    "name": folder_name_or_id,
                    "mimeType": "application/vnd.google-apps.folder",
                }
                new_folder = self.drive.files().create(body=meta, fields="id").execute()
                folder_id = new_folder["id"]
        except Exception:
            pass

        # Move file
        file_obj = self.drive.files().get(fileId=doc_id, fields="parents").execute()
        previous_parents = ",".join(file_obj.get("parents", []))
        return (
            self.drive.files()
            .update(
                fileId=doc_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields="id, parents",
            )
            .execute()
        )


def _build_insert_requests(text: str, title: str) -> list[dict[str, Any]]:
    """Builds Google Docs batchUpdate requests for initial document structure."""
    clean_text = text.strip()
    # Simple plain text insert with title at top
    full_text = f"{title}\n\n{clean_text}\n"

    requests: list[dict[str, Any]] = [
        {"insertText": {"location": {"index": 1}, "text": full_text}}
    ]
    return requests


def _get_doc_end_index(doc_data: dict[str, Any]) -> int:
    """Estimates the end index of the existing document body."""
    body = doc_data.get("body")
    if isinstance(body, str):
        return len(body) + 1
    if isinstance(body, dict):
        content = body.get("content", [])
        if content:
            last = content[-1]
            return last.get("endIndex", 1)
    return 1


def _build_update_requests(
    text: str, title: str, mode: str, existing_body_length: int = 1
) -> list[dict[str, Any]]:
    """Builds Google Docs batchUpdate requests for updating an existing document."""
    if mode == "append":
        # Insert at end
        clean_text = f"\n\n--- Published Update: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ---\n\n{text.strip()}\n"
        return [{"insertText": {"endOfSegmentLocation": {}, "text": clean_text}}]

    # replace mode: delete existing body range if not empty, then insert at index 1
    requests: list[dict[str, Any]] = []
    if existing_body_length > 1:
        requests.append(
            {
                "deleteContentRange": {
                    "range": {
                        "startIndex": 1,
                        "endIndex": existing_body_length,
                    }
                }
            }
        )
    requests.append(
        {
            "insertText": {
                "location": {"index": 1},
                "text": f"{title}\n\n{text.strip()}\n",
            }
        }
    )
    return requests
