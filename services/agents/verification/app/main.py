from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from .api.verification_routes import router as verification_router
from .config import Settings
from .repositories.evidence_repository import EvidenceRepository
from .repositories.sqlite_repositories import SQLiteEvidenceRepository, SQLiteTaskRepository
from .repositories.task_repository import TaskRepository
from .repositories.verification_repository import SQLiteVerificationRepository
from .services.verification_service import VerificationService
from .services.vision_model_service import build_vision_adapter

settings = Settings()
audit_repository = SQLiteVerificationRepository(settings.db_path)
if settings.repository_provider == "memory":
    task_repository = TaskRepository()
    evidence_repository = EvidenceRepository(storage_root=settings.evidence_root)
elif settings.repository_provider == "sqlite":
    task_repository = SQLiteTaskRepository(settings.db_path)
    evidence_repository = SQLiteEvidenceRepository(settings.db_path, storage_root=settings.evidence_root)
else:
    raise ValueError("Unknown KAVACH_REPOSITORY_PROVIDER; use 'memory' or 'sqlite'.")
vision_adapter = build_vision_adapter(settings, image_loader=evidence_repository.load_image)
verification_service = VerificationService(
    tasks=task_repository, submissions=evidence_repository,
    vision=vision_adapter, audit=audit_repository, settings=settings,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    audit_repository.initialize()
    for repository in (task_repository, evidence_repository):
        initialize = getattr(repository, "initialize", None)
        if initialize is not None:
            initialize()
    yield


app = FastAPI(
    title="KAVACH Verification Agent (Prototype)",
    description="Local educational prototype using synthetic fixtures and mock image findings.",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.verification_service = verification_service
app.include_router(verification_router)


@app.middleware("http")
async def contract_version_header(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-KAVACH-Contract-Version"] = "1.1"
    return response


@app.get("/")
def home() -> dict:
    return {
        "contract_version": "1.1",
        "message": "KAVACH Verification Agent prototype is running.",
        "api_docs": "/docs",
        "health_check": "/health",
    }


@app.get("/health")
def health() -> dict:
    return {"contract_version": "1.1", "status": "ok", "mode": "prototype", "vision": "mock"}

