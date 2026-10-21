from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError

from app.api.error_handlers import (
    DATABASE_UNAVAILABLE_ERRORS,
    database_unavailable_handler,
    integrity_error_handler,
    request_validation_handler,
)
from app.api.evidence_routes import router as evidence_router
from app.api.location_routes import router as location_router
from app.api.worker_task_routes import router as worker_router
from app.config import settings
from app.db.database import Database
from app.db.seed import seed_demo_data
from app.services.completion_submission_service import (
    CompletionSubmissionService,
)
from app.services.evidence_service import EvidenceService
from app.services.field_work_service import FieldWorkService
from app.services.location_capture_service import LocationCaptureService
from app.services.task_state_service import TaskStateService
from app.storage.image_storage import ImageStorage


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PostgreSQL is required. Startup fails with a clear message when it
    # is not configured, unreachable or not migrated; there is no fallback.
    database = await Database.connect(settings)

    try:
        if settings.seed_demo_data and settings.app_env != "production":
            async with database.unit_of_work() as uow:
                await seed_demo_data(uow)

        storage = ImageStorage()
        state_service = TaskStateService()
        unit_of_work = database.unit_of_work

        app.state.database = database

        app.state.field_work_service = FieldWorkService(
            unit_of_work,
            state_service,
        )

        app.state.evidence_service = EvidenceService(
            unit_of_work,
            storage,
        )

        app.state.location_service = LocationCaptureService(unit_of_work)

        app.state.completion_service = CompletionSubmissionService(
            unit_of_work,
            state_service,
        )

        yield
    finally:
        await database.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="KAVACH Field Worker Execution Agent API",
    lifespan=lifespan,
)

app.add_exception_handler(RequestValidationError, request_validation_handler)
app.add_exception_handler(IntegrityError, integrity_error_handler)

for error_type in DATABASE_UNAVAILABLE_ERRORS:
    app.add_exception_handler(error_type, database_unavailable_handler)

# Restrict allowed origins before connecting a real frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)

app.include_router(
    worker_router,
    prefix=settings.api_prefix,
)
app.include_router(
    evidence_router,
    prefix=settings.api_prefix,
)
app.include_router(
    location_router,
    prefix=settings.api_prefix,
)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": settings.app_name}
