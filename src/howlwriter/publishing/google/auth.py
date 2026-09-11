"""Google Docs and Drive OAuth2 authentication manager."""

from __future__ import annotations

import os
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
    if env_path and Path(env_path).is_file():
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
    """Saves credentials securely to disk with 0600 permissions."""
    token_p = get_token_path()
    token_json = creds.to_json()
    token_p.write_text(token_json, encoding="utf-8")
    try:
        token_p.chmod(0o600)
    except OSError:
        pass


def revoke_and_logout() -> bool:
    """Revokes local credentials and deletes token file."""
    token_p = get_token_path()
    revoked = False

    if token_p.is_file():
        try:
            creds = load_credentials()
            if creds and hasattr(creds, "token"):
                import httpx

                httpx.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": creds.token},
                    timeout=5.0,
                )
        except Exception:
            pass

        try:
            token_p.unlink()
            return True
        except OSError:
            return False

    return False
