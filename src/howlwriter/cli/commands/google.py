"""`howlwriter google <auth|status|logout>` -- Google Docs OAuth authorization management."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from howlwriter.publishing.google.auth import (
    get_auth_status,
    get_client_secrets_path,
    get_token_path,
    revoke_and_logout,
    save_credentials,
)


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "google",
        help="Manage Google Docs OAuth authentication and credentials.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # status
    p_status = sub.add_parser("status", help="Check Google OAuth credential status.")
    p_status.set_defaults(handler=run_status)

    # auth
    p_auth = sub.add_parser("auth", help="Authenticate with Google OAuth.")
    p_auth.add_argument(
        "--client-secrets",
        dest="client_secrets",
        default=None,
        help="Path to Google OAuth client secrets JSON file.",
    )
    p_auth.set_defaults(handler=run_auth)

    # logout
    p_logout = sub.add_parser("logout", help="Revoke and delete local Google credentials.")
    p_logout.set_defaults(handler=run_logout)

    return parser


def run_status(args: argparse.Namespace) -> int:
    status = get_auth_status()
    print("Google OAuth Authentication Status")
    print("==================================")
    print(f"Authenticated:       {status.get('authenticated')}")
    print(f"Token Path:          {status.get('token_path')}")
    if "scopes" in status:
        print(f"Authorized Scopes:   {', '.join(status['scopes'])}")
    if status.get("client_secrets_found"):
        print(f"Client Secrets:      Found ({status.get('client_secrets_path')})")
    else:
        print("Client Secrets:      Not configured (default or custom secrets required for new auth)")

    if status.get("error"):
        print(f"\nNotice: {status['error']}")
    elif status.get("message"):
        print(f"\nStatus: {status['message']}")

    return 0 if status.get("authenticated") else 1


def run_auth(args: argparse.Namespace) -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from howlwriter.publishing.google.auth import GOOGLE_DOCS_SCOPES
    except ImportError:
        print(
            "error: Google client libraries are required for authentication.\n"
            "Install them with: pip install 'howlwriter[gdocs]'",
            file=sys.stderr,
        )
        return 1

    secrets_path = args.client_secrets or get_client_secrets_path()
    if not secrets_path or not Path(secrets_path).is_file():
        print(
            "error: Google OAuth client configuration not found.\n"
            "Provide a client secrets file via --client-secrets <path>, or place it at:\n"
            f"  ~/.howlwriter/credentials/google_client_secret.json\n"
            "or set the HOWLWRITER_GOOGLE_CLIENT_CONFIG environment variable.",
            file=sys.stderr,
        )
        return 1

    print(f"Starting Google OAuth authorization using: {secrets_path}")
    print("Requested Scopes:")
    for scope in GOOGLE_DOCS_SCOPES:
        print(f"  - {scope}")
    print("\nPlease follow the authorization prompt in your browser...")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(secrets_path), GOOGLE_DOCS_SCOPES
        )
        creds = flow.run_local_server(port=0)
        save_credentials(creds)
        print(f"\nAuthentication successful! Token saved securely to: {get_token_path()}")
        return 0
    except Exception as exc:
        print(f"error: Google authentication failed: {exc}", file=sys.stderr)
        return 1


def run_logout(args: argparse.Namespace) -> int:
    token_p = get_token_path()
    if not token_p.is_file():
        print("No active Google OAuth credentials found to revoke.")
        return 0

    revoked = revoke_and_logout()
    if revoked:
        print("Google OAuth credentials revoked and local token deleted.")
    else:
        print("Failed to remove local credentials.")
    return 0
