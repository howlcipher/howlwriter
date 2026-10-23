"""Google Docs publication adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
from typing import Any

from howlwriter.publishing.verification import (
    HASH_MISMATCH,
    approved_record,
    extract_document_text,
    looks_like_sha256,
    verify_readback,
    write_record,
)
from howlwriter.publishing.base import (
    ArtifactPublisher,
    PublicationArtifact,
    PublishContext,
    PublishDestination,
    PublishResult,
    RevisionConflictError,
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

        # 1b. The text being published must be the text that was approved. Fails closed: an approval
        # hash that is present but not a recognizable SHA-256 is refused, never ignored.
        asserted = (artifact.authorized_sha256 or "").strip()
        if asserted:
            normalized = asserted.lower().removeprefix("sha256:").strip()
            if not looks_like_sha256(normalized) or normalized != artifact.content_hash:
                reason = ("is not a SHA-256" if not looks_like_sha256(normalized) else
                          f"does not match (approved {normalized[:12]}, got {artifact.content_hash[:12]})")
                return PublishResult(
                    destination_type="google_docs",
                    destination_target=destination.target or destination.folder or "",
                    artifact_title=artifact.title,
                    published_at=datetime.now(timezone.utc).isoformat(),
                    content_hash=artifact.content_hash,
                    source_run_id=context.run_id,
                    status="FAILED",
                    diagnostics=[f"{HASH_MISMATCH}: the approval hash {reason}. Nothing was published."],
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
            prior_text = ""
            update_mode = ""

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

                # Revision-aware write: refuse if the document changed since we read it. The
                # check is repeated immediately before the write and enforced again by the
                # destination, so a concurrent edit is reported, never overwritten.
                read_revision = existing.get("revisionId")
                if not read_revision or not _supports_revision_guard(client):
                    return PublishResult(
                        destination_type="google_docs", destination_target=doc_id, artifact_title=title,
                        artifact_id=doc_id, published_at=datetime.now(timezone.utc).isoformat(),
                        content_hash=artifact.content_hash, source_run_id=context.run_id, status="FAILED",
                        diagnostics=["Cannot update an existing document safely: the destination does not "
                                     "provide a revision id or revision-aware writes. Nothing was changed."])
                prior_text = extract_document_text(existing)
                fresh = client.get_document(doc_id)
                if fresh.get("revisionId") != read_revision:
                    raise RevisionConflictError(
                        f"document changed since it was read (revision {read_revision} -> {fresh.get('revisionId')})")
                revision_meta["read_revision"] = read_revision

                end_index = _get_doc_end_index(existing)
                requests = _build_update_requests(
                    text_content,
                    title=title,
                    mode=update_mode,
                    existing_body_length=end_index,
                )
                res = client.batch_update(doc_id, requests, required_revision_id=read_revision)
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
            folder_error = ""
            if target_folder and hasattr(client, "move_to_folder"):
                try:
                    client.move_to_folder(doc_id, target_folder)
                    revision_meta["folder"] = target_folder
                except Exception as exc:  # the document exists; say so rather than "nothing published"
                    folder_error = f"The document was written but could not be moved to '{target_folder}' " \
                                   f"({type(exc).__name__}: {exc})."
                    revision_meta["folder_error"] = folder_error

            url = f"https://docs.google.com/document/d/{doc_id}/edit"

            # 5. Confirm what the destination now holds. Success is not claimed on a write alone.
            record_dir = context.extra.get("record_dir") if isinstance(context.extra, dict) else None
            if record_dir:
                rec = approved_record(text_content, title=title, run_id=context.run_id)
                rec.authorized_sha256 = artifact.authorized_sha256
                revision_meta["approved_record"] = str(write_record(rec, record_dir))
            status, diagnostics = "SUCCESS", []
            if folder_error:
                status, diagnostics = "UNCONFIRMED", [folder_error]
            try:
                readback_doc = client.get_document(doc_id)
                verification = verify_readback(
                    text_content, extract_document_text(readback_doc), title=title,
                    prior_text=prior_text if (destination.update_doc_id and update_mode == "append") else "",
                    min_words=context.extra.get("min_words") if isinstance(context.extra, dict) else None,
                    max_words=context.extra.get("max_words") if isinstance(context.extra, dict) else None)
                revision_meta["readback"] = verification.to_dict()
                revision_meta["readback_revision"] = readback_doc.get("revisionId")
                if not verification.verified:
                    status = "UNCONFIRMED"
                    diagnostics = diagnostics + [f"{f.code}: {f.message}" for f in verification.findings
                                                 if f.severity == "error"]
            except Exception as exc:  # could not read back: unconfirmed, not failed and not success
                status = "UNCONFIRMED"
                diagnostics = diagnostics + [f"The published document could not be read back ({type(exc).__name__}: {exc}); "
                               "publication is unconfirmed."]

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
                status=status,
                diagnostics=diagnostics,
            )
        except RevisionConflictError as exc:
            return PublishResult(
                destination_type="google_docs",
                destination_target=destination.target or "",
                artifact_title=title,
                artifact_id=destination.update_doc_id,
                published_at=datetime.now(timezone.utc).isoformat(),
                content_hash=artifact.content_hash,
                source_run_id=context.run_id,
                status="CONFLICT",
                diagnostics=[f"Not published: {exc}. The document was changed by someone else; "
                             "nothing was overwritten. Read the current version and retry."],
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


def _supports_revision_guard(client: Any) -> bool:
    try:
        return "required_revision_id" in inspect.signature(client.batch_update).parameters
    except (TypeError, ValueError, AttributeError):
        return False


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
        self, doc_id: str, requests: list[dict[str, Any]], required_revision_id: str | None = None
    ) -> dict[str, Any]:
        if not requests:
            return {}
        body: dict[str, Any] = {"requests": requests}
        if required_revision_id:
            body["writeControl"] = {"requiredRevisionId": required_revision_id}
        try:
            return self.docs.documents().batchUpdate(documentId=doc_id, body=body).execute()
        except Exception as exc:
            # The Docs API rejects a stale requiredRevisionId with HTTP 400 naming the revision.
            if required_revision_id and "revision" in str(exc).lower():
                raise RevisionConflictError(f"destination rejected the write: {exc}") from exc
            raise

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
    # The final newline of a document body can never be deleted; the range must stop before it.
    delete_end = existing_body_length - 1
    if delete_end > 1:
        requests.append(
            {
                "deleteContentRange": {
                    "range": {
                        "startIndex": 1,
                        "endIndex": delete_end,
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
