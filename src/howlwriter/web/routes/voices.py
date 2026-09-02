"""Personal-voice endpoints for the local web application.

Bounded on purpose. The UI can list local voices, show what one learned, and
kick off a rebuild through the job manager that already drives the academic
pipeline. It cannot create a voice from scratch -- choosing which directories
on a machine to read is a decision that belongs at the command line, where
the user can see exactly what they are pointing at.

Everything returned here is a summary. No corpus passage is ever serialized,
and the source-file list is behind an explicit query parameter rather than
included by default: a browser tab is a bad place for a map of someone's
drive to appear by accident.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from howlwriter.domain.voice import TraitValue, VoiceProfile
from howlwriter.voice.corpus.build import STAGES, build_voice
from howlwriter.voice.corpus.store import VoiceStore, validate_name
from howlwriter.web.jobs import Job, get_job_manager
from howlwriter.web.models import (
    VoiceBuildResultDto,
    VoiceContextDto,
    VoiceCorpusSummaryDto,
    VoiceDetailDto,
    VoiceOverridesDto,
    VoiceRebuildRequest,
    VoiceSummaryDto,
    VoiceTraitDto,
    VoiceValidationDto,
)

router = APIRouter(prefix="/api/voices", tags=["voices"])


def _band(confidence: float) -> str:
    if confidence >= 0.75:
        return "HIGH"
    if confidence >= 0.5:
        return "MEDIUM"
    if confidence >= 0.3:
        return "LOW"
    return "VERY_LOW"


def _trait_dto(name: str, trait: TraitValue) -> VoiceTraitDto:
    return VoiceTraitDto(
        name=name,
        value=trait.value,
        confidence=trait.confidence,
        confidence_band=_band(trait.confidence),
        supporting_documents=trait.supporting_documents,
        supporting_words=trait.supporting_words,
        agreement=trait.agreement,
        source=trait.source,
    )


def _detail(name: str, profile: VoiceProfile) -> VoiceDetailDto:
    summary = profile.corpus_summary
    validation = profile.validation
    overrides = profile.overrides
    distributions = profile.distributions

    return VoiceDetailDto(
        name=name,
        profile_type=profile.profile_type,
        built_at=profile.built_at,
        version=profile.version,
        traits=[
            _trait_dto(trait_name, trait)
            for trait_name, trait in sorted(
                profile.traits.items(), key=lambda kv: -kv[1].confidence
            )
        ],
        contexts=[
            VoiceContextDto(
                name=context.name or context_name,
                document_count=context.document_count,
                word_count=context.word_count,
                confidence=context.confidence,
                sufficiency=context.sufficiency,
                traits=[
                    _trait_dto(trait_name, trait)
                    for trait_name, trait in sorted(
                        context.traits.items(), key=lambda kv: -kv[1].confidence
                    )
                ],
            )
            for context_name, context in sorted(profile.contexts.items())
        ],
        corpus=(
            VoiceCorpusSummaryDto(**summary.to_dict()) if summary else VoiceCorpusSummaryDto()
        ),
        validation=(
            VoiceValidationDto(**validation.to_dict()) if validation else VoiceValidationDto()
        ),
        overrides=(
            VoiceOverridesDto(**overrides.to_dict()) if overrides else VoiceOverridesDto()
        ),
        warnings=list(profile.warnings),
        distributions={
            key: value
            for key, value in (distributions.to_dict() if distributions else {}).items()
            if isinstance(value, (int, float))
        },
    )


def _load(name: str) -> tuple[VoiceStore, VoiceProfile]:
    try:
        store = VoiceStore(validate_name(name))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        profile = store.load_profile()
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    try:
        profile.overrides = store.load_overrides()
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return store, profile


@router.get("", response_model=list[VoiceSummaryDto])
async def list_voices() -> list[VoiceSummaryDto]:
    """Every local voice, as one summary row each."""
    summaries: list[VoiceSummaryDto] = []
    for name in VoiceStore.list_names():
        try:
            profile = VoiceStore(name).load_profile()
        except (OSError, ValueError, FileNotFoundError):
            continue
        corpus = profile.corpus_summary
        validation = profile.validation
        summaries.append(VoiceSummaryDto(
            name=name,
            profile_type=profile.profile_type,
            built_at=profile.built_at,
            included_documents=corpus.included_documents if corpus else 0,
            training_words=corpus.training_words if corpus else 0,
            contexts=sorted(profile.contexts),
            overall_confidence=validation.overall_confidence if validation else "UNKNOWN",
            sufficiency=corpus.sufficiency if corpus else "unknown",
        ))
    return summaries


@router.get("/{name}", response_model=VoiceDetailDto)
async def get_voice(name: str) -> VoiceDetailDto:
    _store, profile = _load(name)
    return _detail(name, profile)


@router.get("/{name}/sources")
async def get_voice_sources(
    name: str,
    confirm: bool = Query(
        False,
        description=(
            "Must be true. The source list names local files and is withheld "
            "unless it is explicitly asked for."
        ),
    ),
) -> dict:
    """List the local files a voice was built from.

    Gated behind an explicit flag rather than returned with the detail
    payload, so a UI cannot surface someone's file paths without meaning to.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "The source list is private local data. Request it with "
                "?confirm=true to acknowledge that it names files on this machine."
            ),
        )
    store, _profile = _load(name)
    return {
        "name": store.name,
        "sources": [
            {
                "path": record.path,
                "words": record.words,
                "context": record.context,
                "classification": record.classification,
                "inclusion": record.inclusion,
                "split": record.split,
                "reason": record.reason,
            }
            for _key, record in sorted(store.load_sources().items())
        ],
    }


@router.post("/{name}/rebuild")
async def rebuild_voice(name: str, request: VoiceRebuildRequest) -> dict:
    """Rebuild a voice from its stored roots, on the existing job runner."""
    store, profile = _load(name)
    roots = store.load_roots()
    if not roots:
        raise HTTPException(
            status_code=400,
            detail=(
                f"voice '{store.name}' has no stored source roots. Rebuild it from the "
                f"command line: howlwriter voice rebuild {store.name} --source <path>"
            ),
        )

    manager = get_job_manager()
    job = manager.create_job(job_type="voice_rebuild", stages=list(STAGES))

    def _task(active: Job) -> None:
        outcome = build_voice(
            store.name,
            list(roots),
            deterministic_only=request.deterministic,
            reuse_cache=request.reuse_cache,
            profile_type=profile.profile_type,
            run_id=active.run_id,
            stage_callback=lambda stage_id, status, data: active.update_stage(
                stage_id, status, data
            ),
        )
        active.complete(VoiceBuildResultDto(
            name=store.name,
            directory=str(outcome.directory),
            detail=_detail(store.name, outcome.profile),
            warnings=list(outcome.warnings),
        ))

    manager.start_in_background(job, _task)
    return job.to_dto().model_dump()
