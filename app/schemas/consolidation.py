"""Request and response schemas for the consolidation API.

The M3 wire contract in :mod:`app.schemas.m3_response` is intentionally not
extended. Consolidation uses its own response models under
``/internal/v1/consolidation``.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import Decision


class ConsolidationStatus(str, Enum):
    """Where a stored complaint sits in the consolidation lifecycle."""

    PRIMARY = "PRIMARY"
    DUPLICATE = "DUPLICATE"
    PENDING_REVIEW = "PENDING_REVIEW"


class GroupStatus(str, Enum):
    """Lifecycle of a consolidation group."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReviewStatus(str, Enum):
    """Lifecycle of a pending review case."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConsolidationResult(BaseModel):
    """Result of ingesting one complaint."""

    model_config = ConfigDict(extra="forbid")

    complaint_id: str
    consolidation_status: ConsolidationStatus
    decision: Decision
    group_id: str | None = None
    primary_complaint_id: str | None = None
    matched_incident_id: str | None = None
    leading_candidate_id: str | None = None
    score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    active_duplicate_count: int = 0
    historical_duplicate_count: int = 0
    review_id: str | None = None
    idempotent_replay: bool = False


class GroupSummaryResponse(BaseModel):
    """Supervisor/Dispatch-facing summary of one group."""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    primary_complaint_id: str
    status: GroupStatus
    active_duplicate_count: int
    historical_duplicate_count: int
    member_count: int
    created_at: datetime
    closed_at: datetime | None = None


class DuplicateMember(BaseModel):
    """One duplicate complaint plus the evidence that linked it."""

    model_config = ConfigDict(extra="forbid")

    complaint: Complaint
    link_id: str
    matched_incident_id: str | None = None
    match_score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    linked_at: datetime


class GroupDetailResponse(GroupSummaryResponse):
    """A group with its canonical primary and duplicate members."""

    primary: Complaint
    duplicates: list[DuplicateMember] = Field(default_factory=list)


class ReviewResponse(BaseModel):
    """A pending review case without its complaint body."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    complaint_id: str
    status: ReviewStatus
    decision: Decision
    leading_candidate_id: str | None = None
    score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    resolved_at: datetime | None = None


class ReviewQueueItem(ReviewResponse):
    """A review case including the complaint awaiting resolution."""

    complaint: Complaint


class ComplaintDetailResponse(BaseModel):
    """Stored complaint, its consolidation status, and related records."""

    model_config = ConfigDict(extra="forbid")

    complaint: Complaint
    consolidation_status: ConsolidationStatus
    group: GroupSummaryResponse | None = None
    review: ReviewResponse | None = None
    received_at: datetime


class PaginatedGroups(BaseModel):
    """A page of consolidation groups."""

    model_config = ConfigDict(extra="forbid")

    items: list[GroupSummaryResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class PaginatedReviews(BaseModel):
    """A page of pending review cases."""

    model_config = ConfigDict(extra="forbid")

    items: list[ReviewQueueItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


__all__ = [
    "ComplaintDetailResponse",
    "ConsolidationResult",
    "ConsolidationStatus",
    "DuplicateMember",
    "GroupDetailResponse",
    "GroupStatus",
    "GroupSummaryResponse",
    "PaginatedGroups",
    "PaginatedReviews",
    "ReviewQueueItem",
    "ReviewResponse",
    "ReviewStatus",
]
