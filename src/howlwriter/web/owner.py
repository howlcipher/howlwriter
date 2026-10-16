"""Owner-only web actions: accepted from the app's page or with the owner's word.

The browser marks requests from HowlWriter's own page ``Sec-Fetch-Site:
same-origin``. Any other client (an AI agent, a script, curl) must send
``X-HowlWriter-Owner-Confirmed: 1`` to say the owner gave this exact
decision; otherwise the request is refused with 403
``owner_confirmation_required`` and nothing changes. This guards against an
agent deciding on the owner's behalf, not against a hostile local process.
"""

from __future__ import annotations

from fastapi import Request

OWNER_CONFIRMED_HEADER = "X-HowlWriter-Owner-Confirmed"

SOURCE_PAGE = "user_attestation"
SOURCE_RELAYED = "owner_relayed"


class OwnerConfirmationRequired(Exception):
    """An owner-only change from a client that is neither the app's page nor relaying the owner."""


def source(request: Request, why: str = "changes what trains the owner's voice profile") -> str:
    """Who is making an owner-only change: the app's page, or a client relaying the owner's word."""
    if (request.headers.get("sec-fetch-site") or "").lower() == "same-origin":
        return SOURCE_PAGE
    if (request.headers.get(OWNER_CONFIRMED_HEADER) or "").strip() == "1":
        return SOURCE_RELAYED
    raise OwnerConfirmationRequired(
        f"This {why}, and only the owner may decide it. Make the change in HowlWriter's page, or, if "
        f"the owner told you this exact decision, resend with {OWNER_CONFIRMED_HEADER}: 1. "
        "Nothing was changed."
    )


def voice_source(request: Request) -> str:
    """FastAPI dependency for authorship and Workshop decisions."""
    return source(request)
