"""Provider inspection and HowlPlane role bindings endpoint."""

from __future__ import annotations

import shutil
from fastapi import APIRouter

from howlwriter.integration.howlplane_bridge import get_howlplane_bridge
from howlwriter.integration.model_role import WritingRole
from howlwriter.web.models import (
    ProviderStatusDto,
    ProvidersResponse,
    RoleBindingDto,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])

ROLE_DESCRIPTIONS = {
    WritingRole.WRITER: (
        "Drafts structured academic and long-form prose conforming to specifications and sources."
    ),
    WritingRole.RESEARCHER: (
        "Discovers scholarly literature, gathers citations, and extracts evidence passages."
    ),
    WritingRole.HUMANIZER: (
        "Transforms synthetic/AI-style phrasing into natural prose while preserving factual meaning."
    ),
    WritingRole.FINAL_REVIEWER: (
        "Performs independent semantic review to falsify meaning preservation after transformation."
    ),
    WritingRole.EDITOR: (
        "Normalizes whitespace, structural elements, and typographical conventions."
    ),
    WritingRole.VOICE_REVIEWER: (
        "Evaluates voice alignment and stylistic variance against target voice profiles."
    ),
}

KNOWN_BACKENDS = [
    ("agy", "Antigravity CLI (AGY)", "Google DeepMind agentic coding and analysis CLI"),
    ("claude", "Claude Code", "Anthropic Claude Code standalone agent CLI"),
    ("codex", "Codex CLI", "OpenAI Codex standalone execution CLI"),
    ("devin", "Devin CLI", "Cognition Devin execution CLI"),
    ("ollama", "Local Ollama", "Local Ollama private model server"),
]


@router.get("", response_model=ProvidersResponse)
def get_providers() -> ProvidersResponse:
    bridge = get_howlplane_bridge()
    is_avail = bridge.is_available()

    role_dtos: list[RoleBindingDto] = []
    bindings_map: dict[str, str] = {}

    for role_enum in (
        WritingRole.WRITER,
        WritingRole.RESEARCHER,
        WritingRole.HUMANIZER,
        WritingRole.FINAL_REVIEWER,
        WritingRole.EDITOR,
        WritingRole.VOICE_REVIEWER,
    ):
        role_name = role_enum.value
        is_conf = bridge.is_role_configured(role_enum) if is_avail else False
        provider = None
        model = None
        timeout = 300

        if is_avail and bridge.registry:
            binding = bridge.registry.get_binding("writing", role_name)
            if binding:
                provider = binding.provider
                model = binding.model
                timeout = binding.timeout_seconds

        if provider:
            bindings_map[role_name] = provider

        role_dtos.append(
            RoleBindingDto(
                role=role_name,
                role_label=role_name.replace("_", " ").title(),
                domain="writing",
                provider=provider,
                model=model,
                is_configured=is_conf,
                timeout_seconds=timeout,
                description=ROLE_DESCRIPTIONS.get(role_enum, ""),
            )
        )

    # Calculate reviewer independence
    humanizer_p = bindings_map.get("humanizer")
    reviewer_p = bindings_map.get("final_reviewer")

    if not is_avail:
        indep_status = "UNAVAILABLE"
        indep_reason = "HowlPlane control plane is not currently available in this environment."
    elif not humanizer_p:
        indep_status = "NOT_REVIEWED"
        indep_reason = "Humanizer role is not currently configured with a model provider."
    elif not reviewer_p:
        indep_status = "NOT_REVIEWED"
        indep_reason = (
            "Final Reviewer role is not configured. "
            "Humanizer outputs will not undergo independent verification."
        )
    elif humanizer_p.lower() == reviewer_p.lower():
        indep_status = "SAME_PROVIDER"
        indep_reason = (
            f"Both Humanizer and Final Reviewer are bound to '{humanizer_p}'. "
            "Reviewer independence guarantee is void."
        )
    else:
        indep_status = "INDEPENDENT"
        indep_reason = (
            f"Humanizer ({humanizer_p}) and Final Reviewer ({reviewer_p}) "
            "are distinct providers, providing independent verification."
        )

    # Detect installed CLI tools
    available_providers: list[ProviderStatusDto] = []
    for bid, name, desc in KNOWN_BACKENDS:
        cmd = shutil.which(bid)
        available_providers.append(
            ProviderStatusDto(
                id=bid,
                name=name,
                is_installed=bool(cmd),
                command_path=cmd,
                description=desc,
            )
        )

    return ProvidersResponse(
        bridge_available=is_avail,
        role_bindings=role_dtos,
        available_providers=available_providers,
        reviewer_independence=indep_status,
        reviewer_independence_reason=indep_reason,
    )
