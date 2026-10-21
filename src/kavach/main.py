"""App factory. Run: uvicorn kavach.main:app --reload  (from ./src)"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from kavach.agents.incident_intelligence import IncidentIntelligenceAgent, create_llm
from kavach.api.routes.incidents import RateLimiter, router as incidents_router
from kavach.config import Settings
from kavach.repositories.incident_repository import (
    InMemoryIncidentRepository,
    IncidentRepository,
    PostgresIncidentRepository,
)
from kavach.services.incident_intelligence.handoff import DuplicateDetectionClient
from kavach.services.incident_intelligence.orchestrator import IncidentIntelligenceOrchestrator
from kavach.services.media.storage import InMemoryMediaStore, LocalDirectoryMediaStore, MediaStore


def build_repository(settings: Settings) -> IncidentRepository:
    if settings.repository == "postgres":
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required for KAVACH_REPOSITORY=postgres")
        return PostgresIncidentRepository(settings.database_url)
    return InMemoryIncidentRepository()


def build_media_store(settings: Settings) -> MediaStore:
    return LocalDirectoryMediaStore(settings.media_dir) if settings.media_dir else InMemoryMediaStore()


def build_orchestrator(settings: Settings) -> IncidentIntelligenceOrchestrator:
    return IncidentIntelligenceOrchestrator(
        agent=IncidentIntelligenceAgent(create_llm(settings)),
        repository=build_repository(settings),
        max_image_bytes=settings.max_image_bytes,
        max_images=settings.max_images,
        media_store=build_media_store(settings),
        handoff_client=(DuplicateDetectionClient(settings.duplicate_detection_url, settings.handoff_timeout_seconds)
                        if settings.duplicate_detection_url else None),
    )


def create_app(orchestrator: IncidentIntelligenceOrchestrator | None = None,
               settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings = settings or Settings.from_env()
    app = FastAPI(title="KAVACH - Incident Intelligence Agent", version="1.1.0")
    app.state.orchestrator = orchestrator or build_orchestrator(settings)
    app.state.read_api_key = settings.read_api_key
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    max_body = (app.state.orchestrator.max_images * app.state.orchestrator.max_image_bytes) + 1024 * 1024

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        # Rejects oversized bodies before multipart parsing. Chunked uploads without Content-Length
        # must be capped by the reverse proxy (e.g. nginx client_max_body_size).
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body:
            return JSONResponse(status_code=413, content={"detail": {"code": "REQUEST_TOO_LARGE",
                                                                     "message": "Upload too large."}})
        return await call_next(request)

    app.include_router(incidents_router)

    # Local testing UI (interactive map + complaint/image/GPS submission).
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.is_dir():
        app.mount("/tester", StaticFiles(directory=str(frontend_dir), html=True), name="tester")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def __getattr__(name: str):  # lazy module-level `app` so importing create_app never needs env/secrets
    if name == "app":
        return create_app()
    raise AttributeError(name)
