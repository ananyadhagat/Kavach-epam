import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db.database import parse_database_url
from app.db.models import Base

config = context.config

if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Only used to pick the SQL dialect for "alembic upgrade head --sql".
OFFLINE_PLACEHOLDER_URL = "postgresql+asyncpg://user@localhost/kavach"


def database_url(offline: bool = False):
    # Tests pass their URL programmatically; otherwise use DATABASE_URL.
    url = config.attributes.get("database_url")

    if url is None:
        configured = get_settings().database_url

        if configured is not None:
            url = configured.get_secret_value()
        elif offline:
            url = OFFLINE_PLACEHOLDER_URL
        else:
            raise RuntimeError(
                "DATABASE_URL is not configured. Set it in .env or the "
                "environment before running migrations."
            )

    return parse_database_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(offline=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)

    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
