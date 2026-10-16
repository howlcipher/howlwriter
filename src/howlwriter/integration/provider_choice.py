"""Which model runs a writing job: chosen by the person, at run time.

HowlWriter does not need a permanent role binding. When a run needs a model
and none is bound, the person picks one (Claude Code, Antigravity, Codex, or
a local model) before anything is sent. Picking a model that is not local
shows what leaves the machine and needs a yes. The choice lasts for one CLI
process, or one web request, and is never written to configuration.

A review role that must be independent of the writer (``avoid_provider``)
gets its own question; the bridge never switches models without asking.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import os
import sys
from typing import Callable, TextIO

ENV_PROVIDER = "HOWLWRITER_PROVIDER"
ENV_REVIEW_PROVIDER = "HOWLWRITER_REVIEW_PROVIDER"
#: Which Ollama model "local" means (HowlPlane's default is a coding model).
ENV_LOCAL_MODEL = "HOWLWRITER_LOCAL_MODEL"


@dataclass(frozen=True)
class ProviderOption:
    provider: str  # HowlPlane backend id
    label: str
    local: bool
    keys: tuple[str, ...]  # accepted spellings


OPTIONS: tuple[ProviderOption, ...] = (
    ProviderOption("claude_code", "Claude Code", False, ("claude_code", "claude", "claude-code")),
    ProviderOption("agy", "Antigravity (agy)", False, ("agy", "antigravity")),
    ProviderOption("codex", "Codex", False, ("codex",)),
    ProviderOption("local_ollama", "Local model (Ollama)", True, ("local", "ollama", "local_ollama")),
)

#: A per-request choice (the web UI sends one with each request).
REQUEST_PROVIDER: ContextVar[str | None] = ContextVar("howlwriter_request_provider", default=None)
REQUEST_REVIEW_PROVIDER: ContextVar[str | None] = ContextVar(
    "howlwriter_request_review_provider", default=None
)
#: The person chose, for this request, to continue without a model.
REQUEST_NO_MODEL: ContextVar[bool] = ContextVar("howlwriter_request_no_model", default=False)
#: The value meaning "no model" (deterministic steps only).
NO_MODEL = "none"
#: The person confirmed, for this request, that text may go to the remote models it names.
REQUEST_CONFIRMED: ContextVar[bool] = ContextVar("howlwriter_request_confirmed", default=False)

#: Web headers that carry a per-request choice.
HEADER_PROVIDER = "x-howlwriter-provider"
HEADER_REVIEW_PROVIDER = "x-howlwriter-review-provider"
HEADER_CONFIRMED = "x-howlwriter-send-confirmed"


#: Process-wide choices from the CLI (--provider, environment, whether it may ask).
PROCESS_DEFAULTS: dict = {"writer": None, "reviewer": None, "interactive": False, "local_model": None}


class ProviderChoiceCancelled(RuntimeError):
    """The person declined to choose a model, or declined to send text to it."""


def normalize(name: str) -> str:
    """The HowlPlane backend id for a spelling such as 'claude' or 'local'."""
    key = (name or "").strip().lower()
    for option in OPTIONS:
        if key in option.keys:
            return option.provider
    choices = ", ".join(o.keys[0] if not o.local else "local" for o in OPTIONS)
    raise ValueError(f"unknown model {name!r}; choose one of: {choices}")


def option_for(provider: str) -> ProviderOption | None:
    try:
        provider = normalize(provider)
    except ValueError:
        return None
    return next((o for o in OPTIONS if o.provider == provider), None)


def is_local(provider: str | None) -> bool:
    option = option_for(provider or "")
    if option is not None:
        return option.local
    return (provider or "").lower().startswith(("ollama", "local", "llama"))


def local_model() -> str | None:
    """The Ollama model chosen with --local-model or HOWLWRITER_LOCAL_MODEL, if any."""
    return PROCESS_DEFAULTS.get("local_model") or os.environ.get(ENV_LOCAL_MODEL, "").strip() or None


def make_backend(provider: str):
    """HowlPlane's backend for exactly this provider; "local" uses the chosen Ollama model."""
    from howlwriter.integration.howlplane_bridge import _ensure_howlplane_on_path

    _ensure_howlplane_on_path()
    from howlplane.control_plane.agent_execution import AgentBackendRegistry

    model = local_model()
    if provider == "local_ollama" and model:
        try:
            from howlplane.control_plane.agent_execution import OllamaLocalBackend
        except ImportError as error:
            raise ValueError(
                "this HowlPlane has no selectable local backend, so --local-model cannot be used"
            ) from error
        return OllamaLocalBackend(model=model)
    return AgentBackendRegistry.get_backend(provider)


