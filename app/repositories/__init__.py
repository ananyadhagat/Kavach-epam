"""Candidate retrieval abstractions and prototype implementations.

The repository is the single storage-aware part of the agent. It never scores
similarity and never decides whether two complaints are duplicates; it only
stores and returns complaint records.
"""

from app.repositories.base import ComplaintRepository, RepositoryError
from app.repositories.in_memory import InMemoryComplaintRepository

__all__ = [
    "ComplaintRepository",
    "InMemoryComplaintRepository",
    "RepositoryError",
]
