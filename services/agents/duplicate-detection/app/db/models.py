"""ORM models for complaints, consolidation groups, links and reviews.

Design notes
------------
* Every complaint is stored individually and is never deleted by consolidation.
* A complaint is either linked to exactly one group (as ``PRIMARY`` or
  ``DUPLICATE``) or attached to a pending review. A complaint with a review has
  no link.
* ``consolidation_groups.primary_complaint_id`` is a denormalised pointer to
  the canonical complaint. The service keeps it consistent with the group's
  ``PRIMARY`` link.
* IDs for groups, links, reviews and requests are UUID4 strings. Complaint IDs
  remain the opaque 1-64 character IDs from the existing contract.
* JSON columns use PostgreSQL ``JSONB`` when available and plain ``JSON``
  elsewhere (notably SQLite in tests).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Portable JSON type with a JSONB variant on PostgreSQL.
JsonType = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def ensure_aware(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes returned by SQLite.

    PostgreSQL returns timezone-aware values for ``TIMESTAMP WITH TIME ZONE``.
    SQLite stores the same logical value without an offset, so mapping helpers
    normalise it to UTC to keep API responses consistent across backends.
    """

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ComplaintRecord(Base):
    """One stored complaint, preserved verbatim for audit and retrieval."""

    __tablename__ = "complaints"

    complaint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    facility_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    image_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        Index("ix_complaints_reported_at", "reported_at"),
        Index("ix_complaints_received_at", "received_at"),
    )


class ConsolidationGroup(Base):
    """A canonical primary complaint plus its duplicate members."""

    __tablename__ = "consolidation_groups"

    group_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    primary_complaint_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("complaints.complaint_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    active_duplicate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    historical_duplicate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    creation_reason: Mapped[str] = mapped_column(
        String(64), nullable=False, default="M3_NEW"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')", name="group_status"
        ),
        CheckConstraint(
            "active_duplicate_count >= 0", name="active_count_non_negative"
        ),
        CheckConstraint(
            "historical_duplicate_count >= 0",
            name="historical_count_non_negative",
        ),
        Index("ix_consolidation_groups_status", "status"),
    )


class ConsolidationLink(Base):
    """Membership of one complaint in one consolidation group."""

    __tablename__ = "consolidation_links"

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("consolidation_groups.group_id", ondelete="RESTRICT"),
        nullable=False,
    )
    complaint_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("complaints.complaint_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    matched_incident_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons: Mapped[list[str] | None] = mapped_column(JsonType, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('PRIMARY', 'DUPLICATE')", name="link_role"
        ),
        Index("ix_consolidation_links_group", "group_id"),
    )


class ConsolidationReview(Base):
    """A complaint M3 could not safely link; a human must resolve it."""

    __tablename__ = "consolidation_reviews"

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("complaints.complaint_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    decision: Mapped[str] = mapped_column(
        String(32), nullable=False, default="REVIEW_REQUIRED"
    )
    leading_candidate_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons: Mapped[list[str] | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')", name="review_status"
        ),
        Index("ix_consolidation_reviews_status", "status"),
    )


class ConsolidationRequest(Base):
    """Stored idempotency record and response snapshot for one ingestion."""

    __tablename__ = "consolidation_requests"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("complaints.complaint_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(
        JsonType, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


__all__ = [
    "ComplaintRecord",
    "ConsolidationGroup",
    "ConsolidationLink",
    "ConsolidationRequest",
    "ConsolidationReview",
    "JsonType",
    "utc_now",
]
