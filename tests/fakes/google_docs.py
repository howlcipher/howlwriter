"""Hermetic test double for Google Docs and Drive APIs (test support only).

Note: ``deleteContentRange`` here wipes the whole body regardless of the range,
so tests built on it cannot catch range/index mistakes in the real publisher.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from howlwriter.publishing.base import RevisionConflictError


class FakeGoogleDocsAdapter:
    """In-memory mock for Google Docs and Drive APIs for testing and offline dogfooding."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.folders: dict[str, str] = {}
        self._counter = 1

        # Simulated failure modes
        self.simulate_network_error = False
        self.simulate_auth_error = False
        self.simulate_permission_error = False
        self.simulate_folder_not_found = False
        # Hooks that model what a real destination can do to a document.
        self.after_read: Callable[[dict[str, Any]], None] | None = None   # runs after a read returns
        self.before_write: Callable[[dict[str, Any]], None] | None = None  # runs just before a write is applied
        self.truncate_tail_chars = 0     # drop this many trailing characters from each write
        self.duplicate_writes = False    # apply each inserted text twice

    def create_document(self, title: str) -> dict[str, Any]:
        self._check_errors()
        doc_id = f"fake-doc-{self._counter:04d}"
        self._counter += 1
        doc_record = {
            "documentId": doc_id,
            "title": title,
            "body": "",
            "folder": None,
            "requests": [],
            "revisionId": "rev-0",
        }
        self.documents[doc_id] = doc_record
        return doc_record

    def get_document(self, doc_id: str) -> dict[str, Any]:
        self._check_errors()
        if doc_id not in self.documents:
            raise KeyError(f"Google Doc '{doc_id}' not found (HTTP 404).")
        # A read returns a snapshot, as a real API does: later edits do not change it.
        snapshot = copy.deepcopy(self.documents[doc_id])
        if self.after_read is not None:
            self.after_read(self.documents[doc_id])
        return snapshot

    def concurrent_edit(self, doc_id: str, appended_text: str) -> None:
        """Another user edits the document: content and revision both change."""
        doc = self.documents[doc_id]
        doc["body"] += appended_text
        doc["requests"].append({"insertText": {"text": appended_text}})
        doc["revisionId"] = f"rev-{len(doc['requests'])}"

    def batch_update(
        self, doc_id: str, requests: list[dict[str, Any]], required_revision_id: str | None = None
    ) -> dict[str, Any]:
        self._check_errors()
        if doc_id not in self.documents:
            raise KeyError(f"Google Doc '{doc_id}' not found (HTTP 404).")

        doc = self.documents[doc_id]
        if self.before_write is not None:
            self.before_write(doc)
        if required_revision_id is not None and doc["revisionId"] != required_revision_id:
            raise RevisionConflictError(
                f"requiredRevisionId {required_revision_id} does not match current revision {doc['revisionId']}")
        doc["requests"].extend(requests)
        doc["revisionId"] = f"rev-{len(doc['requests'])}"

        # Simulate text insertion
        for req in requests:
            if "insertText" in req:
                text = req["insertText"].get("text", "")
                if self.duplicate_writes:
                    text = text + text
                if self.truncate_tail_chars:
                    text = text[: -self.truncate_tail_chars]
                doc["body"] += text
            elif "deleteContentRange" in req:
                doc["body"] = ""

        return {"documentId": doc_id, "replies": [{}] * len(requests)}

    def move_to_folder(self, doc_id: str, folder_name_or_id: str) -> dict[str, Any]:
        self._check_errors()
        if self.simulate_folder_not_found:
            raise ValueError(f"Drive folder '{folder_name_or_id}' not found.")
        if doc_id not in self.documents:
            raise KeyError(f"Google Doc '{doc_id}' not found.")

        folder_id = self.folders.get(folder_name_or_id, folder_name_or_id)
        self.documents[doc_id]["folder"] = folder_id
        return {"documentId": doc_id, "folderId": folder_id}

    def _check_errors(self) -> None:
        if self.simulate_auth_error:
            raise PermissionError("Google OAuth token expired or invalid (HTTP 401).")
        if self.simulate_permission_error:
            raise PermissionError("Google permission denied (HTTP 403).")
        if self.simulate_network_error:
            raise ConnectionError("Google Docs API network connection timed out.")