def availability() -> list[tuple[ProviderOption, bool, str]]:
    """Each option, whether it can run now, and why not."""
    from howlwriter.integration.howlplane_bridge import _ensure_howlplane_on_path

    _ensure_howlplane_on_path()
    try:
        import howlplane.control_plane.agent_execution  # noqa: F401
    except ImportError:
        return [(o, False, "HowlPlane is not installed") for o in OPTIONS]
    rows = []
    for option in OPTIONS:
        try:
            backend = make_backend(option.provider)
            if option.local and hasattr(backend, "diagnose"):
                diagnosis = backend.diagnose()
                ready = bool(diagnosis.available)
                why = "" if ready else diagnosis.detail
                if not ready and "did not respond" in why:
                    why += " Start it with `ollama serve`."
                rows.append((option, ready, why))
            else:
                ready = bool(backend.is_available())
                rows.append((option, ready, "" if ready else "its command-line tool is not installed"))
        except Exception as error:  # a broken backend must not hide the others
            rows.append((option, False, f"unavailable ({type(error).__name__})"))
    return rows


def disclosure(option: ProviderOption) -> str:
    return (
        f"{option.label} is not a local model. The text of this run (your draft or sources, "
        "and for a project draft, evidence excerpts from the project), and a summary of your voice "
        f"profile when one is in use, will be sent to {option.label}'s provider."
    )


def ask(
    *,
    purpose: str,
    avoid: str | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    rows: list[tuple[ProviderOption, bool, str]] | None = None,
    allow_none: bool = False,
) -> tuple[str, bool]:
    """Ask which model to use. Returns (provider, remote_confirmed); provider may be NO_MODEL."""
    out = output or sys.stderr
    rows = availability() if rows is None else rows
    avoid_id = None
    if avoid:
        try:
            avoid_id = normalize(avoid)
        except ValueError:
            avoid_id = avoid
    print(f"\nWhich model should run {purpose}?", file=out)
    if avoid_id:
        print(
            "  (this review should use a different model than the one that wrote the text; "
            "choosing the same one is allowed but the review will not be independent)",
            file=out,
        )
    selectable: dict[str, ProviderOption] = {}
    for number, (option, ready, why) in enumerate(rows, start=1):
        tags = ["private, on this machine" if option.local else "sends text to its provider"]
        if option.provider == avoid_id:
            tags.append("wrote the text")
        line = f"  {number}. {option.label} ({'; '.join(tags)})"
        if ready:
            selectable[str(number)] = option
            for key in option.keys:
                selectable[key] = option
        else:
            line += f"  [unavailable: {why}]"
        print(line, file=out)
    if allow_none:
        print("  0. Continue without a model (rule-based steps only)", file=out)
        selectable["0"] = None
    elif not selectable:
        raise ProviderChoiceCancelled("no model is available to run this")
    answer = input_fn("Choose a number (Enter to cancel): ").strip().lower()
    if answer not in selectable:
        raise ProviderChoiceCancelled("no model was chosen; nothing was sent")
    option = selectable[answer]
    if option is None:
        return NO_MODEL, False
    if option.local:
        return option.provider, False
    print(disclosure(option), file=out)
    if input_fn(f"Send it to {option.label}? [y/N]: ").strip().lower() not in ("y", "yes"):
        raise ProviderChoiceCancelled(f"declined to send text to {option.label}; nothing was sent")
    return option.provider, True


def interactive_chooser(
    input_fn: Callable[[str], str] = input, output: TextIO | None = None
) -> Callable[..., tuple[str, bool]]:
    def chooser(role, avoid: str | None = None) -> tuple[str, bool]:
        purpose = f"the {role.value.replace('_', ' ')} step"
        # A review is either run or the whole run stops; "no model" is offered only up front.
        return ask(purpose=purpose, avoid=avoid, input_fn=input_fn, output=output, allow_none=avoid is None)

    return chooser


def from_environment() -> tuple[str | None, str | None]:
    """(writer, reviewer) choices from HOWLWRITER_PROVIDER / HOWLWRITER_REVIEW_PROVIDER."""
    writer = os.environ.get(ENV_PROVIDER, "").strip()
    reviewer = os.environ.get(ENV_REVIEW_PROVIDER, "").strip()
    return (normalize(writer) if writer else None, normalize(reviewer) if reviewer else None)


def choices_payload() -> list[dict]:
    """The options and whether each can run now, for the web picker."""
    return [
        {"provider": o.provider, "label": o.label, "local": o.local, "available": ready, "detail": why,
         "disclosure": "" if o.local else disclosure(o)}
        for o, ready, why in availability()
    ]


def apply_request_headers(headers) -> None:
    """Set this request's choice from the web UI's headers (unknown names are ignored)."""
    if (headers.get(HEADER_PROVIDER) or "").strip().lower() == NO_MODEL:
        REQUEST_NO_MODEL.set(True)
    pairs = ((HEADER_PROVIDER, REQUEST_PROVIDER), (HEADER_REVIEW_PROVIDER, REQUEST_REVIEW_PROVIDER))
    for header, var in pairs:
        value = (headers.get(header) or "").strip()
        if value and value.lower() != NO_MODEL:
            try:
                var.set(normalize(value))
            except ValueError:
                pass
    REQUEST_CONFIRMED.set((headers.get(HEADER_CONFIRMED) or "").strip() == "1")
