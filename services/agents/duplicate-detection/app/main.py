"""ASGI entry point for the KAVACH duplicate-detection service.

The application keeps its original zero-configuration behaviour: when neither
``KAVACH_DATABASE_URL`` nor ``DATABASE_URL`` is set, it starts with an empty
in-memory M3 repository and no consolidation routes.

When a database URL is configured, the process builds the SQLAlchemy engine and
mounts the consolidation routes. No connection is opened at import time; run the
migrations before serving traffic::

    alembic upgrade head
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.app import create_app
from app.config.database import get_database_url
from app.db.session import build_session_factory
from app.services.consolidation_service import ConsolidationService


def build_app() -> FastAPI:
    """Build the application for the current environment.

    A configured database enables persistent consolidation. Without one, the
    original in-memory application is returned unchanged.
    """

    database_url = get_database_url()
    if database_url is None:
        return create_app()

    engine, session_factory = build_session_factory(database_url)
    consolidation_service = ConsolidationService(session_factory)
    application = create_app(consolidation_service=consolidation_service)
    # Keep the engine alive for the process lifetime and expose it for health
    # checks and shutdown hooks without importing it in the API layer.
    application.state.database_engine = engine
    return application


app = build_app()

__all__ = ["app", "build_app"]
