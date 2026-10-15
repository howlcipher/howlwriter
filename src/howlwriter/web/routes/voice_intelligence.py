"""Voice Intelligence endpoints: corpus status, authorship review, profiles,
and the two calibrated scores.

Boundaries this module keeps, matching the existing voices endpoints:

* Choosing what to read stays at the command line. A scan from the UI rescans
  the sources the identity was configured with; there is no endpoint that
  accepts a new filesystem path.
* Summaries by default. Review items carry a document's file name, because a
  person cannot attest a document they cannot identify, but folder paths are
  only included with `?show_paths=true`, and document text only through the
  per-document preview with `?confirm=true`.
* Nothing here calls a model or sends content anywhere. Evaluation is the
  same deterministic code path as `howlwriter evaluate`.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from howlwriter.evaluation.personal import compare_texts, evaluate_text, load_preferences
from howlwriter.voice.identity import review
from howlwriter.voice.identity.profiles import build_identity
from howlwriter.voice.identity.scanner import MountUnavailableError, scan
from howlwriter.voice.identity.status import identity_status
from howlwriter.voice.identity.store import IdentityStore, source_path_of, validate_identity
from howlwriter.web.jobs import Job, get_job_manager
from howlwriter.web.models import VoiceIntelJobResultDto

router = APIRouter(prefix="/api/voice-intel", tags=["voice-intelligence"])

MAX_EVALUATE_CHARS = 400_000


class AttestRequest(BaseModel):
    authorship: str
    category: str = ""
    context: str = ""
    include_paragraphs: str = ""
    use_proposed_extraction: bool = False
    note: str = Field(default="", max_length=500)


class GroupDecisionRequest(BaseModel):
    authorship: str
    #: Exactly the members the person was shown; a changed group is refused.
    doc_ids: list[str]
    use_proposed_extraction: bool = False


class EvaluateRequest(BaseModel):
    text: str = Field(..., max_length=MAX_EVALUATE_CHARS)
    mode: Optional[str] = None
    voice: Optional[str] = None
    identity: Optional[str] = None
    auto_voice: bool = False


class CompareRequest(BaseModel):
    original: str = Field(..., max_length=MAX_EVALUATE_CHARS)
    revised: str = Field(..., max_length=MAX_EVALUATE_CHARS)
    mode: Optional[str] = None
    voice: Optional[str] = None
    identity: Optional[str] = None
    auto_voice: bool = False
    requirements: Optional[dict[str, Any]] = None


def _store(identity: str) -> IdentityStore:
    try:
        store = IdentityStore(validate_identity(identity))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not store.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"identity '{store.identity}' has not been scanned. Start from the command line: "
                f"howlwriter voice scan --identity {store.identity} --source <path>"
            ),
        )
    return store


@router.get("/identities")
async def list_identities() -> dict:
    return {
        "identities": IdentityStore.list_identities(),
        "preferred_identity": load_preferences().get("preferred_identity"),
    }


@router.get("/{identity}/status")
async def get_status(identity: str) -> dict:
    store = _store(identity)
    return identity_status(store.identity)


@router.get("/{identity}/review")
async def get_review(identity: str, show_paths: bool = Query(False)) -> dict:
    store = _store(identity)
    items = []
    for item in review.queue(store):
        data = item.to_dict()
        relative = data.pop("path")
        data["title"] = PurePosixPath(source_path_of(relative)).name
        if show_paths:
            data["path"] = relative
        items.append(data)
    return {"summary": review.summary(store), "pending": items}


@router.post("/{identity}/review/{doc_id}")
async def post_attestation(identity: str, doc_id: str, request: AttestRequest) -> dict:
    store = _store(identity)
    try:
        decision = review.attest(
            store,
            doc_id,
            request.authorship,
            category=request.category,
            context=request.context,
            include_paragraphs=request.include_paragraphs,
            note=request.note,
            use_proposed_extraction=request.use_proposed_extraction,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    review.refresh_queue(store)
    return {
        "doc_id": decision.doc_id,
        "authorship": decision.authorship,
        "decided_at": decision.decided_at,
    }


@router.get("/{identity}/review-groups")
async def get_review_groups(identity: str) -> dict:
    store = _store(identity)
    return {
        "groups": [g.to_dict() for g in review.groups(store)],
        "descriptions": review.AUTHORSHIP_DESCRIPTIONS,
    }


@router.post("/{identity}/review-groups/{group_id}")
async def post_group_decision(identity: str, group_id: str, request: GroupDecisionRequest) -> dict:
    store = _store(identity)
    try:
        decisions = review.attest_group(
            store,
            group_id,
            request.authorship,
            confirmed_doc_ids=request.doc_ids,
            use_proposed_extraction=request.use_proposed_extraction,
            note=f"bulk decision for group {group_id} (web)",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "recorded": len(decisions),
        "authorship": decisions[0].authorship if decisions else None,
    }


@router.get("/{identity}/review/{doc_id}/preview")
async def get_preview(identity: str, doc_id: str, confirm: bool = Query(False)) -> dict:
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="A preview shows document text. Request it with ?confirm=true.",
        )
    store = _store(identity)
    try:
        return {
            "doc_id": doc_id,
            "paragraphs": review.preview(store, doc_id, max_paragraphs=30, max_chars=320),
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _start(kind: str, identity: str, work) -> dict:
    manager = get_job_manager()
    job = manager.create_job(
        job_type=f"voice_intel_{kind}", stages=[(kind, kind.replace("_", " ").title())]
    )

    def _task(active: Job) -> None:
        active.update_stage(kind, "RUNNING", {})
        payload = work()
        active.update_stage(kind, "DONE", {})
        active.complete(VoiceIntelJobResultDto(kind=kind, identity=identity, payload=payload))

    manager.start_in_background(job, _task)
    return job.to_dto().model_dump()


@router.post("/{identity}/scan")
async def post_scan(identity: str) -> dict:
    """Rescan the identity's configured sources. No new paths are accepted."""
    store = _store(identity)

    def work() -> dict:
        try:
            return {"report": scan(store.identity).report}
        except MountUnavailableError as error:
            return {"error": str(error), "mount_unavailable": True}

    return _start("scan", store.identity, work)


