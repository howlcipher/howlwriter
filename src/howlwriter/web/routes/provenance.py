"""Read-only inspection of a run's generation provenance.

Read-only on purpose. A provenance record is evidence about a run that already
happened; an endpoint that could alter one would make every other record worth
less. Nothing here writes, and nothing recomputes -- the record is served as it
was captured.

The privacy stance matches `/api/voices`, which returns summaries by default
and source paths only on explicit request. A provenance record at full level
contains every prompt HowlWriter built, and those prompts contain the user's
own sentences, so prompt text is withheld unless the caller asks for it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from howlwriter.domain.generation_provenance import (
    LEVEL_FULL,
    LEVEL_SUMMARY,
    GenerationProvenance,
)
from howlwriter.provenance.assemble import finalize, load_provenance
from howlwriter.provenance.manifest import render_manifest

router = APIRouter(prefix="/api/provenance", tags=["provenance"])


def _timeline(provenance: GenerationProvenance) -> list[dict[str, Any]]:
    """Stages in execution order, each with the model calls it made.

    Built from the recorded stages and calls rather than from a fixed list of
    pipeline steps, so a run that skipped a stage shows it missing instead of
    showing it as though it had run.
    """
    calls_by_sequence = {call.sequence: call for call in provenance.calls}
    nodes: list[dict[str, Any]] = []

    for stage in provenance.stages:
        stage_calls = [
            calls_by_sequence[seq]
            for seq in stage.call_sequences
            if seq in calls_by_sequence
        ]
        nodes.append(
            {
                "name": stage.name,
                "sequence": stage.sequence,
                "status": stage.status,
                "model_backed": stage.model_backed,
                "duration_seconds": stage.duration_seconds,
                "detail": stage.detail,
                "output_sha256": stage.output_sha256,
                "calls": [c.sequence for c in stage_calls],
            }
        )

    # Calls made outside any recorded stage still belong on the timeline; a
    # model invocation that no stage claims is exactly the thing an inspector
    # should surface rather than hide.
    claimed = {seq for stage in provenance.stages for seq in stage.call_sequences}
    for call in provenance.calls:
        if call.sequence not in claimed:
            nodes.append(
                {
                    "name": call.role,
                    "sequence": 1000 + call.sequence,
                    "status": "OK" if call.success else "FAILED",
                    "model_backed": True,
                    "duration_seconds": call.duration_seconds,
                    "detail": "not attributed to a recorded stage",
                    "output_sha256": call.response_sha256,
                    "calls": [call.sequence],
                }
            )
    return sorted(nodes, key=lambda node: node["sequence"])


@router.get("/{run_id}")
def get_provenance(
    run_id: str,
    include_prompts: bool = Query(
        False,
        description=(
            "Include the exact prompts HowlWriter sent. Withheld by default: "
            "they contain the user's own text."
        ),
    ),
) -> dict[str, Any]:
    provenance = load_provenance(run_id)
    if provenance is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no provenance record for run {run_id!r}. Runs record "
                "provenance only when they generate; older runs have none."
            ),
        )

    level = LEVEL_FULL if include_prompts else LEVEL_SUMMARY
    served = finalize(provenance, level=level)
    payload = served.to_dict()
    payload["timeline"] = _timeline(served)
    payload["manifest"] = render_manifest(served)
    payload["prompts_included"] = include_prompts
    payload["providers_used"] = served.providers_used()
    payload["models_used"] = served.models_used()
    payload["unknown_model_calls"] = len(served.unknown_model_calls())
    payload["reviewer_independence"] = served.reviewer_independence()
    # A record stored at summary level cannot be served at full level. Say so,
    # rather than returning empty prompts that read as "no prompt was sent".
    if include_prompts and not any(c.user_prompt for c in served.calls):
        payload["prompt_note"] = (
            "this run was recorded at summary level, so the prompt text was "
            "never persisted; the hashes and lengths are still exact"
        )
    return payload


@router.get("/{run_id}/manifest")
def get_manifest(run_id: str) -> dict[str, str]:
    provenance = load_provenance(run_id)
    if provenance is None:
        raise HTTPException(status_code=404, detail=f"no provenance record for {run_id!r}")
    return {"run_id": run_id, "manifest": render_manifest(provenance)}
