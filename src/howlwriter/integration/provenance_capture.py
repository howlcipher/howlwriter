"""Capturing every model call where it actually leaves the system.

There is exactly one place a prompt reaches a provider:
`HowlPlaneWritingBridge.execute_writing_role`. Seven call sites across the
academic writer, the humanizer, the meaning reviewer and its fallback, the
consistency reviewer, the voice analyst, and now the outline writer all funnel
through it, and it holds the only `dispatcher.execute` call in the codebase.

That single seam is why prompt capture here can be exact rather than
reconstructed. The recorder sees the same `prompt` and `system_instruction`
strings the provider receives, in the same call, so there is no second prompt
builder that could drift away from the first. Anything assembled afterwards by
re-rendering "the prompt that would have been sent" is a reconstruction, and
this module exists so that no such thing is ever needed.

Recording is always on when a run activates a recorder; the provenance LEVEL
decides only what gets persisted. Deciding at capture time instead would mean a
user who wanted the full record had to know that before running, which is
exactly when they do not yet know whether they will want it.

The recorder never raises into the pipeline. Diagnostics that can abort a
writing job are worse than diagnostics that go missing, so every entry point
here swallows its own failures the same way `RunRecord.save` does.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from howlwriter.domain.generation_provenance import (
    MODEL_NOT_REPORTED,
    MODEL_REPORTED,
    ModelCallRecord,
    sha256_text,
)

#: Active recorder for the current run. A ContextVar rather than a module
#: global so that concurrent runs in the web job manager cannot write into each
#: other's provenance.
_ACTIVE: ContextVar["ProvenanceRecorder | None"] = ContextVar(
    "howlwriter_provenance_recorder", default=None
)


class ProvenanceRecorder:
    """Collects model calls for one run, in dispatch order."""

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        self.calls: list[ModelCallRecord] = []
        self._token: Any = None

    # --- activation ---------------------------------------------------

    def __enter__(self) -> "ProvenanceRecorder":
        self._token = _ACTIVE.set(self)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            _ACTIVE.reset(self._token)
            self._token = None

    def activate(self) -> Any:
        """Enter without a `with` block, for a body too long to indent.

        The caller owns the token and must release it in a `finally`; see
        `run_academic_pipeline`.
        """
        return _ACTIVE.set(self)

    def deactivate(self, token: Any) -> None:
        try:
            _ACTIVE.reset(token)
        except (ValueError, LookupError):
            # Token from another context, which means something already reset
            # it. Clearing outright is still correct and never worse.
            _ACTIVE.set(None)

    # --- capture ------------------------------------------------------

    def record(
        self,
        *,
        role: str,
        prompt: str,
        system_instruction: str | None,
        result: Any,
        avoid_provider: str | None = None,
        started_at: str = "",
    ) -> ModelCallRecord:
        """Record one completed call. Never raises."""
        try:
            return self._record(
                role=role,
                prompt=prompt,
                system_instruction=system_instruction,
                result=result,
                avoid_provider=avoid_provider,
                started_at=started_at,
            )
        except Exception:                       # pragma: no cover - defensive
            return ModelCallRecord(role=role)

    def _record(
        self,
        *,
        role: str,
        prompt: str,
        system_instruction: str | None,
        result: Any,
        avoid_provider: str | None,
        started_at: str,
    ) -> ModelCallRecord:
        system = system_instruction or ""
        model = getattr(result, "model", None)
        raw_output = getattr(result, "raw_output", "") or ""
        metadata = dict(getattr(result, "metadata", {}) or {})

        record = ModelCallRecord(
            sequence=len(self.calls) + 1,
            role=role,
            provider=getattr(result, "provider", "") or "",
            model=model,
            # An unreported model is a fact about the provider, not a gap to
            # fill in from the provider's name.
            model_status=MODEL_REPORTED if model else MODEL_NOT_REPORTED,
            started_at=started_at or _now(),
            duration_seconds=getattr(result, "duration_seconds", None),
            success=bool(getattr(result, "success", True)),
            timed_out=bool(getattr(result, "timed_out", False)),
            error_message=getattr(result, "error_message", None),
            independence_status=getattr(result, "independence_status", None),
            avoid_provider=avoid_provider,
            system_instruction=system,
            user_prompt=prompt,
            system_instruction_sha256=sha256_text(system),
            user_prompt_sha256=sha256_text(prompt),
            system_instruction_chars=len(system),
            user_prompt_chars=len(prompt),
            response_sha256=sha256_text(raw_output),
            response_chars=len(raw_output),
            # HowlPlane's result carries no usage or request id. Left as None
            # rather than estimated, so "unavailable" stays distinguishable
            # from "zero".
            token_usage=_first_dict(metadata, ("token_usage", "usage", "tokens")),
            request_id=_first_str(metadata, ("request_id", "requestId", "id")),
            response_id=_first_str(metadata, ("response_id", "responseId")),
        )

        # A retry is recognised by the same role re-sending the same prompt
        # after a failure, which is exactly what the meaning reviewer's
        # independence fallback does when no second provider is available.
        for earlier in reversed(self.calls):
            if (
                earlier.role == role
                and earlier.user_prompt_sha256 == record.user_prompt_sha256
                and not earlier.success
            ):
                record.retry_of = earlier.sequence
                break

        self.calls.append(record)
        return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_dict(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, dict) and value:
            return value
    return None


def _first_str(source: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def active_recorder() -> ProvenanceRecorder | None:
    """The recorder for the current run, if one is active."""
    return _ACTIVE.get()


def capture_call(
    *,
    role: str,
    prompt: str,
    system_instruction: str | None,
    result: Any,
    avoid_provider: str | None = None,
    started_at: str = "",
) -> None:
    """Record a call if anything is listening. Cheap and silent when not."""
    recorder = _ACTIVE.get()
    if recorder is None:
        return
    recorder.record(
        role=role,
        prompt=prompt,
        system_instruction=system_instruction,
        result=result,
        avoid_provider=avoid_provider,
        started_at=started_at,
    )


def reset_recorder() -> None:
    """Clear any active recorder. Safe to call when none is set."""
    _ACTIVE.set(None)
