"""FastAPI application factory for HowlWriter local web application."""

from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from howlwriter.web.routes.academic import router as academic_router
from howlwriter.web.routes.documents import router as documents_router
from howlwriter.web.routes.howl import router as howl_router
from howlwriter.web.routes.humanize import router as humanize_router
from howlwriter.web.routes.jobs import router as jobs_router
from howlwriter.web.routes.lint import router as lint_router
from howlwriter.web.routes.providers import router as providers_router
from howlwriter.web.routes.redpen import router as redpen_router
from howlwriter.web.routes.runs import router as runs_router


def create_app(static_dir: Path | str | None = None) -> FastAPI:
    app = FastAPI(
        title="HowlWriter Local Web Application",
        description="Local writing control system, voice preservation & review interface.",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # Local CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers
    app.include_router(documents_router)
    app.include_router(lint_router)
    app.include_router(redpen_router)
    app.include_router(humanize_router)
    app.include_router(howl_router)
    app.include_router(academic_router)
    app.include_router(jobs_router)
    app.include_router(runs_router)
    app.include_router(providers_router)

    # Static assets directory
    resolved_static_dir = (
        Path(static_dir)
        if static_dir
        else Path(__file__).parent / "static"
    )

    if resolved_static_dir.exists() and (resolved_static_dir / "index.html").exists():
        # Mount assets directory if it exists
        assets_dir = resolved_static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API endpoint not found")
            file_path = resolved_static_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(resolved_static_dir / "index.html")
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
            content={"error": exc.detail},
        )

    return app


app = create_app()
