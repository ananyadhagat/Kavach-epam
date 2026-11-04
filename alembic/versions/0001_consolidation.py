"""Create the complaint and consolidation tables.

Revision ID: 0001_consolidation
Revises:
Create Date: 2026-11-04

The migration is deliberately limited to the five consolidation tables. It
does not modify any M3 table or contract because none existed before it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_consolidation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Portable JSON with a JSONB implementation on PostgreSQL.
JSON_TYPE = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "complaints",
        sa.Column("complaint_id", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("facility_id", sa.String(length=64), nullable=True),
        sa.Column("location_id", sa.String(length=64), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image_hash", sa.String(length=128), nullable=True),
        sa.Column("payload", JSON_TYPE, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "complaint_id", name="pk_complaints"
        ),
    )
    op.create_index(
        "ix_complaints_reported_at", "complaints", ["reported_at"]
    )
    op.create_index(
        "ix_complaints_received_at", "complaints", ["received_at"]
    )

    op.create_table(
        "consolidation_groups",
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column(
            "primary_complaint_id", sa.String(length=64), nullable=False
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "active_duplicate_count", sa.Integer(), nullable=False
        ),
        sa.Column(
            "historical_duplicate_count", sa.Integer(), nullable=False
        ),
        sa.Column("creation_reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "closed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="group_status",
        ),
        sa.CheckConstraint(
            "active_duplicate_count >= 0",
            name="active_count_non_negative",
        ),
        sa.CheckConstraint(
            "historical_duplicate_count >= 0",
            name="historical_count_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["primary_complaint_id"],
            ["complaints.complaint_id"],
            name="fk_consolidation_groups_primary_complaint_id_complaints",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("group_id", name="pk_consolidation_groups"),
        sa.UniqueConstraint(
            "primary_complaint_id",
            name="uq_consolidation_groups_primary_complaint_id",
        ),
    )
    op.create_index(
        "ix_consolidation_groups_status",
        "consolidation_groups",
        ["status"],
    )

    op.create_table(
        "consolidation_links",
        sa.Column("link_id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("complaint_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "matched_incident_id", sa.String(length=64), nullable=True
        ),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("reasons", JSON_TYPE, nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('PRIMARY', 'DUPLICATE')",
            name="link_role",
        ),
        sa.ForeignKeyConstraint(
            ["complaint_id"],
            ["complaints.complaint_id"],
            name="fk_consolidation_links_complaint_id_complaints",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["consolidation_groups.group_id"],
            name="fk_consolidation_links_group_id_consolidation_groups",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("link_id", name="pk_consolidation_links"),
        sa.UniqueConstraint(
            "complaint_id", name="uq_consolidation_links_complaint_id"
        ),
    )
    op.create_index(
        "ix_consolidation_links_group",
        "consolidation_links",
        ["group_id"],
    )

    op.create_table(
        "consolidation_reviews",
        sa.Column("review_id", sa.String(length=36), nullable=False),
        sa.Column("complaint_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column(
            "leading_candidate_id", sa.String(length=64), nullable=True
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reasons", JSON_TYPE, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="review_status",
        ),
        sa.ForeignKeyConstraint(
            ["complaint_id"],
            ["complaints.complaint_id"],
            name="fk_consolidation_reviews_complaint_id_complaints",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "review_id", name="pk_consolidation_reviews"
        ),
        sa.UniqueConstraint(
            "complaint_id", name="uq_consolidation_reviews_complaint_id"
        ),
    )
    op.create_index(
        "ix_consolidation_reviews_status",
        "consolidation_reviews",
        ["status"],
    )

    op.create_table(
        "consolidation_requests",
        sa.Column(
            "idempotency_key", sa.String(length=128), nullable=False
        ),
        sa.Column("complaint_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", JSON_TYPE, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["complaint_id"],
            ["complaints.complaint_id"],
            name="fk_consolidation_requests_complaint_id_complaints",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "idempotency_key", name="pk_consolidation_requests"
        ),
        sa.UniqueConstraint(
            "complaint_id", name="uq_consolidation_requests_complaint_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("consolidation_requests")
    op.drop_table("consolidation_reviews")
    op.drop_table("consolidation_links")
    op.drop_table("consolidation_groups")
    op.drop_table("complaints")
