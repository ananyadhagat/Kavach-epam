"""Persistence helpers for consolidation groups, links, reviews and requests.

This module is deliberately thin: it translates between the service's domain
objects and SQLAlchemy rows. It contains no decision policy and no scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    ComplaintRecord,
    ConsolidationGroup,
    ConsolidationLink,
    ConsolidationRequest,
    ConsolidationReview,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class GroupSummary:
    group_id: str
    primary_complaint_id: str
    status: str
    active_duplicate_count: int
    historical_duplicate_count: int
    created_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class LinkSummary:
    link_id: str
    group_id: str
    complaint_id: str
    role: str
    matched_incident_id: str | None
    match_score: float | None
    reasons: tuple[str, ...]
    linked_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    review_id: str
    complaint_id: str
    status: str
    decision: str
    leading_candidate_id: str | None
    score: float | None
    reasons: tuple[str, ...]
    created_at: datetime
    resolved_at: datetime | None


def group_summary(group: ConsolidationGroup) -> GroupSummary:
    return GroupSummary(
        group_id=group.group_id,
        primary_complaint_id=group.primary_complaint_id,
        status=group.status,
        active_duplicate_count=group.active_duplicate_count,
        historical_duplicate_count=group.historical_duplicate_count,
        created_at=group.created_at,
        closed_at=group.closed_at,
    )


def link_summary(link: ConsolidationLink) -> LinkSummary:
    return LinkSummary(
        link_id=link.link_id,
        group_id=link.group_id,
        complaint_id=link.complaint_id,
        role=link.role,
        matched_incident_id=link.matched_incident_id,
        match_score=link.match_score,
        reasons=tuple(link.reasons or ()),
        linked_at=link.linked_at,
    )


def review_summary(review: ConsolidationReview) -> ReviewSummary:
    return ReviewSummary(
        review_id=review.review_id,
        complaint_id=review.complaint_id,
        status=review.status,
        decision=review.decision,
        leading_candidate_id=review.leading_candidate_id,
        score=review.score,
        reasons=tuple(review.reasons or ()),
        created_at=review.created_at,
        resolved_at=review.resolved_at,
    )


def get_complaint(session: Session, complaint_id: str) -> ComplaintRecord | None:
    return session.get(ComplaintRecord, complaint_id)


def get_group(session: Session, group_id: str) -> ConsolidationGroup | None:
    return session.get(ConsolidationGroup, group_id)


def get_group_by_primary(
    session: Session, primary_complaint_id: str
) -> ConsolidationGroup | None:
    return session.execute(
        select(ConsolidationGroup).where(
            ConsolidationGroup.primary_complaint_id == primary_complaint_id
        )
    ).scalar_one_or_none()


def get_link(session: Session, complaint_id: str) -> ConsolidationLink | None:
    return session.execute(
        select(ConsolidationLink).where(
            ConsolidationLink.complaint_id == complaint_id
        )
    ).scalar_one_or_none()


def get_link_for_group(
    session: Session, group_id: str, role: str
) -> ConsolidationLink | None:
    return session.execute(
        select(ConsolidationLink)
        .where(
            ConsolidationLink.group_id == group_id,
            ConsolidationLink.role == role,
        )
        .order_by(ConsolidationLink.linked_at)
    ).scalars().first()


def get_review(
    session: Session, complaint_id: str
) -> ConsolidationReview | None:
    return session.execute(
        select(ConsolidationReview).where(
            ConsolidationReview.complaint_id == complaint_id
        )
    ).scalar_one_or_none()


def get_request(
    session: Session, idempotency_key: str
) -> ConsolidationRequest | None:
    return session.get(ConsolidationRequest, idempotency_key)


def get_request_by_complaint(
    session: Session, complaint_id: str
) -> ConsolidationRequest | None:
    return session.execute(
        select(ConsolidationRequest).where(
            ConsolidationRequest.complaint_id == complaint_id
        )
    ).scalar_one_or_none()


def increment_duplicate_counts(session: Session, group_id: str) -> int:
    """Atomically increment both duplicate counters for an open group.

    Returns the number of rows updated. Zero means the group is missing or
    closed; callers translate that into a domain error.
    """

    result = session.execute(
        update(ConsolidationGroup)
        .where(
            ConsolidationGroup.group_id == group_id,
            ConsolidationGroup.status == "OPEN",
        )
        .values(
            active_duplicate_count=(
                ConsolidationGroup.active_duplicate_count + 1
            ),
            historical_duplicate_count=(
                ConsolidationGroup.historical_duplicate_count + 1
            ),
        )
    )
    return int(result.rowcount or 0)


def list_duplicates(
    session: Session, group_id: str
) -> list[tuple[ComplaintRecord, ConsolidationLink]]:
    rows = session.execute(
        select(ComplaintRecord, ConsolidationLink)
        .join(
            ConsolidationLink,
            ConsolidationLink.complaint_id == ComplaintRecord.complaint_id,
        )
        .where(
            ConsolidationLink.group_id == group_id,
            ConsolidationLink.role == "DUPLICATE",
        )
        .order_by(ConsolidationLink.linked_at)
    ).all()
    return [(row[0], row[1]) for row in rows]


def list_groups(
    session: Session,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[ConsolidationGroup], int]:
    filters = []
    if status is not None:
        filters.append(ConsolidationGroup.status == status)
    total = int(
        session.execute(
            select(func.count())
            .select_from(ConsolidationGroup)
            .where(*filters)
        ).scalar_one()
    )
    rows = session.execute(
        select(ConsolidationGroup)
        .where(*filters)
        .order_by(ConsolidationGroup.created_at, ConsolidationGroup.group_id)
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return list(rows), total


def list_reviews(
    session: Session,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[ConsolidationReview], int]:
    filters = []
    if status is not None:
        filters.append(ConsolidationReview.status == status)
    total = int(
        session.execute(
            select(func.count())
            .select_from(ConsolidationReview)
            .where(*filters)
        ).scalar_one()
    )
    rows = session.execute(
        select(ConsolidationReview)
        .where(*filters)
        .order_by(
            ConsolidationReview.created_at,
            ConsolidationReview.review_id,
        )
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return list(rows), total


__all__ = [
    "GroupSummary",
    "LinkSummary",
    "ReviewSummary",
    "get_complaint",
    "get_group",
    "get_group_by_primary",
    "get_link",
    "get_link_for_group",
    "get_request",
    "get_request_by_complaint",
    "get_review",
    "group_summary",
    "increment_duplicate_counts",
    "link_summary",
    "list_duplicates",
    "list_groups",
    "list_reviews",
    "review_summary",
]
