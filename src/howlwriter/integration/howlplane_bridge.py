"""Bridge binding HowlWriter WritingRoles to HowlPlane's role execution framework.

Allows HowlWriter to request capabilities from HowlPlane without creating a
parallel provider-routing system inside HowlWriter.
HowlWriter owns the semantics of writing roles.
HowlPlane owns execution, provider resolution, reviewer independence, and control.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from howlwriter.integration.model_role import (
    ModelRoleNotConfiguredError,
    WritingRole,
)
from howlwriter.integration.provenance_capture import capture_call

# Optional dynamic discovery of HowlPlane source tree if not directly in sys.path
_KNOWN_HOWLPLANE_PATHS = [
    Path("/run/media/system/tallgeese/dev/howlplane"),
    Path(__file__).resolve().parents[4] / "howlplane",
]

for p in _KNOWN_HOWLPLANE_PATHS:
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _try_import_howlplane() -> tuple[Any, Any, Any, Any, Any] | None:
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

    def is_available(self) -> bool:
        return self.dispatcher is not None

    def is_role_configured(self, role: WritingRole) -> bool:
        if not self.is_available() or self.registry is None:
            return False
        binding = self.registry.get_binding("writing", role.value)
        return binding is not None and bool(binding.provider)

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

        if not self.is_role_configured(role) and custom_backend is None and preferred_provider is None:
            raise ModelRoleNotConfiguredError(role)

        imported = _try_import_howlplane()
        if imported is None and custom_backend is None:
            raise ModelRoleNotConfiguredError(role)

        req_cls = imported[2] if imported else None
        if req_cls is None:
            raise ModelRoleNotConfiguredError(role)

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
            cwd=str(cwd) if cwd else None,
        )

        # Captured here, and only here. This is the last point at which the
        # exact strings being sent are still in hand, so provenance never has
        # to re-render a prompt afterwards and claim it is the one that ran.
        started_at = datetime.now(timezone.utc).isoformat()
        result = self.dispatcher.execute(request, custom_backend=custom_backend)
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


_GLOBAL_BRIDGE: HowlPlaneWritingBridge | None = None


def get_howlplane_bridge() -> HowlPlaneWritingBridge:
    global _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None:
        _GLOBAL_BRIDGE = HowlPlaneWritingBridge()
    return _GLOBAL_BRIDGE


def set_howlplane_bridge(bridge: HowlPlaneWritingBridge | None) -> None:
    global _GLOBAL_BRIDGE
    _GLOBAL_BRIDGE = bridge
