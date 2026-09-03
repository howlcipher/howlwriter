"""Test doubles for HowlPlane control-plane interfaces.

Enables HowlWriter's model-boundary and dogfood test suites to execute
hermetically in clean CI environments where HowlPlane is not installed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import sys
import time
import types
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml


class IndependenceStatus(str, Enum):
    """Observable status of reviewer independence."""

    INDEPENDENT = "INDEPENDENT"
    SAME_PROVIDER = "SAME_PROVIDER"
    NOT_REVIEWED = "NOT_REVIEWED"
    UNAVAILABLE = "UNAVAILABLE"


class RoleExecutionError(RuntimeError):
    """Base error for role execution failures."""

    pass


class RoleNotConfiguredError(RoleExecutionError):
    """Raised when a requested domain role has no executor configured."""

    def __init__(self, domain: str, role: str) -> None:
        self.domain = domain
        self.role = role
        super().__init__(
            f"No executor or provider configured for role '{role}' in domain '{domain}'."
        )


@dataclass
class RoleDescriptor:
    """Declarative description of a role across any domain."""

    domain: str
    role: str
    capability: str
    description: str = ""
    default_provider: Optional[str] = None
    default_model: Optional[str] = None
    requires_reviewer_independence: bool = False


@dataclass
class RoleBinding:
    """Explicit binding of a (domain, role) pair to a provider/executor."""

    domain: str
    role: str
    provider: str
    model: Optional[str] = None
    interface: Optional[str] = None
    capability: Optional[str] = None
    timeout_seconds: int = 300
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema: str = "howlplane.role_binding/v1"


@dataclass
class RoleExecutionRequest:
    """Structured invocation request for a domain role."""

    domain: str
    role: str
    prompt: str
    capability: Optional[str] = None
    system_instruction: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    avoid_provider: Optional[str] = None
    preferred_provider: Optional[str] = None
    timeout_seconds: int = 300
    structured_output_schema: Optional[Dict[str, Any]] = None
    cwd: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentExecutionResult:
    """Execution result from an underlying agent backend."""

    agent_id: str
    role: str = ""
    command: str = ""
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    success: bool = True
    timed_out: bool = False
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RoleExecutionResult:
    """Result of executing a domain role through HowlPlane."""

    domain: str
    role: str
    provider: str
    model: Optional[str] = None
    success: bool = True
    raw_output: str = ""
    structured_output: Optional[Dict[str, Any]] = None
    duration_seconds: float = 0.0
    independence_status: str = "INDEPENDENT"
    error_message: Optional[str] = None
    timed_out: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_structured_output(text: str) -> Optional[Dict[str, Any]]:
    """Extracts JSON or YAML object from model output text or code blocks."""
    if not text or not text.strip():
        return None

    clean = text.strip()

    # 1. Try fenced code blocks
    matches = re.findall(r"```(?:yaml|json)?\s*\n([\s\S]*?)\n```", clean)
    for block in matches:
        candidate = block.strip()
        try:
            parsed = yaml.safe_load(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            try:
                parsed_json = json.loads(candidate)
                if isinstance(parsed_json, dict):
                    return parsed_json
            except Exception:
                pass

    # 2. Extract from Codex/CLI transcript if present
    codex_match = re.search(
        r"(?:^|\n)codex\s*\n([\s\S]*?)(?:\ntokens used|\Z)",
        clean,
        re.IGNORECASE,
    )
    if codex_match:
        sub_text = codex_match.group(1).strip()
        sub_matches = re.findall(
            r"```(?:yaml|json)?\s*\n([\s\S]*?)\n```", sub_text
        )
        for block in sub_matches:
            try:
                parsed = yaml.safe_load(block.strip())
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        try:
            parsed = yaml.safe_load(sub_text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # 3. Direct parse
    try:
        parsed_json = json.loads(clean)
        if isinstance(parsed_json, dict):
            return parsed_json
    except Exception:
        pass

    try:
        parsed_yaml = yaml.safe_load(clean)
        if isinstance(parsed_yaml, dict):
            return parsed_yaml
    except Exception:
        pass

    # 4. JSON substring
    first_b = clean.find("{")
    last_b = clean.rfind("}")
    if first_b != -1 and last_b != -1 and last_b > first_b:
        try:
            parsed_json = json.loads(clean[first_b : last_b + 1])
            if isinstance(parsed_json, dict):
                return parsed_json
        except Exception:
            pass

    return None


class RoleBindingRegistry:
    """Registry mapping domain roles to providers for tests."""

    def __init__(self) -> None:
        self._bindings: Dict[Tuple[str, str], RoleBinding] = {}
        self._descriptors: Dict[Tuple[str, str], RoleDescriptor] = {}

    def register_descriptor(self, descriptor: RoleDescriptor) -> None:
        key = (descriptor.domain.lower(), descriptor.role.lower())
        self._descriptors[key] = descriptor

    def register_binding(self, binding: RoleBinding) -> None:
        key = (binding.domain.lower(), binding.role.lower())
        self._bindings[key] = binding

    def get_binding(self, domain: str, role: str) -> Optional[RoleBinding]:
        key = (domain.lower(), role.lower())
        return self._bindings.get(key)

    def get_descriptor(self, domain: str, role: str) -> Optional[RoleDescriptor]:
        key = (domain.lower(), role.lower())
        return self._descriptors.get(key)

    def list_bindings(self, domain: Optional[str] = None) -> List[RoleBinding]:
        if domain is None:
            return list(self._bindings.values())
        return [b for b in self._bindings.values() if b.domain.lower() == domain.lower()]

    def clear(self) -> None:
        self._bindings.clear()
        self._descriptors.clear()


_GLOBAL_REGISTRY = RoleBindingRegistry()


def get_default_role_registry() -> RoleBindingRegistry:
    return _GLOBAL_REGISTRY


class AgentBackend:
    """Abstract agent backend base class."""

    pass


class FakeAgentBackend(AgentBackend):
    """Deterministic fake agent backend for automated tests."""

    def __init__(
        self,
        agent_id: str = "fake_agent",
        default_exit_code: int = 0,
        default_stdout: str = "Fake implementation completed successfully. No issues found.",
        default_stderr: str = "",
        side_effect: Optional[Callable[[Any, Path, str], None]] = None,
        duration: float = 0.05,
        default_timed_out: bool = False,
        default_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.agent_id = agent_id
        self.default_exit_code = default_exit_code
        self.default_stdout = default_stdout
        self.default_stderr = default_stderr
        self.side_effect = side_effect
        self.duration = duration
        self.default_timed_out = default_timed_out
        self.default_metadata = dict(default_metadata or {})
        self.executed_calls: List[Dict[str, Any]] = []

    def is_available(self) -> bool:
        return True

    def execute(
        self,
        task: Any = None,
        cwd: Union[str, Path] = ".",
        role: str = "implementation",
        prompt_override: Optional[str] = None,
        timeout_seconds: int = 300,
        env_vars: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AgentExecutionResult:
        target_cwd = Path(cwd).resolve()
        prompt = prompt_override or f"Fake execute: {role}"
        self.executed_calls.append(
            {
                "task_id": "test_task",
                "role": role,
                "prompt": prompt,
                "cwd": str(target_cwd),
            }
        )

        if self.side_effect:
            try:
                self.side_effect(task, target_cwd, prompt)
            except Exception as exc:
                return AgentExecutionResult(
                    agent_id=self.agent_id,
                    role=role,
                    command=f"fake_agent({self.agent_id})",
                    exit_code=1,
                    stdout="",
                    stderr=f"Side effect error: {exc}",
                    duration_seconds=self.duration,
                    success=False,
                    error_message=str(exc),
                )

        ok = self.default_exit_code == 0
        return AgentExecutionResult(
            agent_id=self.agent_id,
            role=role,
            command=f"fake_agent({self.agent_id})",
            exit_code=self.default_exit_code,
            stdout=self.default_stdout,
            stderr=self.default_stderr,
            duration_seconds=self.duration,
            success=ok,
            timed_out=self.default_timed_out,
            error_message=None if ok else f"Exit code {self.default_exit_code}",
            metadata=dict(self.default_metadata),
        )


class RoleDispatcher:
    """Resolves and executes domain roles through fake or supplied backends."""

    def __init__(
        self,
        binding_registry: Optional[RoleBindingRegistry] = None,
        agent_registry: Any = None,
    ) -> None:
        self.binding_registry = binding_registry or get_default_role_registry()

    def resolve_provider(
        self,
        domain: str,
        role: str,
        avoid_provider: Optional[str] = None,
        preferred_provider: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], str]:
        binding = self.binding_registry.get_binding(domain, role)
        candidate = preferred_provider or (binding.provider if binding else None)
        model_id = binding.model if binding else None

        if not candidate:
            return None, None, IndependenceStatus.UNAVAILABLE.value

        if not avoid_provider:
            return candidate, model_id, IndependenceStatus.NOT_REVIEWED.value

        if candidate != avoid_provider:
            return candidate, model_id, IndependenceStatus.INDEPENDENT.value

        return candidate, model_id, IndependenceStatus.SAME_PROVIDER.value

    def execute(
        self,
        request: RoleExecutionRequest,
        custom_backend: Optional[AgentBackend] = None,
        backend_resolver: Any = None,
    ) -> RoleExecutionResult:
        start_time = time.time()

        if custom_backend is not None:
            provider_id = getattr(custom_backend, "agent_id", "custom_backend")
            independence_status = (
                IndependenceStatus.INDEPENDENT.value
                if request.avoid_provider != provider_id
                else IndependenceStatus.SAME_PROVIDER.value
            )
            model_id = None
        else:
            provider_id, model_id, independence_status = self.resolve_provider(
                domain=request.domain,
                role=request.role,
                avoid_provider=request.avoid_provider,
                preferred_provider=request.preferred_provider,
            )

        if not provider_id:
            return RoleExecutionResult(
                domain=request.domain,
                role=request.role,
                provider="none",
                model=None,
                success=False,
                duration_seconds=0.0,
                independence_status=IndependenceStatus.UNAVAILABLE.value,
                error_message=(
                    f"No executor or provider configured for role '{request.role}' in domain '{request.domain}'."
                ),
                metadata={"request": request.to_dict()},
            )

        backend = custom_backend
        if backend is None and backend_resolver is not None:
            backend = backend_resolver(provider_id)

        if backend is None:
            return RoleExecutionResult(
                domain=request.domain,
                role=request.role,
                provider=provider_id,
                model=model_id,
                success=False,
                duration_seconds=0.0,
                independence_status=independence_status,
                error_message=(
                    f"No executor or provider configured for role '{request.role}' in domain '{request.domain}'."
                ),
                metadata={"request": request.to_dict()},
            )

        target_cwd = Path(request.cwd).resolve() if request.cwd else Path.cwd()
        full_prompt = request.prompt
        if request.system_instruction:
            full_prompt = f"{request.system_instruction}\n\n{request.prompt}"

        try:
            agent_res = backend.execute(
                task=None,
                cwd=target_cwd,
                role=f"{request.domain}:{request.role}",
                prompt_override=full_prompt,
                timeout_seconds=request.timeout_seconds,
            )
        except Exception as exc:
            elapsed = round(time.time() - start_time, 3)
            return RoleExecutionResult(
                domain=request.domain,
                role=request.role,
                provider=provider_id,
                model=model_id,
                success=False,
                duration_seconds=elapsed,
                independence_status=independence_status,
                error_message=f"Backend execution exception: {exc}",
                metadata={"request": request.to_dict()},
            )

        elapsed = round(time.time() - start_time, 3)
        if not agent_res.success:
            err = agent_res.error_message or agent_res.stderr or "Provider execution failed"
            return RoleExecutionResult(
                domain=request.domain,
                role=request.role,
                provider=provider_id,
                model=model_id,
                success=False,
                raw_output=agent_res.stdout,
                duration_seconds=elapsed,
                independence_status=independence_status,
                error_message=err,
                timed_out=agent_res.timed_out,
                metadata={
                    "request": request.to_dict(),
                    "agent_result": agent_res.to_dict(),
                },
            )

        raw_output = agent_res.stdout
        structured = extract_structured_output(raw_output)
        return RoleExecutionResult(
            domain=request.domain,
            role=request.role,
            provider=provider_id,
            model=model_id,
            success=True,
            raw_output=raw_output,
            structured_output=structured,
            duration_seconds=elapsed,
            independence_status=independence_status,
            error_message=None,
            timed_out=agent_res.timed_out,
            metadata={
                "request": request.to_dict(),
                "agent_result": agent_res.to_dict(),
            },
        )


def install_control_plane_fakes() -> None:
    """Injects control_plane fakes into sys.modules if not already present."""
    if "src.control_plane" in sys.modules and "src.control_plane.role_binding" in sys.modules:
        return

    cp_pkg = types.ModuleType("src.control_plane")
    rb_mod = types.ModuleType("src.control_plane.role_binding")
    ae_mod = types.ModuleType("src.control_plane.agent_execution")

    rb_mod.IndependenceStatus = IndependenceStatus
    rb_mod.RoleExecutionError = RoleExecutionError
    rb_mod.RoleNotConfiguredError = RoleNotConfiguredError
    rb_mod.RoleDescriptor = RoleDescriptor
    rb_mod.RoleBinding = RoleBinding
    rb_mod.RoleExecutionRequest = RoleExecutionRequest
    rb_mod.RoleExecutionResult = RoleExecutionResult
    rb_mod.RoleBindingRegistry = RoleBindingRegistry
    rb_mod.get_default_role_registry = get_default_role_registry
    rb_mod.RoleDispatcher = RoleDispatcher
    rb_mod.extract_structured_output = extract_structured_output

    ae_mod.AgentExecutionResult = AgentExecutionResult
    ae_mod.AgentBackend = AgentBackend
    ae_mod.FakeAgentBackend = FakeAgentBackend

    sys.modules["src.control_plane"] = cp_pkg
    sys.modules["src.control_plane.role_binding"] = rb_mod
    sys.modules["src.control_plane.agent_execution"] = ae_mod
