"""Google Docs and Drive OAuth2 authentication manager."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Narrowest practical scopes for HowlWriter:
# documents: create and edit docs
# drive.file: manage only the files created or opened by HowlWriter
GOOGLE_DOCS_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def get_credentials_dir() -> Path:
    """Returns directory for secure user credentials."""
    custom = os.environ.get("HOWLWRITER_CREDENTIALS_DIR")
    if custom and custom.strip():
        p = Path(custom.strip()).expanduser().resolve()
    else:
        p = Path.home() / ".howlwriter" / "credentials"
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(0o700)
    except OSError:
        pass
    return p


def get_token_path() -> Path:
    """Returns path to user's saved Google OAuth refresh token."""
    return get_credentials_dir() / "google_token.json"


def get_client_secrets_path() -> Path | None:
    """Locates user-supplied OAuth client configuration."""
    env_path = os.environ.get("HOWLWRITER_GOOGLE_CLIENT_CONFIG")
    if env_path and Path(env_path).expanduser().is_file():
        return Path(env_path).expanduser().resolve()

    candidate = get_credentials_dir() / "google_client_secret.json"
    if candidate.is_file():
        return candidate
    return None


def get_auth_status() -> dict[str, Any]:
    """Returns non-secret diagnostic status of Google OAuth authorization."""
    token_p = get_token_path()
    secrets_p = get_client_secrets_path()

    if not token_p.is_file():
        return {
            "authenticated": False,
            "token_path": str(token_p),
            "client_secrets_found": bool(secrets_p),
            "client_secrets_path": str(secrets_p) if secrets_p else None,
            "scopes": GOOGLE_DOCS_SCOPES,
            "message": "No Google OAuth credentials found. Run: howlwriter google auth",
        }

    try:
        from google.oauth2.credentials import Credentials  # type: ignore

        creds = Credentials.from_authorized_user_file(
            str(token_p), GOOGLE_DOCS_SCOPES
        )
        return {
            "authenticated": bool(creds and creds.valid),
            "expired": bool(creds and creds.expired),
            "token_path": str(token_p),
            "client_secrets_found": bool(secrets_p),
            "scopes": list(creds.scopes or GOOGLE_DOCS_SCOPES),
            "message": "Google credentials active and valid."
            if creds.valid
            else "Google credentials expired or need refresh.",
        }
    except ImportError:
        return {
            "authenticated": False,
            "token_path": str(token_p),
            "error": "Google client libraries not installed. Run: pip install 'howlwriter[gdocs]'",
        }
    except Exception as exc:
        return {
            "authenticated": False,
            "token_path": str(token_p),
            "error": f"Failed to load credentials: {exc}",
        }


def load_credentials() -> Any | None:
    """Loads active Google OAuth credentials, refreshing expired tokens if possible."""
    token_p = get_token_path()
    if not token_p.is_file():
        return None

    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore

        creds = Credentials.from_authorized_user_file(
            str(token_p), GOOGLE_DOCS_SCOPES
        )
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed token with safe permissions
            save_credentials(creds)
        if creds and creds.valid:
            return creds
        return None
    except ImportError as exc:
        raise RuntimeError(
            "Google Docs integration requires 'google-api-python-client'. "
            "Install with: pip install 'howlwriter[gdocs]'"
        ) from exc
    except Exception:
        return None


def save_credentials(creds: Any) -> None:
    """Saves credentials atomically with owner-only (0600) permissions."""
    from howlwriter.voice.identity.privacy import write_private_text

    write_private_text(get_token_path(), creds.to_json())


GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_PERMISSIONS_URL = "https://myaccount.google.com/permissions"


@dataclass
class LogoutResult:
    """What `revoke_and_logout` actually did."""

    remote_revoked: bool
    local_deleted: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "remote_revoked": self.remote_revoked,
            "local_deleted": self.local_deleted,
            "detail": self.detail,
        }


def _revoke_remote(token: str) -> tuple[bool, str]:
    data = urllib.parse.urlencode({"token": token}).encode("ascii")
    req = urllib.request.Request(
        GOOGLE_REVOKE_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:  # noqa: S310 - fixed https URL
            status = getattr(resp, "status", None) or resp.getcode()
    except urllib.error.HTTPError as exc:
        return False, f"Google returned HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if status == 200:
        return True, "Google confirmed the revocation"
    return False, f"Google returned HTTP {status}"


def revoke_and_logout() -> LogoutResult:
    """Revoke the token at Google when possible, then delete the local token file."""
    token_p = get_token_path()
    remote_revoked = False
    notes: list[str] = []

    token: str | None = None
    try:
        data = json.loads(token_p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("refresh_token", "token"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    token = value
                    break
    except FileNotFoundError:
        return LogoutResult(False, False, "No local token file was found.")
    except (OSError, ValueError) as exc:
        notes.append(f"could not read the token file ({type(exc).__name__})")

    if token:
        remote_revoked, why = _revoke_remote(token)
        notes.append(why if remote_revoked else f"remote revocation failed: {why}")
    elif not notes:
        notes.append("the token file holds no token to revoke")

    local_deleted = False
    try:
        token_p.unlink()
        local_deleted = True
    except OSError as exc:
        notes.append(f"could not delete the local token file: {exc}")
    return LogoutResult(remote_revoked, local_deleted, "; ".join(notes))
