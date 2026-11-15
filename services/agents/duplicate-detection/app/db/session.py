"""Engine and session helpers for the consolidation database.

The application never connects at import time. ``create_db_engine`` only builds
an engine; connections are opened on first use. Tests may use SQLite in memory;
production uses PostgreSQL through psycopg2.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy URL with the psycopg2 driver selected.

    Accepts the common ``postgres://`` and ``postgresql://`` forms emitted by
    hosting providers and leaves URLs that already name a driver untouched.
    """

    value = url.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg2://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg2://" + value[len("postgresql://") :]
    return value


def create_db_engine(url: str, *, echo: bool = False) -> Engine:
    """Build an :class:`~sqlalchemy.Engine` for ``url``.

    SQLite in-memory databases use a ``StaticPool`` so every session in the
    process sees the same database. This is a test convenience; production uses
    PostgreSQL.
    """

    normalized = normalize_database_url(url)
    if normalized.startswith("sqlite"):
        connect_args: dict[str, object] = {}
        if ":memory:" in normalized:
            connect_args["check_same_thread"] = False
            engine = create_engine(
                normalized,
                echo=echo,
                future=True,
                connect_args=connect_args,
                poolclass=StaticPool,
            )
        else:
            engine = create_engine(normalized, echo=echo, future=True)
        _enable_sqlite_foreign_keys(engine)
        return engine
    return create_engine(
        normalized,
        echo=echo,
        future=True,
        pool_pre_ping=True,
    )


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Enforce declared foreign keys on SQLite, which is off by default.

    Production uses PostgreSQL, where foreign keys are always enforced. Turning
    them on for SQLite keeps test behaviour close to production.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def build_session_factory(
    url: str,
    *,
    echo: bool = False,
) -> tuple[Engine, sessionmaker[Session]]:
    """Create an engine and a session factory for ``url``."""

    engine = create_db_engine(url, echo=echo)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    return engine, factory


@contextmanager
def session_scope(
    factory: sessionmaker[Session],
) -> Iterator[Session]:
    """Yield a session inside a transaction and close it afterwards.

    Commits on success and rolls back on any exception. Callers that need
    explicit control can use ``factory()`` directly.
    """

    session = factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()


__all__ = [
    "build_session_factory",
    "create_db_engine",
    "normalize_database_url",
    "session_scope",
]
