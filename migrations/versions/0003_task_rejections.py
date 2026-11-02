"""Persist worker task acceptance and rejection decisions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_rejections",
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name=op.f("ck_task_rejections_reason_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.task_id"],
            name=op.f("fk_task_rejections_task_id_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.worker_id"],
            name=op.f("fk_task_rejections_worker_id_workers"),
        ),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_task_rejections")),
    )


def downgrade() -> None:
    op.drop_table("task_rejections")
