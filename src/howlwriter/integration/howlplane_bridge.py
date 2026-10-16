"""Bridge binding HowlWriter WritingRoles to HowlPlane's role execution framework.

Allows HowlWriter to request capabilities from HowlPlane without creating a
parallel provider-routing system inside HowlWriter.
HowlWriter owns the semantics of writing roles.
HowlPlane owns execution, provider resolution, reviewer independence, and control.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable, Protocol, runtime_checkable

from howlwriter.integration.model_role import (
    ModelRoleNotConfiguredError,
    WritingRole,
)
from howlwriter.integration import provider_choice
from howlwriter.integration.provenance_capture import capture_call


@runtime_checkable
class RoleBindingProtocol(Protocol):
    domain: str
    role: str
    provider: str | None


@runtime_checkable
class RoleBindingRegistryProtocol(Protocol):
    def get_binding(self, domain: str, role: str) -> Any | None: ...
    def register_binding(self, binding: Any) -> None: ...
    def clear(self) -> None: ...


@runtime_checkable
class RoleDispatcherProtocol(Protocol):
    def execute(self, request: Any, custom_backend: Any | None = None) -> Any: ...


def _ensure_howlplane_on_path() -> None:
    """Discover an explicit HowlPlane checkout in current or legacy layout."""
    env_root = os.environ.get("HOWLPLANE_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
        source_root = p / "src"
        if (source_root / "howlplane" / "control_plane").is_dir():
            if str(source_root) not in sys.path:
                sys.path.insert(0, str(source_root))


def _try_import_howlplane() -> tuple[Any, Any, Any, Any, Any] | None:
    _ensure_howlplane_on_path()
    try:
        from howlplane.control_plane.role_binding import (
            IndependenceStatus,
            RoleBindingRegistry,
            RoleDispatcher,
            RoleExecutionRequest,
            get_default_role_registry,
        )
        return (
            RoleDispatcher,
            RoleBindingRegistry,
            RoleExecutionRequest,
            get_default_role_registry,
            IndependenceStatus,
        )
    except ImportError:
        try:
            from src.control_plane.role_binding import (
                IndependenceStatus,
                RoleBindingRegistry,
                RoleDispatcher,
                RoleExecutionRequest,
                get_default_role_registry,
            )
            return (
                RoleDispatcher,
                RoleBindingRegistry,
                RoleExecutionRequest,
                get_default_role_registry,
                IndependenceStatus,
            )
        except ImportError:
            return None


class HowlPlaneWritingBridge:
    """Executes HowlWriter writing roles via HowlPlane."""

    def __init__(
        self,
        dispatcher: Any | None = None,
        registry: Any | None = None,
    ) -> None:
        imported = _try_import_howlplane()
        if imported is not None:
            disp_cls, _, _, get_def_reg, _ = imported
            self.registry = (
                registry if registry is not None else get_def_reg()
            )
            self.dispatcher = (
                dispatcher
                if dispatcher is not None
                else disp_cls(binding_registry=self.registry)
            )
        else:
            self.registry = registry
            self.dispatcher = dispatcher
        # A model chosen for this process (CLI) when no role binding exists.
        self.session_provider: str | None = None
        self.review_provider: str | None = None
        self.remote_confirmed: set[str] = set()
        self.no_model = False
        #: Asks the person which model to use: (role, avoid=None) -> (provider, confirmed).
        self.chooser: Callable[..., tuple[str, bool]] | None = None
        defaults = provider_choice.PROCESS_DEFAULTS
        if defaults.get("writer"):
            self.use_provider(defaults["writer"])
        if defaults.get("reviewer"):
            self.use_provider(defaults["reviewer"], review=True)
        if defaults.get("interactive"):
            self.chooser = provider_choice.interactive_chooser()

    def is_available(self) -> bool:
        return self.dispatcher is not None

    def _bound_provider(self, role: WritingRole) -> str | None:
        if not self.is_available() or self.registry is None:
            return None
        binding = self.registry.get_binding("writing", role.value)
        return binding.provider if binding is not None and binding.provider else None

    def is_role_configured(self, role: WritingRole) -> bool:
        """Whether `role` can run: bound, chosen, or (on a terminal) the person picks a model now.

        Callers use this to decide between a model step and a rule-based one,
        so this is where the person is asked; "continue without a model" makes it False.
        """
        if self._bound_provider(role) is not None:
            return True
        if self.no_model or provider_choice.REQUEST_NO_MODEL.get():
            return False
        if provider_choice.REQUEST_PROVIDER.get() or self.session_provider:
            return self.is_available()
        if self.chooser is None or not self.is_available():
            return False
        try:
            return self.chosen_provider(role) is not None
        except ModelRoleNotConfiguredError:
            if self.no_model:
                return False
            raise

    def use_provider(self, provider: str, *, confirmed: bool = False, review: bool = False) -> str:
        """Use `provider` for this process's writing roles (or its independent reviews)."""
        provider = provider_choice.normalize(provider)
        if review:
            self.review_provider = provider
        else:
            self.session_provider = provider
        if confirmed:
            self.remote_confirmed.add(provider)
        return provider

    def chosen_provider(self, role: WritingRole, avoid_provider: str | None = None) -> str | None:
        """The model the person chose for this call, asking if needed.

        None means a HowlPlane role binding applies (unchanged behaviour).
        Raises ModelRoleNotConfiguredError when nothing is bound or chosen.
        """
        provider = provider_choice.REQUEST_PROVIDER.get() or self.session_provider
        if provider is None:
            if self._bound_provider(role) is not None:
                return None
            if self.chooser is None:
                raise ModelRoleNotConfiguredError(role)
            if self.no_model:
                raise ModelRoleNotConfiguredError(role, detail="you chose to continue without a model")
            try:
                chosen, confirmed = self.chooser(role)
            except provider_choice.ProviderChoiceCancelled as error:
                raise ModelRoleNotConfiguredError(role, detail=str(error)) from error
            if chosen == provider_choice.NO_MODEL:
                self.no_model = True
                raise ModelRoleNotConfiguredError(role, detail="you chose to continue without a model")
            provider = self.use_provider(chosen, confirmed=confirmed)
        if avoid_provider and _same(provider, avoid_provider):
            review = provider_choice.REQUEST_REVIEW_PROVIDER.get() or self.review_provider
            if review is None and self.chooser is not None:
                try:
                    chosen, confirmed = self.chooser(role, avoid=avoid_provider)
                except provider_choice.ProviderChoiceCancelled as error:
                    raise ModelRoleNotConfiguredError(role, detail=str(error)) from error
                review = self.use_provider(chosen, confirmed=confirmed, review=True)
            # With no reviewer chosen the same model reviews, recorded as SAME_PROVIDER:
            # never a silent switch to a model the person did not pick.
            provider = review or provider
        return provider

    def require_decision(self, role: WritingRole) -> None:
        """Web: stop (HTTP 409, the page asks) until a model or "no model" is chosen.

        Nothing is sent before this passes. A bound role, or no HowlPlane at all
        (nothing to choose), needs no decision.
        """
        if (
            not self.is_available()
            or self._bound_provider(role) is not None
            or self.no_model
            or self.session_provider
            or provider_choice.REQUEST_NO_MODEL.get()
            or provider_choice.REQUEST_PROVIDER.get()
        ):
            return
        raise ModelRoleNotConfiguredError(role)

    def is_remote_confirmed(self, provider: str | None) -> bool:
        if not provider:
            return False
        provider = provider_choice.normalize(provider)
        if provider_choice.REQUEST_CONFIRMED.get() and provider in (
            provider_choice.REQUEST_PROVIDER.get(),
            provider_choice.REQUEST_REVIEW_PROVIDER.get(),
        ):
            return True
        return provider in self.remote_confirmed

    def execute_writing_role(
        self,
        role: WritingRole,
        prompt: str,
        system_instruction: str | None = None,
        context: dict[str, Any] | None = None,
        avoid_provider: str | None = None,
        preferred_provider: str | None = None,
        timeout_seconds: int = 300,
        structured_schema: dict[str, Any] | None = None,
        cwd: Path | str | None = None,
        custom_backend: Any | None = None,
    ) -> Any:
        """Invokes a WritingRole through HowlPlane."""
        if not self.is_available() and custom_backend is None:
            raise ModelRoleNotConfiguredError(role)

        if custom_backend is None and preferred_provider is None:
            chosen = self.chosen_provider(role, avoid_provider)
            if chosen is not None:
                custom_backend = _backend_for(chosen)

        imported = _try_import_howlplane()
        if imported is None and custom_backend is None:
            raise ModelRoleNotConfiguredError(role)

        req_cls = imported[2] if imported else None
        if req_cls is None:
            raise ModelRoleNotConfiguredError(role)

        # Model backends are agent CLIs that may read or edit their working
        # directory (agy and Codex may edit it in writing roles). Writing roles
        # get everything they need in the prompt, so they always run in an
        # empty private directory, never the user's folder or the caller's
        # `cwd` (kept in the request context for provenance only).
        sandbox = tempfile.mkdtemp(prefix="howlwriter-model-")
        if cwd:
            context = {**(context or {}), "requested_cwd": str(cwd)}
        request = req_cls(
            domain="writing",
            role=role.value,
            prompt=prompt,
            system_instruction=system_instruction,
            context=context or {},
            avoid_provider=avoid_provider,
            preferred_provider=preferred_provider,
            timeout_seconds=timeout_seconds,
            structured_output_schema=structured_schema,
            cwd=sandbox,
        )

        # Captured here, and only here. This is the last point at which the
        # exact strings being sent are still in hand, so provenance never has
        # to re-render a prompt afterwards and claim it is the one that ran.
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = self.dispatcher.execute(request, custom_backend=custom_backend)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        capture_call(
            role=role.value,
            prompt=prompt,
            system_instruction=system_instruction,
            result=result,
            avoid_provider=avoid_provider,
            started_at=started_at,
        )

        if not result.success and "No executor or provider configured" in (result.error_message or ""):
            raise ModelRoleNotConfiguredError(role)

        return result


def _same(a: str, b: str) -> bool:
    def canonical(value: str) -> str:
        try:
            return provider_choice.normalize(value)
        except ValueError:
            return value.strip().lower()

    return canonical(a) == canonical(b)


def _backend_for(provider: str) -> Any:
    """The HowlPlane backend for exactly this provider (no automatic alternates)."""
    _ensure_howlplane_on_path()
    from howlplane.control_plane.agent_execution import AgentBackendRegistry

    return AgentBackendRegistry.get_backend(provider)


_GLOBAL_BRIDGE: HowlPlaneWritingBridge | None = None


def get_howlplane_bridge() -> HowlPlaneWritingBridge:
    global _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None:
        _GLOBAL_BRIDGE = HowlPlaneWritingBridge()
    return _GLOBAL_BRIDGE


def set_howlplane_bridge(bridge: HowlPlaneWritingBridge | None) -> None:
    global _GLOBAL_BRIDGE
    _GLOBAL_BRIDGE = bridge
