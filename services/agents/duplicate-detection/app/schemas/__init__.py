"""Pydantic request/response schemas for the Duplicate Detection Agent.

These models are the transport-free contracts agreed in Phase 1
(``docs/duplicate_detection/api_contract.md``). Consolidation schemas are
additive and live under their own prefix; the M3 wire contract is unchanged.
They are re-exported here for convenient imports.
"""

from app.schemas.complaint import Complaint, Location
from app.schemas.consolidation import (
    ComplaintDetailResponse,
    ConsolidationResult,
    ConsolidationStatus,
    DuplicateMember,
    GroupDetailResponse,
    GroupStatus,
    GroupSummaryResponse,
    PaginatedGroups,
    PaginatedReviews,
    ReviewQueueItem,
    ReviewResponse,
    ReviewStatus,
)
from app.schemas.duplicate_response import (
    Decision,
    DuplicateDetectionResponse,
    SignalResult,
    SignalStatus,
)
from app.schemas.m3_response import (
    M3Candidate,
    M3DuplicateCheckResponse,
    M3Error,
    ProcessingStatus,
)

__all__ = [
    "Complaint",
    "Location",
    "Decision",
    "SignalStatus",
    "SignalResult",
    "DuplicateDetectionResponse",
    "M3Candidate",
    "M3DuplicateCheckResponse",
    "M3Error",
    "ProcessingStatus",
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
