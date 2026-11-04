"""Alembic environment for the KAVACH consolidation database.

The URL is resolved from ``KAVACH_DATABASE_URL`` / ``DATABASE_URL`` first, then
from ``alembic.ini``. This avoids duplicating database configuration between the
application and the migration tool.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config.database import get_database_url
from app.db.base import Base
from app.db.models import (  # noqa: F401 - imported for metadata registration
    ComplaintRecord,
    ConsolidationGroup,
    ConsolidationLink,
    ConsolidationRequest,
    ConsolidationReview,
)
from app.db.session import normalize_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the migration URL without connecting to the database."""

    configured = get_database_url()
    if configured is not None:
        return normalize_database_url(configured)

    from_config = config.get_main_option("sqlalchemy.url")
    if from_config and from_config.strip():
        return normalize_database_url(from_config)

    raise RuntimeError(
        "No database URL configured. Set KAVACH_DATABASE_URL (or "
        "DATABASE_URL), or set sqlalchemy.url in alembic.ini."
    )


def run_migrations_offline() -> None:
    """Emit SQL without a live database connection."""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
