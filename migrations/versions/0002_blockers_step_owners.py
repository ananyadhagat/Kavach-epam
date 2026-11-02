"""Task blockers, checklist step owners and completion times.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26

- tasks.status may be BLOCKED.
- checklist_steps gains assigned_worker_id (backfilled from the task's
  worker) and completed_at (backfilled from updated_at for COMPLETED
  steps).
- completion_submissions.status is renamed from SUBMITTED_FOR_VERIFICATION
  to COMPLETION_SUBMITTED.
- task_blockers keeps every blocker report and its resolution.

The upgrade keeps all existing data. The downgrade drops task_blockers and
fails if any task is still BLOCKED.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)

OLD_TASK_STATUSES = ("ASSIGNED", "ACCEPTED", "REJECTED", "IN_PROGRESS",
                     "PAUSED", "COMPLETION_SUBMITTED")
NEW_TASK_STATUSES = ("ASSIGNED", "ACCEPTED", "REJECTED", "IN_PROGRESS",
                     "PAUSED", "BLOCKED", "COMPLETION_SUBMITTED")


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    _replace_check("tasks", "ck_tasks_status_valid",
                   _in("status", NEW_TASK_STATUSES))

    # Checklist step owner: existing steps belong to the task's worker.
    op.add_column("checklist_steps",
                  sa.Column("assigned_worker_id", sa.String(100),
                            nullable=True))
    op.execute(
        "UPDATE checklist_steps AS s SET assigned_worker_id = "
        "t.assigned_worker_id FROM tasks AS t WHERE t.task_id = s.task_id"
    )
    op.alter_column("checklist_steps", "assigned_worker_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_checklist_steps_assigned_worker_id_workers"), "checklist_steps",
        "workers", ["assigned_worker_id"], ["worker_id"],
    )

    op.add_column("checklist_steps",
                  sa.Column("completed_at", TS, nullable=True))
    op.execute(
        "UPDATE checklist_steps SET completed_at = updated_at "
        "WHERE status = 'COMPLETED'"
    )
    op.create_check_constraint(
        op.f("ck_checklist_steps_completed_at_matches_status"), "checklist_steps",
        "(status = 'COMPLETED') = (completed_at IS NOT NULL)",
    )

    # Constraint first, so the renamed value is valid when written.
    op.drop_constraint(op.f("ck_completion_submissions_status_valid"),
                       "completion_submissions", type_="check")
    op.execute(
        "UPDATE completion_submissions SET status = 'COMPLETION_SUBMITTED' "
        "WHERE status = 'SUBMITTED_FOR_VERIFICATION'"
    )
    op.create_check_constraint(
        op.f("ck_completion_submissions_status_valid"), "completion_submissions",
        _in("status", ("COMPLETION_SUBMITTED",)),
    )

    op.create_table(
        "task_blockers",
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("step_id", sa.String(100), nullable=True),
        sa.Column("reason_code", sa.String(50), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("previous_status", sa.String(30), nullable=False),
        sa.Column("reported_at", TS, nullable=False),
        sa.Column("resolved_at", TS, nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("resolution_note", sa.String(1000), nullable=True),
        sa.CheckConstraint(_in("status", ("OPEN", "RESOLVED")),
                           name=op.f("ck_task_blockers_status_valid")),
        sa.CheckConstraint(
            _in("previous_status", ("ACCEPTED", "IN_PROGRESS", "PAUSED")),
            name=op.f("ck_task_blockers_previous_status_valid"),
        ),
        sa.CheckConstraint("reason_code ~ '^[A-Z][A-Z0-9_]*$'",
                           name=op.f("ck_task_blockers_reason_code_format")),
        sa.CheckConstraint("length(trim(description)) > 0",
                           name=op.f("ck_task_blockers_description_not_blank")),
        sa.CheckConstraint(
            "(status = 'RESOLVED') = "
            "(resolved_at IS NOT NULL AND resolved_by IS NOT NULL)",
            name=op.f("ck_task_blockers_resolution_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.task_id"],
            name=op.f("fk_task_blockers_task_id_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.worker_id"],
            name=op.f("fk_task_blockers_worker_id_workers"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "step_id"],
            ["checklist_steps.task_id", "checklist_steps.step_id"],
            name=op.f("fk_task_blockers_checklist_step"),
        ),
        sa.PrimaryKeyConstraint("blocker_id", name=op.f("pk_task_blockers")),
    )
    op.create_index("uq_task_blockers_one_open", "task_blockers",
                    ["task_id"], unique=True,
                    postgresql_where=sa.text("status = 'OPEN'"))
    op.create_index("ix_task_blockers_status", "task_blockers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_task_blockers_status", table_name="task_blockers")
    op.drop_index("uq_task_blockers_one_open", table_name="task_blockers")
    op.drop_table("task_blockers")

    op.drop_constraint(op.f("ck_completion_submissions_status_valid"),
                       "completion_submissions", type_="check")
    op.execute(
        "UPDATE completion_submissions "
        "SET status = 'SUBMITTED_FOR_VERIFICATION' "
        "WHERE status = 'COMPLETION_SUBMITTED'"
    )
    op.create_check_constraint(
        op.f("ck_completion_submissions_status_valid"), "completion_submissions",
        _in("status", ("SUBMITTED_FOR_VERIFICATION",)),
    )

    op.drop_constraint(op.f("ck_checklist_steps_completed_at_matches_status"),
                       "checklist_steps", type_="check")
    op.drop_column("checklist_steps", "completed_at")
    op.drop_constraint(op.f("fk_checklist_steps_assigned_worker_id_workers"),
                       "checklist_steps", type_="foreignkey")
    op.drop_column("checklist_steps", "assigned_worker_id")

    # Fails if a task is still BLOCKED; unblock it first.
    _replace_check("tasks", "ck_tasks_status_valid",
                   _in("status", OLD_TASK_STATUSES))
