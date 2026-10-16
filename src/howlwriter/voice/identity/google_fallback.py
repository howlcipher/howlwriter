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
from howlwriter.voice.identity.store import (
    EXPORT_PARSER,
    IdentityConfig,
    IdentityStore,
    source_path_of,
)

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


def docs_service() -> Any:
    """A Docs v1 service on the same read-only token (drive.readonly covers documents.get)."""
    from google.oauth2.credentials import Credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    credentials = Credentials.from_authorized_user_file(str(token_path()), DRIVE_READONLY_SCOPES)
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


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


#: HTTP statuses worth retrying: rate limiting and transient server errors.
_RETRYABLE = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = 1.0


def _execute(request: Any, *, sleep=None) -> Any:
    """Execute a Google API request with exponential backoff on 429/5xx."""
    import time

    sleep = sleep or time.sleep
    for attempt in range(MAX_ATTEMPTS):
        try:
            return request.execute()
        except Exception as error:
            status = getattr(getattr(error, "resp", None), "status", None)
            if status is None:
                status = getattr(error, "status_code", None)
            try:
                status = int(status) if status is not None else None
            except (TypeError, ValueError):
                status = None
            if status not in _RETRYABLE or attempt == MAX_ATTEMPTS - 1:
                raise
            sleep(BACKOFF_SECONDS * (2**attempt))
    raise RuntimeError("unreachable")


def _list_all(service: Any, **kwargs: Any) -> list[dict]:
    """files.list across every page."""
    files: list[dict] = []
    token = None
    while True:
        response = _execute(
            service.files().list(pageToken=token, **kwargs)
            if token
            else service.files().list(**kwargs)
        )
        files.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            return files


def _docs_text(docs: Any, document_id: str) -> str | None:
    """Full text of a Google Doc, every tab, via the Docs API."""
    if docs is None:
        return None
    document = _execute(docs.documents().get(documentId=document_id, includeTabsContent=True))

    def body_text(body: dict) -> list[str]:
        out = []
        for element in body.get("content", []) or []:
            paragraph = element.get("paragraph")
            if paragraph:
                runs = "".join(
                    (e.get("textRun") or {}).get("content", "")
                    for e in paragraph.get("elements", []) or []
                )
                out.append(runs)
            table = element.get("table")
            if table:
                for row in table.get("tableRows", []) or []:
                    for cell in row.get("tableCells", []) or []:
                        out.extend(body_text(cell))
        return out

    def walk(tabs: list[dict]) -> list[str]:
        out = []
        for tab in tabs or []:
            body = ((tab.get("documentTab") or {}).get("body")) or {}
            out.extend(body_text(body))
            out.extend(walk(tab.get("childTabs", [])))
        return out

    tabs = document.get("tabs")
    lines = walk(tabs) if tabs else body_text(document.get("body") or {})
    text = "".join(lines)
    return text if text.strip() else None


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
        files = _list_all(
            service,
            q=" and ".join(clauses),
            spaces="drive",
            pageSize=100,
            fields=(
                "nextPageToken,"
                "files(id,name,mimeType,modifiedTime,createdTime,ownedByMe,owners(displayName,me))"
            ),
        )
        if len(files) != 1:
            return None  # missing or ambiguous: never guess between two documents
        if last:
            return files[0]
        parent_id = files[0]["id"]
    return None


def _revisions(service: Any, file_id: str) -> dict:
    try:
        response = _execute(
            service.revisions().list(
                fileId=file_id, fields="revisions(id,modifiedTime)", pageSize=1000
            )
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
    docs_factory: Callable[[], Any] | None = None,
    perturbations: bool = True,
) -> dict[str, int]:
    """Export and analyse every native document the mount could not read."""
    pending = [
        e
        for e in entries.values()
        if e.get("present", True)
        and (
            e.get("status") == "native_unavailable"
            # Exported before private copies were kept: fetch again so profiles can read it.
            or (e.get("parser") == EXPORT_PARSER and not Path(e.get("content_path") or "").is_file())
            # Names the mount cannot even stat (e.g. containing ':') are
            # still native documents the API can supply.
            or (e.get("status") == "unreadable" and not e.get("suffix"))
        )
        and not config.exclusions.path_is_excluded(source_path_of(e).split("/"))
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
    docs = None
    try:
        docs = (docs_factory or docs_service)()
    except Exception:
        docs = None  # Drive export still works without the Docs API
    shared_dirs = {normalize_component(d) for d in config.shared_with_me_dirs}
    for entry in pending:
        relative = source_path_of(entry)
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
            tab_text = None
            try:
                tab_text = _docs_text(docs, found["id"])
            except Exception:
                tab_text = None
            if tab_text is not None:
                data = tab_text.encode("utf-8")
            else:
                data = _execute(service.files().export(fileId=found["id"], mimeType="text/plain"))
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
        entry["parser"] = EXPORT_PARSER
        entry["ownership"] = ownership
        if entry.get("status") == "extracted":
            # Profile builds read text from a file; the mount only holds a stub.
            entry["content_path"] = str(store.save_export(entry["doc_id"], text))
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
