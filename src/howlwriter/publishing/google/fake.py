"""Hermetic test double for Google Docs and Drive APIs."""

from __future__ import annotations

from typing import Any


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
            "revisionId": "rev-1",
        }
        self.documents[doc_id] = doc_record
        return doc_record

    def get_document(self, doc_id: str) -> dict[str, Any]:
        self._check_errors()
        if doc_id not in self.documents:
            raise KeyError(f"Google Doc '{doc_id}' not found (HTTP 404).")
        return self.documents[doc_id]

    def batch_update(
        self, doc_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self._check_errors()
        if doc_id not in self.documents:
            raise KeyError(f"Google Doc '{doc_id}' not found (HTTP 404).")

        doc = self.documents[doc_id]
        doc["requests"].extend(requests)
        doc["revisionId"] = f"rev-{len(doc['requests'])}"

        # Simulate text insertion
        for req in requests:
            if "insertText" in req:
                text = req["insertText"].get("text", "")
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
