"""FastAPI application factory for HowlWriter local web application."""

from __future__ import annotations

from collections.abc import Sequence
from http import HTTPStatus
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from howlwriter import __version__
from howlwriter.integration import provider_choice
from howlwriter.integration.model_role import HowlPlaneUnavailableError, ModelRoleNotConfiguredError
from howlwriter.web.owner import OwnerConfirmationRequired
from howlwriter.web.paths import PathNotAllowed
from howlwriter.web.routes.academic import router as academic_router
from howlwriter.web.routes.documents import router as documents_router
from howlwriter.web.routes.evaluation import router as evaluation_router
from howlwriter.web.routes.howl import router as howl_router
from howlwriter.web.routes.humanize import router as humanize_router
from howlwriter.web.routes.jobs import router as jobs_router
from howlwriter.web.routes.lint import router as lint_router
from howlwriter.web.routes.providers import router as providers_router
from howlwriter.web.routes.redpen import router as redpen_router
from howlwriter.web.routes.runs import router as runs_router
from howlwriter.web.routes.provenance import router as provenance_router
from howlwriter.web.routes.projects import router as projects_router
from howlwriter.web.routes.publishing import router as publishing_router
from howlwriter.web.routes.voices import router as voices_router
from howlwriter.web.routes.voice_intelligence import router as voice_intel_router


async def _model_choice(request: Request) -> None:
    # Async, so the context it sets reaches sync endpoints and the jobs they start.
    provider_choice.apply_request_headers(request.headers)


DEFAULT_PORT = 8765
_VITE_PORT = 5173
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_LOOPBACK_V6 = ("::1", "[::1]")


def _allowed_origins(port: int, host: str) -> set[str]:
    names = ["127.0.0.1", "localhost"]
    if host in _LOOPBACK_V6:
        names.append("[::1]")
    return {f"http://{name}:{p}" for name in names for p in (port, _VITE_PORT)}


def _slug(exc: HTTPException) -> str:
    try:
        return HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_").replace("'", "")
    except ValueError:
        return "http_error"


def create_app(
    static_dir: Path | str | None = None,
    *,
    port: int | None = None,
    host: str = "127.0.0.1",
    allowed_hosts: Sequence[str] = ("127.0.0.1", "localhost"),
) -> FastAPI:
    """Build the app. Only requests addressed to ``allowed_hosts`` are answered, and cross-origin
    writes are refused, so a web page cannot reach the API through DNS rebinding or a forged form."""
    hosts = list(allowed_hosts)
    if host in _LOOPBACK_V6:
        hosts += [name for name in _LOOPBACK_V6 if name not in hosts]
    origins = _allowed_origins(port or DEFAULT_PORT, host)
    any_host = "*" in hosts

    app = FastAPI(
        title="HowlWriter Local Web Application",
        description="Local writing control system, voice preservation & review interface.",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        dependencies=[Depends(_model_choice)],
    )

    @app.exception_handler(ModelRoleNotConfiguredError)
    async def _model_needed(request: Request, error: ModelRoleNotConfiguredError) -> JSONResponse:
        # The page asks which model to use and retries; nothing was sent.
        return JSONResponse(
            status_code=409,
            content={"code": "model_choice_required", "role": error.role.value, "detail": str(error)},
        )

    @app.exception_handler(HowlPlaneUnavailableError)
    async def _howlplane_missing(request: Request, error: HowlPlaneUnavailableError) -> JSONResponse:
        # A model was chosen but cannot run here; asking again would not help.
        return JSONResponse(
            status_code=503,
            content={"code": "howlplane_unavailable", "role": error.role.value, "detail": str(error)},
        )

    @app.exception_handler(OwnerConfirmationRequired)
    async def _owner_needed(request: Request, error: OwnerConfirmationRequired) -> JSONResponse:
        # Authorship, Workshop, and remote-send decisions are the owner's; nothing was changed.
        return JSONResponse(
            status_code=403, content={"code": "owner_confirmation_required", "detail": str(error)}
        )

    @app.exception_handler(PathNotAllowed)
    async def _path_refused(request: Request, error: PathNotAllowed) -> JSONResponse:
        return JSONResponse(status_code=403, content={"code": "path_not_allowed", "detail": str(error)})

    # No CORS: the page is same-origin (served by `ui`, or proxied by the Vite dev server), so no
    # other origin gets to read responses or send the owner headers from a browser.

    @app.middleware("http")
    async def _refuse_cross_origin_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and request.method in _WRITE_METHODS:
            same_origin = any_host and origin == f"http://{request.headers.get('host', '')}"
            if origin not in origins and not same_origin:
                return JSONResponse(
                    status_code=403,
                    content={
                        "code": "origin_not_allowed",
                        "detail": "Writes are only accepted from HowlWriter's own page.",
                    },
                )
        return await call_next(request)

    # Added last, so it runs first: nothing else sees a request addressed to another host.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)

    # Mount API routers
    app.include_router(documents_router)
    app.include_router(lint_router)
    app.include_router(redpen_router)
    app.include_router(humanize_router)
    app.include_router(howl_router)
    app.include_router(academic_router)
    app.include_router(jobs_router)
    app.include_router(runs_router)
    app.include_router(publishing_router)
    app.include_router(providers_router)
    app.include_router(voices_router)
    app.include_router(voice_intel_router)
    app.include_router(projects_router)
    app.include_router(provenance_router)
    app.include_router(evaluation_router)

    # Static assets directory
    resolved_static_dir = (
        Path(static_dir)
        if static_dir
        else Path(__file__).parent / "static"
    )

    static_root = resolved_static_dir.resolve()

    if resolved_static_dir.exists() and (resolved_static_dir / "index.html").exists():
        # Mount assets directory if it exists
        assets_dir = resolved_static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API endpoint not found")
            candidate = (static_root / full_path).resolve()
            if candidate.is_relative_to(static_root) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_root / "index.html")
    else:
        # Fallback when static assets are not built yet
        @app.get("/")
        async def root():
            return {
                "name": "HowlWriter Local Web API",
                "status": "online",
                "docs": "/api/docs",
                "frontend_status": (
                    "Static frontend not built yet. Run 'npm run build' in frontend/ directory."
                ),
            }

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": _slug(exc), "error": exc.detail, "detail": exc.detail},
        )

    return app


app = create_app()
