from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image

from geosatya.api.routes import register_error_handlers, router
from geosatya.categories import load_categories
from geosatya.config import BASE_DIR, Settings, get_settings
from geosatya.db import init_schema, make_engine, make_session_factory
from geosatya.media.storage import LocalImageStorage
from geosatya.models import Base
from geosatya.seed import ensure_users, seed_demo_data

FRONTEND_DIR = BASE_DIR / "frontend"


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
    if settings.app_env == "production" and settings.auth_mode == "demo":
        raise RuntimeError("AUTH_MODE=demo is not allowed when APP_ENV=production. "
                           "Connect an identity provider or use AUTH_MODE=token.")
    if settings.auth_mode == "token" and not settings.token_map():
        raise RuntimeError("AUTH_MODE=token needs AUTH_TOKENS.")
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels

    engine = make_engine(settings.database_url)
    init_schema(engine)
    session_factory = make_session_factory(engine)
    storage = LocalImageStorage(settings.storage_dir)
    categories = load_categories(CATEGORIES_FILE)

    def seed() -> None:
        with session_factory() as session:
            ensure_users(session)
            if settings.seed_demo_data and settings.app_env != "production":
                seed_demo_data(session, storage, settings, categories)
            session.commit()

    def reset_demo() -> None:
        """Drop and rebuild the local demo database (demo mode only)."""
        Base.metadata.drop_all(engine)
        init_schema(engine)
        seed()

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

    if settings.cors_list():
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list(), allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT"],
                           allow_headers=["Content-Type", "Authorization", "X-GeoSatya-Demo-User"])
    register_error_handlers(app)
    app.include_router(router, prefix=settings.api_prefix)

    @app.get("/health", tags=["App"])
    def health():
        return {"status": "ok", "service": settings.app_name, "auth_mode": settings.auth_mode}

    if FRONTEND_DIR.is_dir():
        # Mounted last so /api, /docs and /health keep priority.
        app.mount("/", FrontendFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
# Run with: uvicorn geosatya.main:create_app --factory --reload
