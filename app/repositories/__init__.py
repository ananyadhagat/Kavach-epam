"""Candidate retrieval abstractions and implementations.

The repository is the single storage-aware part of the agent. It never scores
similarity and never decides whether two complaints are duplicates; it only
stores and returns complaint records.
"""

from app.repositories.base import (
    CandidateRetrieval,
    ComplaintRepository,
    RepositoryError,
    RetrievalFailure,
    RetrievalOutcome,
)
from app.repositories.in_memory import InMemoryComplaintRepository
from app.repositories.sql_complaint import (
    DatabaseComplaintRepository,
    SessionComplaintRepository,
)

__all__ = [
    "CandidateRetrieval",
    "ComplaintRepository",
    "DatabaseComplaintRepository",
    "InMemoryComplaintRepository",
    "RepositoryError",
    "RetrievalFailure",
    "RetrievalOutcome",
    "SessionComplaintRepository",
]