@router.post("/{identity}/build")
async def post_build(identity: str) -> dict:
    """Rebuild the identity's profiles, deterministic only."""
    store = _store(identity)
    return _start(
        "build",
        store.identity,
        lambda: {"profiles": [r.to_dict() for r in build_identity(store.identity)]},
    )


@router.post("/evaluate")
async def post_evaluate(request: EvaluateRequest) -> dict:
    try:
        return evaluate_text(
            request.text,
            mode=request.mode,
            voice=request.voice,
            identity=request.identity,
            auto_voice=request.auto_voice,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/compare")
async def post_compare(request: CompareRequest) -> dict:
    try:
        return compare_texts(
            request.original,
            request.revised,
            requirements=request.requirements,
            mode=request.mode,
            voice=request.voice,
            identity=request.identity,
            auto_voice=request.auto_voice,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


# --- Voice Workshop ---------------------------------------------------------


class WorkshopPromptRequest(BaseModel):
    context: Optional[str] = None
    subject: Optional[str] = Field(default=None, max_length=120)
    kind: Optional[str] = None
    follow_up_of: Optional[str] = None


class WorkshopAnswerRequest(BaseModel):
    prompt_id: str
    subject: str = Field(default="", max_length=120)
    text: str = Field(..., max_length=20_000)
    self_written: bool = False
    approve: bool = False


class WorkshopReclassifyRequest(BaseModel):
    context: str


class WorkshopRevisionRequest(BaseModel):
    text: str = Field(..., max_length=20_000)


def _workshop(identity: str):
    from howlwriter.voice.identity.workshop import Workshop

    try:
        return Workshop(validate_identity(identity))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _sample_view(sample, counting: set[str], *, with_text: bool) -> dict:
    data = sample.to_dict()
    data["counts"] = sample.sample_id in counting
    if not with_text:
        data.pop("text")
        data.pop("preferred_revision")
    return data


@router.get("/{identity}/workshop")
async def get_workshop(identity: str, show_text: bool = Query(False)) -> dict:
    """Coverage and samples. Answer text only with ?show_text=true."""
    from howlwriter.voice.identity.workshop import counting_ids

    workshop = _workshop(identity)
    samples = workshop.samples()
    counting = counting_ids(samples.values())
    return {
        "coverage": workshop.coverage(),
        "samples": [
            _sample_view(s, counting, with_text=show_text)
            for s in sorted(samples.values(), key=lambda x: x.created_at)
        ],
        "local_only": True,
    }


@router.post("/{identity}/workshop/prompt")
async def post_workshop_prompt(identity: str, request: WorkshopPromptRequest) -> dict:
    try:
        return (
            _workshop(identity)
            .next_prompt(
                context=request.context,
                subject=request.subject,
                kind=request.kind,
                follow_up_of=request.follow_up_of,
            )
            .to_dict()
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/{identity}/workshop/samples")
async def post_workshop_sample(identity: str, request: WorkshopAnswerRequest) -> dict:
    from howlwriter.voice.identity.workshop import counting_ids

    workshop = _workshop(identity)
    try:
        sample = workshop.add(
            prompt_id=request.prompt_id,
            subject=request.subject,
            text=request.text,
            self_written=request.self_written,
            approve=request.approve,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _sample_view(sample, counting_ids(workshop.samples().values()), with_text=False)


@router.post("/{identity}/workshop/samples/{sample_id}/actions/{action}")
async def post_workshop_action(identity: str, sample_id: str, action: str) -> dict:
    if action not in ("approve", "exclude", "remove"):
        raise HTTPException(status_code=404, detail=f"unknown action {action!r}")
    workshop = _workshop(identity)
    try:
        sample = getattr(workshop, action)(sample_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"sample_id": sample.sample_id, "status": sample.status, "side": sample.side}


@router.post("/{identity}/workshop/samples/{sample_id}/context")
async def post_workshop_reclassify(
    identity: str, sample_id: str, request: WorkshopReclassifyRequest
) -> dict:
    try:
        sample = _workshop(identity).reclassify(sample_id, request.context)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"sample_id": sample.sample_id, "context": sample.context}


@router.post("/{identity}/workshop/samples/{sample_id}/revision")
async def post_workshop_revision(
    identity: str, sample_id: str, request: WorkshopRevisionRequest
) -> dict:
    try:
        sample = _workshop(identity).set_preferred_revision(sample_id, request.text)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "sample_id": sample.sample_id,
        "has_preferred_revision": bool(sample.preferred_revision),
    }
