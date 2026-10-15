"""Optional, read-only Drive API fallback for native Google Docs.

A mounted drive (the cloud-drive client and similar) can list a native Google Doc but
not hand over its content: the file reads as a small placeholder and the
read is refused. This module reads those documents through the Drive API
instead, and only when explicitly asked (`voice scan --google-api`).

What it does and does not do:

* Read-only. The token it uses is separate from the publishing token and is
  granted `drive.readonly` and nothing else. It never creates, edits, moves,
  shares, or trashes anything.
* Local processing. Exported plain text is analysed in memory exactly like a
  file read from the mount, then discarded. Nothing is sent to a model.
* Never silent. It runs only behind its flag, and it fails with an
  explanation (missing library, missing client config, missing token) rather
  than prompting for authorization in the middle of a scan.
* Exclusions still apply. Paths are checked against the identity's
  exclusion policy before any lookup, and shared drives are not queried.
* Revision history is provenance. The Drive API exposes how many revisions a
  document has and over what period; one revision holding a finished essay
  is a different history from forty revisions over two weeks, and the review
  queue shows it. It is never treated as proof of anything.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from howlwriter.voice.identity import analysis
from howlwriter.voice.identity.exclusions import normalize_component
from howlwriter.voice.identity.store import IdentityConfig, IdentityStore

DRIVE_READONLY_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_FILE = "google_drive_readonly_token.json"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
MAX_EXPORT_BYTES = 10 * 1024 * 1024

DISCLOSURE = (
    "Reading native Google Docs through the Drive API with a read-only token. "
    "Content is downloaded to this machine and processed locally; nothing is sent to any model."
)


class GoogleFallbackUnavailable(RuntimeError):
    """The fallback cannot run; the message says what is missing."""


def token_path() -> Path:
    from howlwriter.publishing.google.auth import get_credentials_dir

    return get_credentials_dir() / TOKEN_FILE


def authorize() -> Path:
    """Interactive one-time authorization (`howlwriter voice google-auth`)."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError as error:
        raise GoogleFallbackUnavailable(
            "the Google client libraries are not installed: pip install 'howlwriter[gdocs]'"
        ) from error
    from howlwriter.publishing.google.auth import get_client_secrets_path

    secrets = get_client_secrets_path()
    if secrets is None:
        raise GoogleFallbackUnavailable(
            "no OAuth client configuration found; place a Desktop-app client file at "
            "~/.howlwriter/credentials/google_client_secret.json (or set "
            "HOWLWRITER_GOOGLE_CLIENT_CONFIG)"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), DRIVE_READONLY_SCOPES)
    credentials = flow.run_local_server(port=0)
    path = token_path()
    path.write_text(credentials.to_json(), encoding="utf-8")
    path.chmod(0o600)
    return path


