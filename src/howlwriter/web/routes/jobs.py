"""Job status and Server-Sent Events (SSE) streaming endpoint."""

from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from howlwriter.web.jobs import get_job_manager
from howlwriter.web.models import JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job_status(job_id: str) -> JobResponse:
    job = get_job_manager().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job.to_dto()


@router.get("/{job_id}/events")
async def get_job_events(job_id: str, request: Request):
    job = get_job_manager().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    queue: asyncio.Queue = asyncio.Queue()
    job.add_listener(queue)

    async def _event_generator():
        try:
            # Yield initial snapshot event
            initial_dto = job.to_dto()
            yield f"event: snapshot\ndata: {initial_dto.model_dump_json()}\n\n"

            if job.status in ("COMPLETED", "FAILED"):
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {event.get('event', 'message')}\ndata: {json.dumps(event)}\n\n"
                    if event.get("event") in ("completed", "failed"):
                        break
                except asyncio.TimeoutError:
                    # Send keep-alive comment
                    yield ": ping\n\n"
        finally:
            job.remove_listener(queue)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
