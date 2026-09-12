"""Thread-safe background job manager and SSE event distributor for HowlWriter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Optional
import uuid

from howlwriter.diagnostic.run_record import classify_failure, generate_run_id
from howlwriter.web.models import AcademicResultDto, JobResponse, StageDto


STANDARD_ACADEMIC_STAGES = [
    ("validate", "Assignment Validated"),
    ("research", "Research & Source Discovery"),
    ("drafting", "Drafting Paper"),
    ("constraints", "Constraint-Aware Editing"),
    ("length_check", "Word Count & Length Check"),
    ("outline_check", "Outline Conformance"),
    ("claim_verification", "Claim & Provenance Verification"),
    ("humanizing", "Safe Prose Humanizing"),
    ("lint_redpen", "Deterministic Lint & Red Pen"),
    ("meaning_review", "Meaning Preservation Review"),
    ("citations_references", "APA 7 Citations & References"),
    ("final_report", "Final Report & Dogfood Record"),
]


@dataclass
class StageState:
    id: str
    label: str
    status: str = "PENDING"  # PENDING, RUNNING, DONE, FAILED
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dto(self) -> StageDto:
        return StageDto(
            id=self.id,
            label=self.label,
            status=self.status,
            started_at=self.started_at,
            completed_at=self.completed_at,
            data=self.data,
        )


class Job:
    def __init__(self, job_type: str, run_id: Optional[str] = None):
        self.job_id = f"job-{uuid.uuid4().hex[:8]}"
        self.run_id = run_id or generate_run_id()
        self.job_type = job_type
        self.status = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED
        self.created_at = time.time()
        self.updated_at = time.time()
        self.current_stage_id: Optional[str] = None
        self.stages: list[StageState] = [
            StageState(id=sid, label=slabel)
            for sid, slabel in STANDARD_ACADEMIC_STAGES
        ]
        self.error_message: Optional[str] = None
        self.failure_category: Optional[str] = None
        self.result: Optional[AcademicResultDto] = None
        self._listeners: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def update_stage(self, stage_id: str, status: str, data: Optional[dict[str, Any]] = None) -> None:
        with self._lock:
            self.updated_at = time.time()
            if self.status == "QUEUED":
                self.status = "RUNNING"
            self.current_stage_id = stage_id

            found = False
            for s in self.stages:
                if s.id == stage_id:
                    s.status = status
                    if status == "RUNNING" and s.started_at is None:
                        s.started_at = time.time()
                    elif status in ("DONE", "FAILED"):
                        s.completed_at = time.time()
                    if data:
                        s.data.update(data)
                    found = True
                    break

            if not found and stage_id:
                new_s = StageState(
                    id=stage_id,
                    label=data.get("label", stage_id) if data else stage_id,
                    status=status,
                    started_at=time.time(),
                    completed_at=time.time() if status in ("DONE", "FAILED") else None,
                    data=data or {},
                )
                self.stages.append(new_s)

            event = {
                "event": "stage_update",
                "job_id": self.job_id,
                "run_id": self.run_id,
                "stage_id": stage_id,
                "status": status,
                "data": data or {},
                "timestamp": self.updated_at,
            }
            self._broadcast_event(event)

    def complete(self, result: AcademicResultDto) -> None:
        with self._lock:
            self.status = "COMPLETED"
            self.updated_at = time.time()
            self.result = result
            # Mark all pending/running stages as DONE
            for s in self.stages:
                if s.status in ("PENDING", "RUNNING"):
                    s.status = "DONE"
                    s.completed_at = time.time()

            event = {
                "event": "completed",
                "job_id": self.job_id,
                "run_id": self.run_id,
                "status": "COMPLETED",
                "timestamp": self.updated_at,
            }
            self._broadcast_event(event)

    def fail(self, error: Exception | str) -> None:
        with self._lock:
            self.status = "FAILED"
            self.updated_at = time.time()
            self.error_message = str(error)
            self.failure_category = classify_failure(error)
            if self.current_stage_id:
                for s in self.stages:
                    if s.id == self.current_stage_id:
                        s.status = "FAILED"
                        s.completed_at = time.time()
                        break

            event = {
                "event": "failed",
                "job_id": self.job_id,
                "run_id": self.run_id,
                "status": "FAILED",
                "error": str(error),
                "failure_category": self.failure_category,
                "timestamp": self.updated_at,
            }
            self._broadcast_event(event)

    def _broadcast_event(self, event: dict[str, Any]) -> None:
        for q in self._listeners[:]:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def add_listener(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._listeners.append(queue)

    def remove_listener(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._listeners:
                self._listeners.remove(queue)

    def to_dto(self) -> JobResponse:
        with self._lock:
            if self.status in ("QUEUED", "RUNNING"):
                elapsed = time.time() - self.created_at
            else:
                elapsed = self.updated_at - self.created_at
            return JobResponse(
                job_id=self.job_id,
                run_id=self.run_id,
                job_type=self.job_type,
                status=self.status,
                created_at=self.created_at,
                updated_at=self.updated_at,
                elapsed_seconds=round(elapsed, 2),
                current_stage_id=self.current_stage_id,
                stages=[s.to_dto() for s in self.stages],
                error_message=self.error_message,
                failure_category=self.failure_category,
                result=self.result,
            )


class JobManager:
    """Manages active and historical local jobs."""

    def __init__(self, max_retained_jobs: int = 50):
        self._jobs: dict[str, Job] = {}
        self._max_retained = max_retained_jobs
        self._lock = threading.Lock()

    def create_job(self, job_type: str, run_id: Optional[str] = None) -> Job:
        with self._lock:
            job = Job(job_type=job_type, run_id=run_id)
            self._jobs[job.job_id] = job
            # Trim old jobs
            if len(self._jobs) > self._max_retained:
                oldest_key = min(self._jobs.keys(), key=lambda k: self._jobs[k].created_at)
                del self._jobs[oldest_key]
            return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def start_in_background(
        self,
        job: Job,
        task_fn: Callable[[Job], None],
    ) -> None:
        def _target() -> None:
            try:
                task_fn(job)
            except Exception as exc:
                job.fail(exc)

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()


_GLOBAL_JOB_MANAGER: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _GLOBAL_JOB_MANAGER
    if _GLOBAL_JOB_MANAGER is None:
        _GLOBAL_JOB_MANAGER = JobManager()
    return _GLOBAL_JOB_MANAGER
