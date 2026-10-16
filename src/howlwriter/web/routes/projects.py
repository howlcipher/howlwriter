"""Source Intelligence endpoints: projects, evidence, requirements, drafting, browser.

Boundaries:

* Opening a project is the one place a folder path is accepted, and only an
  existing directory that is not a filesystem root, the home directory
  itself, or anything under ~/.howlwriter. Opening a folder authorizes that
  folder only. Requests are JSON, so a cross-origin page cannot post one
  without a CORS preflight the app refuses.
* Source text appears only in evidence excerpts (bounded) and search hits.
* Browser sessions run on their own thread, in a dedicated profile, under
  the policy given at start; state-changing actions are queued and need an
  explicit approve call.
* Drafting with a model goes through the same remote-inference gate as the CLI.
"""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from howlwriter.projects import service
from howlwriter.projects.workspace import ProjectWorkspace
from howlwriter.web.jobs import Job, get_job_manager
from howlwriter.web.models import ProjectJobResultDto

router = APIRouter(prefix="/api/projects", tags=["projects"])

_BROWSERS: dict[str, object] = {}
_BROWSER_LOCK = threading.Lock()


class OpenRequest(BaseModel):
    folder: str = Field(..., max_length=4096)
    name: Optional[str] = Field(default=None, max_length=120)


class ScanRequest(BaseModel):
    force: bool = False
    transcribe: bool = True
    frames: bool = True
    ocr: bool = True


class CategoryRequest(BaseModel):
    category: str


class RequirementRequest(BaseModel):
    text: str = Field(..., max_length=2000)
    kind: Optional[str] = None


class StatusRequest(BaseModel):
    status: str
    note: str = Field(default="", max_length=500)


class BriefRequest(BaseModel):
    sections: Optional[list[str]] = None
    topic: str = Field(default="", max_length=500)


class DraftRequest(BriefRequest):
    mode: str = "academic"
    voice: Optional[str] = None
    identity: Optional[str] = None
    auto_voice: bool = False
    allow_generic: bool = False
    allow_remote: bool = False
    instructions: str = Field(default="", max_length=4000)


class ValidateRequest(BaseModel):
    text: str = Field(..., max_length=600_000)


class BrowserStartRequest(BaseModel):
    mode: str = "research"
    allowed_origins: list[str] = Field(default_factory=list)
    interactive_origins: list[str] = Field(default_factory=list)
    headless: bool = False


class NavigateRequest(BaseModel):
    url: str = Field(..., max_length=2000)


class ScreenshotRequest(BaseModel):
    label: str = Field(default="page", max_length=60)


class ActionRequest(BaseModel):
    kind: str
    selector: str = Field(..., max_length=500)
    value: Optional[str] = Field(default=None, max_length=2000)