def drive_service() -> Any:
    """A Drive v3 service from the saved read-only token, or a clear refusal."""
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as error:
        raise GoogleFallbackUnavailable(
            "the Google client libraries are not installed: pip install 'howlwriter[gdocs]'"
        ) from error
    path = token_path()
    if not path.is_file():
        raise GoogleFallbackUnavailable(
            "no read-only Drive token yet; run `howlwriter voice google-auth` once to authorize"
        )
    credentials = Credentials.from_authorized_user_file(str(path), DRIVE_READONLY_SCOPES)
    if not credentials.valid and credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request  # type: ignore

        credentials.refresh(Request())
        path.write_text(credentials.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find(service: Any, relative_path: str, shared_dirs: set[str]) -> dict | None:
    """Resolve a mount-relative path to a Drive file by walking folder names."""
    parts = relative_path.split("/")
    first = normalize_component(parts[0])
    parent_clause: str | None = "'root' in parents"
    if first in shared_dirs:
        parts = parts[1:]
        parent_clause = None  # first component is resolved among sharedWithMe items
    parent_id = None
    for position, name in enumerate(parts):
        last = position == len(parts) - 1
        clauses = [f"name = '{_escape(name)}'", "trashed = false"]
        clauses.append(
            f"mimeType = '{GOOGLE_DOC_MIME}'"
            if last
            else "mimeType = 'application/vnd.google-apps.folder'"
        )
        if parent_id is not None:
            clauses.append(f"'{parent_id}' in parents")
        elif parent_clause:
            clauses.append(parent_clause)
        else:
            clauses.append("sharedWithMe = true")
        response = (
            service.files()
            .list(
                q=" and ".join(clauses),
                spaces="drive",
                pageSize=10,
                fields="files(id,name,mimeType,modifiedTime,createdTime,ownedByMe,owners(displayName,me))",
            )
            .execute()
        )
        files = response.get("files", [])
        if len(files) != 1:
            return None  # missing or ambiguous: never guess between two documents
        if last:
            return files[0]
        parent_id = files[0]["id"]
    return None


def _revisions(service: Any, file_id: str) -> dict:
    try:
        response = (
            service.revisions()
            .list(fileId=file_id, fields="revisions(id,modifiedTime)", pageSize=1000)
            .execute()
        )
    except Exception:
        return {"revision_count": None}
    times = [r.get("modifiedTime") for r in response.get("revisions", []) if r.get("modifiedTime")]
    span = None
    if len(times) >= 2:
        try:
            first = datetime.fromisoformat(times[0].replace("Z", "+00:00"))
            last = datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
            span = round((last - first).total_seconds() / 86400, 2)
        except ValueError:
            span = None
    return {"revision_count": len(times), "revision_span_days": span}


def fetch_native_documents(
    store: IdentityStore,
    config: IdentityConfig,
    entries: dict[str, dict],
    *,
    service_factory: Callable[[], Any] = drive_service,
    perturbations: bool = True,
) -> dict[str, int]:
    """Export and analyse every native document the mount could not read."""
    pending = [
        e
        for e in entries.values()
        if e.get("present", True)
        and e.get("status") == "native_unavailable"
        and not config.exclusions.path_is_excluded(e["relative_path"].split(":", 1)[-1].split("/"))
    ]
    counts = {
        "attempted": len(pending),
        "exported": 0,
        "not_found_or_ambiguous": 0,
        "not_a_document": 0,
        "failed": 0,
    }
    if not pending:
        return counts
    service = service_factory()
    shared_dirs = {normalize_component(d) for d in config.shared_with_me_dirs}
    for entry in pending:
        relative = entry["relative_path"].split(":", 1)[-1]
        try:
            found = _find(service, relative, shared_dirs)
        except Exception as error:
            counts["failed"] += 1
            entry["reason"] = f"Drive API lookup failed ({type(error).__name__})"
            continue
        if found is None:
            counts["not_found_or_ambiguous"] += 1
            entry["reason"] = (
                "not found as a single Google Doc through the Drive API (it may be a Sheet or Slides file)"
            )
            continue
        try:
            data = service.files().export(fileId=found["id"], mimeType="text/plain").execute()
        except Exception as error:
            counts["failed"] += 1
            entry["reason"] = f"Drive API export failed ({type(error).__name__})"
            continue
        if isinstance(data, str):
            data = data.encode("utf-8")
        if len(data) > MAX_EXPORT_BYTES:
            counts["failed"] += 1
            entry["reason"] = "exported text exceeds the size limit"
            continue
        text = data.decode("utf-8", errors="replace").lstrip("﻿")
        try:
            modified = datetime.fromisoformat(
                str(found.get("modifiedTime", "")).replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            modified = float(entry.get("mtime") or 0)
        ownership = entry.get("ownership", "owned")
        if found.get("ownedByMe") is False:
            ownership = "shared_with_me"
        try:
            derived = analysis.analyze(
                text=text,
                raw=data,
                relative_path=relative,
                suffix=".gdoc",
                mtime=modified,
                aliases=config.aliases,
                ownership=ownership,
                auto_accept_pre_llm_bylined=config.auto_accept_pre_llm_bylined,
                perturbations=perturbations,
            )
        except Exception as error:
            counts["failed"] += 1
            entry["reason"] = f"analysis raised {type(error).__name__}"
            continue
        import hashlib

        entry.update(derived)
        entry["raw_sha256"] = hashlib.sha256(data).hexdigest()
        entry["parser"] = "google_drive_api_export"
        entry["ownership"] = ownership
        history = _revisions(service, found["id"])
        provenance = entry.setdefault("provenance", {})
        provenance.update(history)
        notes = provenance.setdefault("notes", [])
        if history.get("revision_count") == 1 and entry.get("words", 0) >= 400:
            notes.append(
                "one recorded revision holds the whole document; it arrived in a single step"
            )
        elif history.get("revision_count"):
            notes.append(
                f"{history['revision_count']} recorded revisions"
                + (
                    f" over {history['revision_span_days']} days"
                    if history.get("revision_span_days") is not None
                    else ""
                )
            )
        if entry.get("status") == "extracted":
            counts["exported"] += 1
        else:
            counts["not_a_document"] += 1
    return counts
