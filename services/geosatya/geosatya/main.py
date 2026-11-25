import logging
import mimetypes
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import secrets

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image

from geosatya.accessgate import install as install_access_gate
from geosatya.api.auth_routes import router as auth_router
from geosatya.api.routes import register_error_handlers, router
from geosatya.authz import authorize
from geosatya.categories import load_categories
from geosatya.config import BASE_DIR, Settings, get_settings
from geosatya.db import init_schema, make_engine, make_session_factory
from geosatya.integrations.intelligence import IntelligenceClient
from geosatya.integrations.agents import make_team_agents


def make_verifier(settings, log):
    """The Verification agent in-process, or None (logged) if it can't load."""
    mode = (settings.verification_agent or "off").strip().lower()
    if mode == "off":
        return None
    try:
        from geosatya.integrations.verification import VerificationAgent
        audit_db = Path(settings.database_url.split("///", 1)[-1]).parent / "verification_audit.db"             if settings.database_url.startswith("sqlite") else Path(settings.storage_dir).parent / "verification_audit.db"
        return VerificationAgent(storage_root=Path(settings.storage_dir), audit_db=audit_db, vision_provider=mode)
    except Exception as exc:
        log.warning("Verification agent not available: %s", exc)
        return None
from geosatya.integrations.routing import make_router
from geosatya.kavach.api import router as kavach_router
from geosatya.kavach.citizen_worker import router as citizen_worker_router
from geosatya.kavach.women import router as women_router
from geosatya.kavach.seed import seed_kavach_demo
from geosatya.kavach.service import ensure_plans
from geosatya.ratelimit import SlidingWindowLimiter
from geosatya.media.storage import LocalImageStorage
from geosatya.kavach.audio import router as audio_router
from geosatya.models import Base
from geosatya.seed import ensure_users, seed_demo_data

FRONTEND_DIR = BASE_DIR / "frontend"
log = logging.getLogger("geosatya")
# The worker app's manifest; Windows' MIME table doesn't know this extension.
mimetypes.add_type("application/manifest+json", ".webmanifest")


class FrontendFiles(StaticFiles):
    """Static frontend that browsers revalidate on each load, so an update is
    never mixed with stale cached modules."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response
CATEGORIES_FILE = BASE_DIR / "geosatya" / "data" / "categories.json"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.team_demo and (settings.auth_mode != "demo" or settings.app_env == "production"):
        raise RuntimeError("TEAM_DEMO needs AUTH_MODE=demo and is not allowed when APP_ENV=production.")
    if settings.app_env == "production" and settings.auth_mode == "demo":
        raise RuntimeError("AUTH_MODE=demo is not allowed when APP_ENV=production. "
                           "Use AUTH_MODE=jwt (real sign-in).")
    if settings.auth_mode == "token" and not settings.token_map():
        raise RuntimeError("AUTH_MODE=token needs AUTH_TOKENS.")
    jwt_secret = settings.jwt_secret.get_secret_value()
    if settings.app_env == "production" and settings.auth_mode == "jwt" and len(jwt_secret) < 32:
        raise RuntimeError("APP_ENV=production needs JWT_SECRET (32+ random characters).")
    if jwt_secret and len(jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters.")
    for name in ("worker_access_code", "supervisor_access_code", "admin_access_code"):
        value = getattr(settings, name).get_secret_value()
        if value and len(value.strip()) < 6:
            raise RuntimeError(f"{name.upper()} must be at least 6 characters.")
    if not jwt_secret:
        # Development: a random secret for this run only (everyone signs in again after a restart).
        jwt_secret = secrets.token_urlsafe(48)
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels

    engine = make_engine(settings.database_url)
    init_schema(engine)
    session_factory = make_session_factory(engine)
    storage = LocalImageStorage(settings.storage_dir)
    categories = load_categories(CATEGORIES_FILE)

    def seed() -> None:
        with session_factory() as session:
            ensure_users(session)
            ensure_plans(session)
            if settings.seed_demo_data and settings.app_env != "production":
                seed_demo_data(session, storage, settings, categories)
                seed_kavach_demo(session)
            if settings.team_demo:
                from geosatya.kavach.teamdemo import seed_team
                seed_team(session)
            session.commit()

    def reset_demo(by: str = "unknown") -> str | None:
        """Drop and rebuild the local demo database (demo mode only). A SQLite
        database is copied to data/backups/ first, so a reset can be undone."""
        backup = None
        db_path = Path(settings.database_url.split("///", 1)[-1]) if settings.database_url.startswith("sqlite") else None
        if db_path is not None and db_path.is_file():
            backups = db_path.parent / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / f"{db_path.stem}-before-reset-{datetime.now():%Y%m%d-%H%M%S}.db"
            with sqlite3.connect(db_path) as src, sqlite3.connect(backup) as dst:
                src.backup(dst)  # consistent copy even while the server is running
        log.warning("DEMO_RESET by=%s backup=%s", by, backup)
        Base.metadata.drop_all(engine)
        init_schema(engine)
        seed()
        return str(backup) if backup else None

    seed()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="GeoSatya API", version=settings.app_version, lifespan=lifespan,
                  description="Geolocation-restricted civic incident reporting and worker verification (KAVACH module).")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.categories = categories
    app.state.reset_demo = reset_demo
    # Incident Intelligence is a separate service; without a URL, reports are
    # still accepted and marked "analysis not configured".
    app.state.intelligence = (IntelligenceClient(settings.intelligence_url, settings.intelligence_timeout_s)
                              if settings.intelligence_url else None)
    # Road routing is optional; None means straight-line estimates everywhere.
    app.state.router = make_router(settings)
    # Team agents after Intelligence (Duplicate Detection, Supervisor, Sanitation); each optional.
    app.state.agents = make_team_agents(settings)
    app.state.verifier = make_verifier(settings, log)
    app.state.report_limiter = SlidingWindowLimiter(settings.report_rate_limit_per_min)
    app.state.auth_limiter = SlidingWindowLimiter(settings.login_rate_limit_per_min)
    app.state.jwt_secret = jwt_secret

    if settings.cors_list():
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list(), allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Content-Type", "Authorization", "X-GeoSatya-Demo-User", "Idempotency-Key"])
    if settings.access_code.get_secret_value():
        if len(settings.access_code.get_secret_value()) < 6:
            raise RuntimeError("ACCESS_CODE must be at least 6 characters.")
        install_access_gate(app, settings.access_code.get_secret_value(), settings.access_cookie_hours)
    register_error_handlers(app)
    # Every API route passes the central authorization check (geosatya/authz.py) before its handler.
    checked = [Depends(authorize)]
    for api_router in (auth_router, router, kavach_router, citizen_worker_router, women_router, audio_router):
        app.include_router(api_router, prefix=settings.api_prefix, dependencies=checked)

    @app.get("/health", tags=["App"])
    def health():
        return {"status": "ok", "service": settings.app_name, "auth_mode": settings.auth_mode}

    if FRONTEND_DIR.is_dir():
        # Mounted last so /api, /docs and /health keep priority.
        app.mount("/", FrontendFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
# Run with: uvicorn geosatya.main:create_app --factory --reload
