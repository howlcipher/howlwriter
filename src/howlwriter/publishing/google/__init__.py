"""Google Docs and Drive publishing integration."""

from howlwriter.publishing.google.auth import (
    GOOGLE_DOCS_SCOPES,
    get_auth_status,
    load_credentials,
    revoke_and_logout,
)
from howlwriter.publishing.google.fake import FakeGoogleDocsAdapter
from howlwriter.publishing.google.publisher import GoogleDocsPublisher

__all__ = [
    "GOOGLE_DOCS_SCOPES",
    "get_auth_status",
    "load_credentials",
    "revoke_and_logout",
    "GoogleDocsPublisher",
    "FakeGoogleDocsAdapter",
]
