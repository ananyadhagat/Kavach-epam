"""Alembic migration tests for the consolidation schema.

The tests run the real migration scripts against a temporary SQLite file. They
verify the resulting schema (tables, columns, keys, indexes and check
constraints), that the downgrade removes everything, and that missing database
configuration fails loudly instead of silently migrating the wrong database.

SQLite is a convenience target here. It is **not** evidence that the migration
has been exercised against PostgreSQL; see the consolidation documentation for
the current PostgreSQL verification status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ComplaintRecord, ConsolidationGroup
from app.db.session import build_session_factory

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"
ALEMBIC_DIR = ROOT / "alembic"

EXPECTED_TABLES = {
    "complaints",
    "consolidation_groups",
    "consolidation_links",
    "consolidation_reviews",
    "consolidation_requests",
}

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _alembic_config(url: str | None) -> Config:
    """Build an Alembic config pointed at this repository."""

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", url or "")
    return config


@pytest.fixture
def database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Temporary SQLite database URL with the environment configured."""

    url = f"sqlite:///{tmp_path / 'consolidation_migration.db'}"
    monkeypatch.setenv("KAVACH_DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return url


@pytest.fixture
def migrated(
    database_url: str,
) -> tuple[str, sessionmaker[Session]]:
    """Apply the migration and return the URL plus a session factory."""

    command.upgrade(_alembic_config(database_url), "head")
    engine, factory = build_session_factory(database_url)
    try:
        yield database_url, factory
    finally:
        engine.dispose()


def _inspect(url: str) -> dict[str, object]:
    """Reflect the whole schema into plain dictionaries.

    The engine is disposed only after every reflection call has completed, so
    the returned data is self-contained and safe to assert on later.
    """

    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        return {
            "tables": set(inspector.get_table_names()),
            "columns": {
                table: {
                    column["name"]: {
                        "nullable": column["nullable"],
                        "type": str(column["type"]),
                    }
                    for column in inspector.get_columns(table)
                }
                for table in inspector.get_table_names()
            },
            "uniques": {
                table: {
                    tuple(constraint["column_names"])
                    for constraint in inspector.get_unique_constraints(table)
                }
                for table in inspector.get_table_names()
            },
            "indexes": {
                table: {
                    index["name"]: (
                        tuple(index["column_names"]),
                        bool(index["unique"]),
                    )
                    for index in inspector.get_indexes(table)
                }
                for table in inspector.get_table_names()
            },
            "checks": {
                table: {
                    constraint["name"]
                    for constraint in inspector.get_check_constraints(table)
                }
                for table in inspector.get_table_names()
            },
            "foreign_keys": {
                table: {
                    (
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        tuple(fk["referred_columns"]),
                    )
                    for fk in inspector.get_foreign_keys(table)
                }
                for table in inspector.get_table_names()
            },
        }
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# Upgrade
# --------------------------------------------------------------------------- #
def test_upgrade_creates_every_expected_table(migrated) -> None:
    url, _ = migrated
    schema = _inspect(url)
    tables = schema["tables"]

    assert isinstance(tables, set)
    assert EXPECTED_TABLES <= tables
    assert "alembic_version" in tables


def test_complaints_schema(migrated) -> None:
    url, _ = migrated
    schema = _inspect(url)
    columns = schema["columns"]["complaints"]

    assert set(columns) == {
        "complaint_id",
        "description",
        "category",
        "facility_id",
        "location_id",
        "latitude",
        "longitude",
        "reported_at",
        "image_hash",
        "payload",
        "received_at",
    }
    assert columns["complaint_id"]["nullable"] is False
    assert columns["received_at"]["nullable"] is False
    assert columns["description"]["nullable"] is True
    assert columns["reported_at"]["nullable"] is True

    indexes = schema["indexes"]["complaints"]
    assert indexes["ix_complaints_reported_at"] == (("reported_at",), False)
    assert indexes["ix_complaints_received_at"] == (("received_at",), False)


def test_group_schema(migrated) -> None:
    url, _ = migrated
    schema = _inspect(url)
    columns = schema["columns"]["consolidation_groups"]

    assert set(columns) == {
        "group_id",
        "primary_complaint_id",
        "status",
        "active_duplicate_count",
        "historical_duplicate_count",
        "creation_reason",
        "created_at",
        "closed_at",
    }
    for required in (
        "group_id",
        "primary_complaint_id",
        "status",
        "active_duplicate_count",
        "historical_duplicate_count",
        "creation_reason",
        "created_at",
    ):
        assert columns[required]["nullable"] is False

    assert schema["uniques"]["consolidation_groups"] == {
        ("primary_complaint_id",)
    }
    assert schema["indexes"]["consolidation_groups"][
        "ix_consolidation_groups_status"
    ] == (("status",), False)

    checks = schema["checks"]["consolidation_groups"]
    assert {
        "ck_consolidation_groups_group_status",
        "ck_consolidation_groups_active_count_non_negative",
        "ck_consolidation_groups_historical_count_non_negative",
    } <= checks

    assert schema["foreign_keys"]["consolidation_groups"] == {
        (("primary_complaint_id",), "complaints", ("complaint_id",))
    }


def test_link_schema(migrated) -> None:
    url, _ = migrated
    schema = _inspect(url)
    columns = schema["columns"]["consolidation_links"]

    assert set(columns) == {
        "link_id",
        "group_id",
        "complaint_id",
        "role",
        "matched_incident_id",
        "match_score",
        "reasons",
        "linked_at",
    }
    for required in ("link_id", "group_id", "complaint_id", "role", "linked_at"):
        assert columns[required]["nullable"] is False

    assert schema["uniques"]["consolidation_links"] == {("complaint_id",)}
    assert schema["indexes"]["consolidation_links"][
        "ix_consolidation_links_group"
    ] == (("group_id",), False)

    assert "ck_consolidation_links_link_role" in schema["checks"][
        "consolidation_links"
    ]
    assert schema["foreign_keys"]["consolidation_links"] == {
        (("complaint_id",), "complaints", ("complaint_id",)),
        (("group_id",), "consolidation_groups", ("group_id",)),
    }


def test_review_schema(migrated) -> None:
    url, _ = migrated
    schema = _inspect(url)
    columns = schema["columns"]["consolidation_reviews"]

    assert set(columns) == {
        "review_id",
        "complaint_id",
        "status",
        "decision",
        "leading_candidate_id",
        "score",
        "reasons",
        "created_at",
        "resolved_at",
    }
    for required in ("review_id", "complaint_id", "status", "decision", "created_at"):
        assert columns[required]["nullable"] is False

    assert schema["uniques"]["consolidation_reviews"] == {("complaint_id",)}
    assert schema["indexes"]["consolidation_reviews"][
        "ix_consolidation_reviews_status"
    ] == (("status",), False)
    assert "ck_consolidation_reviews_review_status" in schema["checks"][
        "consolidation_reviews"
    ]
    assert schema["foreign_keys"]["consolidation_reviews"] == {
        (("complaint_id",), "complaints", ("complaint_id",))
    }


def test_request_schema(migrated) -> None:
    url, _ = migrated
    schema = _inspect(url)
    columns = schema["columns"]["consolidation_requests"]

    assert set(columns) == {
        "idempotency_key",
        "complaint_id",
        "fingerprint",
        "response_status",
        "response_body",
        "created_at",
    }
    for required in (
        "idempotency_key",
        "complaint_id",
        "fingerprint",
        "response_status",
        "response_body",
        "created_at",
    ):
        assert columns[required]["nullable"] is False

    assert schema["uniques"]["consolidation_requests"] == {("complaint_id",)}
    assert schema["foreign_keys"]["consolidation_requests"] == {
        (("complaint_id",), "complaints", ("complaint_id",))
    }


# --------------------------------------------------------------------------- #
# Constraints behave when written to
# --------------------------------------------------------------------------- #
def test_migrated_schema_enforces_constraints(migrated) -> None:
    _, factory = migrated

    with factory() as session:
        with session.begin():
            session.add_all(
                [
                    ComplaintRecord(
                        complaint_id="CMP-A",
                        description="Primary",
                        payload=None,
                        received_at=NOW,
                    ),
                    ComplaintRecord(
                        complaint_id="CMP-B",
                        description="Duplicate",
                        payload=None,
                        received_at=NOW,
                    ),
                ]
            )

    with pytest.raises(IntegrityError):
        with factory() as session:
            with session.begin():
                session.add(
                    ComplaintRecord(
                        complaint_id="CMP-A",
                        description="Duplicate primary key",
                        payload=None,
                        received_at=NOW,
                    )
                )

    with pytest.raises(IntegrityError):
        with factory() as session:
            with session.begin():
                session.add(
                    ConsolidationGroup(
                        group_id="11111111-1111-4111-8111-111111111111",
                        primary_complaint_id="CMP-A",
                        status="INVALID",
                        active_duplicate_count=0,
                        historical_duplicate_count=0,
                        creation_reason="NEW",
                        created_at=NOW,
                    )
                )

    with factory() as session:
        with session.begin():
            session.add(
                ConsolidationGroup(
                    group_id="11111111-1111-4111-8111-111111111111",
                    primary_complaint_id="CMP-A",
                    status="OPEN",
                    active_duplicate_count=0,
                    historical_duplicate_count=0,
                    creation_reason="NEW",
                    created_at=NOW,
                )
            )

    with pytest.raises(IntegrityError):
        with factory() as session:
            with session.begin():
                session.add(
                    ConsolidationGroup(
                        group_id="22222222-2222-4222-8222-222222222222",
                        primary_complaint_id="CMP-A",
                        status="OPEN",
                        active_duplicate_count=0,
                        historical_duplicate_count=0,
                        creation_reason="NEW",
                        created_at=NOW,
                    )
                )

    with pytest.raises(IntegrityError):
        # SQLite only enforces this because `create_db_engine` turns the
        # foreign_keys pragma on.
        with factory() as session:
            with session.begin():
                session.add(
                    ConsolidationGroup(
                        group_id="33333333-3333-4333-8333-333333333333",
                        primary_complaint_id="MISSING",
                        status="OPEN",
                        active_duplicate_count=0,
                        historical_duplicate_count=0,
                        creation_reason="NEW",
                        created_at=NOW,
                    )
                )


# --------------------------------------------------------------------------- #
# Downgrade and configuration errors
# --------------------------------------------------------------------------- #
def test_downgrade_removes_every_table(database_url) -> None:
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    assert tables == {"alembic_version"}


def test_missing_database_url_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KAVACH_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="No database URL configured"):
        command.upgrade(_alembic_config(None), "head")