def _bad(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def _ws(project_id: str) -> ProjectWorkspace:
    try:
        return service.resolve(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _check_folder(folder: str) -> Path:
    path = Path(folder).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"{folder} is not a directory")
    resolved = path.resolve()
    home = Path.home().resolve()
    if resolved == Path(resolved.anchor) or resolved == home or len(resolved.parts) <= 2:
        raise HTTPException(
            status_code=400, detail="choose a specific project folder, not a filesystem or home root"
        )
    private = home / ".howlwriter"
    if resolved == private or private in resolved.parents:
        raise HTTPException(status_code=400, detail="HowlWriter's private data cannot be opened as a project")
    return resolved


def _job(kind: str, project_id: str, work) -> dict:
    manager = get_job_manager()
    job = manager.create_job(job_type=f"project_{kind}", stages=[(kind, kind.title())])

    def _task(active: Job) -> None:
        active.update_stage(kind, "RUNNING", {})
        payload = work()
        active.update_stage(kind, "DONE", {})
        active.complete(ProjectJobResultDto(kind=kind, project_id=project_id, payload=payload))

    manager.start_in_background(job, _task)
    return job.to_dto().model_dump()


# --- projects -----------------------------------------------------------------


@router.get("")
async def list_projects() -> list[dict]:
    return [service.summary(ProjectWorkspace(pid)) for pid in ProjectWorkspace.list_projects()]


@router.post("")
async def open_project(request: OpenRequest) -> dict:
    folder = _check_folder(request.folder)
    try:
        workspace = ProjectWorkspace.create(folder, name=request.name)
    except ValueError as error:
        raise _bad(error) from error
    return service.summary(workspace)


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict:
    return service.summary(_ws(project_id))


@router.post("/{project_id}/scan")
async def post_scan(project_id: str, request: ScanRequest) -> dict:
    workspace = _ws(project_id)

    def work() -> dict:
        from howlwriter.projects.resources import ResourcePolicy
        from howlwriter.projects.scan import Extractors, scan_project

        class _Off:
            available = False
            name = "disabled"

        extractors = Extractors(
            policy=ResourcePolicy.from_dict(workspace.load_meta().get("resources")),
            media_frames=request.frames,
            ocr=None if request.ocr else _Off(),
            transcriber=None if request.transcribe else _Off(),
        )
        try:
            return scan_project(workspace, extractors=extractors, force=request.force).to_dict()
        finally:
            extractors.close()

    return _job("scan", workspace.project_id, work)


@router.get("/{project_id}/sources")
async def get_sources(project_id: str, category: Optional[str] = None) -> list[dict]:
    rows = [
        s.to_dict()
        for s in _ws(project_id).load_sources().values()
        if s.present and (not category or s.category == category)
    ]
    return sorted(rows, key=lambda r: r["path"])


@router.post("/{project_id}/sources/{source_id}/category")
async def post_category(project_id: str, source_id: str, request: CategoryRequest) -> dict:
    from howlwriter.projects.scan import set_category

    try:
        return set_category(_ws(project_id), source_id, request.category).to_dict()
    except ValueError as error:
        raise _bad(error) from error


@router.get("/{project_id}/evidence")
async def get_evidence(
    project_id: str,
    source: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
) -> list[dict]:
    items = [
        e
        for e in _ws(project_id).load_evidence().values()
        if (not source or source in (e.source_id, e.source_path)) and (not kind or e.kind == kind)
    ]
    items.sort(key=lambda e: (e.source_path, str(e.locator)))
    out = []
    for item in items[:limit]:
        data = item.to_dict()
        data["observation"] = {
            k: v for k, v in data["observation"].items() if k not in ("text", "lines", "segments")
        }
        out.append(data)
    return out


@router.get("/{project_id}/search")
async def get_search(
    project_id: str,
    q: str = Query(..., max_length=500),
    purpose: str = "facts",
    limit: int = Query(default=8, le=50),
) -> list[dict]:
    from howlwriter.projects.retrieval import EvidenceIndex

    hits = EvidenceIndex(_ws(project_id).load_evidence()).search(q, purpose=purpose, limit=limit)
    return [h.to_dict() for h in hits]


@router.get("/{project_id}/requirements")
async def get_requirements(project_id: str) -> dict:
    from howlwriter.projects.validate import coverage_check

    return coverage_check(_ws(project_id))


@router.post("/{project_id}/requirements")
async def post_requirement(project_id: str, request: RequirementRequest) -> dict:
    from howlwriter.projects.requirements import add_requirement

    return add_requirement(_ws(project_id), request.text, request.kind).to_dict()


@router.post("/{project_id}/requirements/{requirement_id}/status")
async def post_requirement_status(project_id: str, requirement_id: str, request: StatusRequest) -> dict:
    from howlwriter.projects.requirements import set_status

    try:
        status = "" if request.status == "clear" else request.status
        return set_status(_ws(project_id), requirement_id, status, request.note).to_dict()
    except ValueError as error:
        raise _bad(error) from error


@router.post("/{project_id}/brief")
async def post_brief(project_id: str, request: BriefRequest) -> dict:
    from howlwriter.projects.writing import build_brief

    return build_brief(_ws(project_id), sections=request.sections, topic=request.topic)


@router.post("/{project_id}/draft/skeleton")
async def post_skeleton(project_id: str, request: BriefRequest) -> dict:
    from howlwriter.projects.workspace import utc_now
    from howlwriter.projects.writing import build_brief, save_draft, skeleton

    workspace = _ws(project_id)
    brief = build_brief(workspace, sections=request.sections, topic=request.topic)
    text = skeleton(brief, title=workspace.load_meta().get("name", ""))
    path = save_draft(workspace, text, {"created_at": utc_now(), "kind": "skeleton", "model": None})
    return {"text": text, "path": path.name, "summary": brief["summary"]}


@router.post("/{project_id}/draft")
async def post_draft(project_id: str, request: DraftRequest) -> dict:
    workspace = _ws(project_id)

    def work() -> dict:
        from howlwriter.config.loader import ConfigLoader
        from howlwriter.domain.modes import parse_mode
        from howlwriter.projects.writing import build_brief, draft
        from howlwriter.voice.selection import apply_selection

        mode = parse_mode(request.mode)
        config = ConfigLoader().load(mode=mode)
        apply_selection(
            config,
            voice=request.voice,
            spec_value=config.voice_profile,
            spec_source="config",
            identity=request.identity,
            auto_voice=request.auto_voice,
            allow_generic=request.allow_generic,
            mode=mode.value,
        )
        brief = build_brief(workspace, sections=request.sections, topic=request.topic)
        try:
            result = draft(
                workspace,
                brief,
                config=config,
                mode=request.mode,
                instructions=request.instructions,
                allow_remote=request.allow_remote,
            )
        except PermissionError as error:
            return {"error": str(error), "needs_authorization": True}
        return {"text": result["text"], "path": Path(result["path"]).name, "provenance": result["provenance"]}

    return _job("draft", workspace.project_id, work)


@router.post("/{project_id}/validate")
async def post_validate(project_id: str, request: ValidateRequest) -> dict:
    from howlwriter.projects.validate import check_draft

    return check_draft(_ws(project_id), request.text)


@router.post("/{project_id}/authorize-remote")
async def post_authorize(project_id: str, allow: bool = True) -> dict:
    return service.authorize_remote(_ws(project_id), allow)


# --- browser ------------------------------------------------------------------


def _controller(project_id: str):
    with _BROWSER_LOCK:
        controller = _BROWSERS.get(project_id)
    if controller is None:
        raise HTTPException(status_code=409, detail="no browser session; start one first")
    return controller


def _browser_call(project_id: str, name: str, *args, **kwargs):
    from howlwriter.projects.browser import BrowserPolicyError

    controller = _controller(project_id)
    try:
        return controller.call(name, *args, **kwargs)
    except BrowserPolicyError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except TimeoutError as error:
        raise HTTPException(status_code=504, detail=str(error)) from error


@router.get("/{project_id}/browser")
async def get_browser(project_id: str) -> dict:
    workspace = _ws(project_id)
    with _BROWSER_LOCK:
        controller = _BROWSERS.get(workspace.project_id)
    status = controller.call("status") if controller is not None else {"state": "stopped"}
    status["recent_actions"] = [a.to_dict() for a in workspace.load_actions()[-25:]]
    return status


@router.post("/{project_id}/browser/start")
async def post_browser_start(project_id: str, request: BrowserStartRequest) -> dict:
    from howlwriter.projects.browser import (
        BrowserController,
        BrowserPolicy,
        BrowserPolicyError,
        BrowserSession,
    )

    workspace = _ws(project_id)
    try:
        policy = BrowserPolicy(
            mode=request.mode,
            allowed_origins=request.allowed_origins,
            interactive_origins=request.interactive_origins,
        )
    except BrowserPolicyError as error:
        raise _bad(error) from error
    with _BROWSER_LOCK:
        if workspace.project_id in _BROWSERS:
            raise HTTPException(
                status_code=409, detail="a browser session is already running for this project"
            )
        controller = BrowserController(BrowserSession(workspace, policy, headless=request.headless))
        _BROWSERS[workspace.project_id] = controller
    try:
        controller.call("start", timeout=60)
    except Exception as error:
        with _BROWSER_LOCK:
            _BROWSERS.pop(workspace.project_id, None)
        controller.close()
        raise HTTPException(status_code=500, detail=f"browser did not start: {error}") from error
    return controller.call("status")


@router.post("/{project_id}/browser/stop")
async def post_browser_stop(project_id: str) -> dict:
    workspace = _ws(project_id)
    with _BROWSER_LOCK:
        controller = _BROWSERS.pop(workspace.project_id, None)
    if controller is not None:
        controller.close()
    return {"state": "stopped"}


@router.post("/{project_id}/browser/navigate")
async def post_browser_navigate(project_id: str, request: NavigateRequest) -> dict:
    return _browser_call(_ws(project_id).project_id, "navigate", request.url).to_dict()


@router.post("/{project_id}/browser/screenshot")
async def post_browser_screenshot(project_id: str, request: ScreenshotRequest) -> dict:
    return _browser_call(_ws(project_id).project_id, "screenshot", request.label).to_dict()


@router.post("/{project_id}/browser/request")
async def post_browser_request(project_id: str, request: ActionRequest) -> dict:
    workspace = _ws(project_id)
    action_id = _browser_call(workspace.project_id, "request", request.kind, request.selector, request.value)
    return {"action_id": action_id, "status": _browser_call(workspace.project_id, "status")}


@router.post("/{project_id}/browser/actions/{action_id}/{decision}")
async def post_browser_decision(project_id: str, action_id: str, decision: str) -> dict:
    if decision not in ("approve", "deny"):
        raise HTTPException(status_code=404, detail="decision must be approve or deny")
    return _browser_call(_ws(project_id).project_id, decision, action_id).to_dict()


@router.post("/{project_id}/browser/{verb}")
async def post_browser_verb(project_id: str, verb: str) -> dict:
    names = {"pause": "pause", "resume": "resume", "read-only": "set_read_only", "read": "read"}
    if verb not in names:
        raise HTTPException(status_code=404, detail=f"unknown browser command {verb}")
    workspace = _ws(project_id)
    result = _browser_call(workspace.project_id, names[verb])
    if verb == "read":
        data = result.to_dict()
        data["observation"] = {k: v for k, v in data["observation"].items() if k != "text"}
        return data
    return _browser_call(workspace.project_id, "status")
