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
from howlwriter.voice.identity.store import IdentityStore, validate_identity
from howlwriter.web.jobs import Job, get_job_manager
from howlwriter.web.models import VoiceIntelJobResultDto

router = APIRouter(prefix="/api/voice-intel", tags=["voice-intelligence"])

MAX_EVALUATE_CHARS = 400_000


class AttestRequest(BaseModel):
    authorship: str
    category: str = ""
    context: str = ""
    include_paragraphs: str = ""
    note: str = Field(default="", max_length=500)


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
        data["title"] = PurePosixPath(relative.split(":", 1)[-1]).name
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
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    review.refresh_queue(store)
    return {
        "doc_id": decision.doc_id,
        "authorship": decision.authorship,
        "decided_at": decision.decided_at,
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
