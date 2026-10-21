import asyncio

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import BASE_DIR, Settings
from app.repositories.completion_repository import CompletionRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.location_repository import LocationRepository
from app.repositories.task_repository import TaskRepository

ALEMBIC_INI = BASE_DIR / "alembic.ini"


class DatabaseConfigurationError(RuntimeError):
    """Raised when PostgreSQL is missing, unreachable or not migrated."""


def parse_database_url(raw_url: str) -> URL:
    try:
        url = make_url(raw_url)
    except ArgumentError as exc:
        raise DatabaseConfigurationError(
            "DATABASE_URL is not a valid database URL."
        ) from exc

    # Accept plain postgresql:// URLs and use the asyncpg driver.
    if url.drivername in {"postgresql", "postgres"}:
        url = url.set(drivername="postgresql+asyncpg")

    if url.drivername != "postgresql+asyncpg":
        raise DatabaseConfigurationError(
            "Only PostgreSQL is supported. Use a "
            "postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DBNAME URL."
        )

    if not url.database:
        raise DatabaseConfigurationError("DATABASE_URL has no database name.")

    # An unencoded "@" in the password shifts part of the password into the
    # host. Reject that without echoing the host, which may contain secrets.
    if url.host and any(char in url.host for char in "@<> \t"):
        raise DatabaseConfigurationError(
            "DATABASE_URL host is malformed. Percent-encode special "
            "characters in the password (@ -> %40, : -> %3A, / -> %2F) and "
            "remove any <placeholder> brackets."
        )

    return url


def safe_url(url: URL) -> str:
    return url.render_as_string(hide_password=True)


def alembic_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BASE_DIR / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


async def verify_schema(connection: AsyncConnection) -> None:
    exists = await connection.scalar(
        text("SELECT to_regclass('alembic_version') IS NOT NULL")
    )
    current = None

    if exists:
        current = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )

    head = alembic_head()

    if current != head:
        raise DatabaseConfigurationError(
            f"Database schema is at revision {current or 'none'}, "
            f"expected {head}. Run: alembic upgrade head"
        )


class UnitOfWork:
    """One database transaction shared by all repositories.

    Commits when the block exits normally and rolls back on any exception,
    so operations either fully succeed or leave no partial changes.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self._session_factory()
        await self.session.begin()
        self.tasks = TaskRepository(self.session)
        self.evidence = EvidenceRepository(self.session)
        self.locations = LocationRepository(self.session)
        self.completions = CompletionRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()


class Database:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.session_factory = async_sessionmaker(
            engine, expire_on_commit=False
        )

    def unit_of_work(self) -> UnitOfWork:
        return UnitOfWork(self.session_factory)

    @classmethod
    async def connect(cls, settings: Settings,
                      check_schema: bool = True) -> "Database":
        if settings.database_url is None:
            raise DatabaseConfigurationError(
                "DATABASE_URL is not configured. KAVACH requires PostgreSQL; "
                "see README.md (Database setup)."
            )

        url = parse_database_url(settings.database_url.get_secret_value())
        timeout = settings.database_connect_timeout_seconds
        engine = create_async_engine(
            url,
            pool_pre_ping=True,
            connect_args={"timeout": timeout},
        )

        try:
            async with asyncio.timeout(timeout + 1):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))

                    if check_schema:
                        await verify_schema(connection)

        except DatabaseConfigurationError:
            await engine.dispose()
            raise

        except Exception as exc:
            await engine.dispose()
            # The password is hidden; the underlying error type is kept.
            raise DatabaseConfigurationError(
                f"PostgreSQL is unavailable at {safe_url(url)} "
                f"({type(exc).__name__}). Check that the server is running "
                "and DATABASE_URL is correct."
            ) from exc

        return cls(engine)

    async def dispose(self) -> None:
        await self.engine.dispose()
