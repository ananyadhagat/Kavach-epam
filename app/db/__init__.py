"""Database foundation for the KAVACH consolidation store.

This package owns the SQLAlchemy declarative base and ORM models only. It does
not contain business logic, scoring, or HTTP code. The consolidation service
depends on it through the repository layer.
"""

from app.db.base import Base
from app.db.models import (
    ComplaintRecord,
    ConsolidationGroup,
    ConsolidationLink,
    ConsolidationRequest,
    ConsolidationReview,
)

__all__ = [
    "Base",
    "ComplaintRecord",
    "ConsolidationGroup",
    "ConsolidationLink",
    "ConsolidationRequest",
    "ConsolidationReview",
]
