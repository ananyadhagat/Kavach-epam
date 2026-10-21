"""Initial KAVACH schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-18

Creates all application tables on an empty database. The downgrade drops
them and all their data; never run it against a database whose data you
need to keep.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true",
                  nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("length(worker_id) > 0",
                           name=op.f("ck_workers_worker_id_not_empty")),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_workers")),
    )

    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("incident_id", sa.String(100), nullable=False),
        sa.Column("assigned_worker_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("arrival_location_event_id", sa.Uuid(), nullable=True),
        sa.Column("completion_location_event_id", sa.Uuid(), nullable=True),
        sa.Column("completion_submission_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            _in("status", ("ASSIGNED", "ACCEPTED", "REJECTED", "IN_PROGRESS",
                           "PAUSED", "COMPLETION_SUBMITTED")),
            name=op.f("ck_tasks_status_valid"),
        ),
        sa.CheckConstraint(_in("priority", ("LOW", "MEDIUM", "HIGH")),
                           name=op.f("ck_tasks_priority_valid")),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90",
                           name=op.f("ck_tasks_latitude_range")),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180",
                           name=op.f("ck_tasks_longitude_range")),
        sa.CheckConstraint("length(task_id) > 0",
                           name=op.f("ck_tasks_task_id_not_empty")),
        sa.CheckConstraint(
            "(status = 'COMPLETION_SUBMITTED') = "
            "(completion_submission_id IS NOT NULL)",
            name=op.f("ck_tasks_submission_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_worker_id"], ["workers.worker_id"],
            name=op.f("fk_tasks_assigned_worker_id_workers"),
        ),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_tasks")),
    )
    op.create_index("ix_tasks_worker_status", "tasks",
                    ["assigned_worker_id", "status"])

    op.create_table(
        "checklist_steps",
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("step_id", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(_in("status", ("PENDING", "COMPLETED", "BLOCKED")),
                           name=op.f("ck_checklist_steps_status_valid")),
        sa.CheckConstraint("length(step_id) > 0",
                           name=op.f("ck_checklist_steps_step_id_not_empty")),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.task_id"], ondelete="CASCADE",
            name=op.f("fk_checklist_steps_task_id_tasks"),
        ),
        sa.PrimaryKeyConstraint("task_id", "step_id",
                                name=op.f("pk_checklist_steps")),
        sa.UniqueConstraint(
            "task_id", "position",
            name=op.f("uq_checklist_steps_task_id_position"),
        ),
    )

    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("evidence_type", sa.String(10), nullable=False),
        sa.Column("storage_key", sa.String(100), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("uploaded_at", TS, nullable=False),
        sa.CheckConstraint(_in("evidence_type", ("BEFORE", "AFTER")),
                           name=op.f("ck_evidence_type_valid")),
        sa.CheckConstraint(
            _in("mime_type", ("image/jpeg", "image/png", "image/webp")),
            name=op.f("ck_evidence_mime_type_valid"),
        ),
        sa.CheckConstraint(_in("status", ("STORED",)),
                           name=op.f("ck_evidence_status_valid")),
        sa.CheckConstraint("size_bytes > 0",
                           name=op.f("ck_evidence_size_positive")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'",
                           name=op.f("ck_evidence_sha256_hex")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"],
                                name=op.f("fk_evidence_task_id_tasks")),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.worker_id"],
                                name=op.f("fk_evidence_worker_id_workers")),
        sa.PrimaryKeyConstraint("evidence_id", name=op.f("pk_evidence")),
        sa.UniqueConstraint("storage_key",
                            name=op.f("uq_evidence_storage_key")),
        sa.UniqueConstraint("task_id", "worker_id", "sha256",
                            "evidence_type",
                            name=op.f("uq_evidence_content")),
        sa.UniqueConstraint("task_id", "evidence_id",
                            name=op.f("uq_evidence_task_id_evidence_id")),
    )
    op.create_index("ix_evidence_task", "evidence", ["task_id"])

    op.create_table(
        "location_events",
        sa.Column("location_event_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("capture_status", sa.String(20), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("accuracy_meters", sa.Double(), nullable=True),
        sa.Column("captured_at_device", TS, nullable=True),
        sa.Column("received_at_server", TS, nullable=False),
        sa.CheckConstraint(_in("event_type", ("ARRIVAL", "COMPLETION")),
                           name=op.f("ck_location_events_event_type_valid")),
        sa.CheckConstraint(
            _in("capture_status", ("CAPTURED", "UNAVAILABLE", "INACCURATE")),
            name=op.f("ck_location_events_capture_status_valid"),
        ),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90",
                           name=op.f("ck_location_events_latitude_range")),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180",
                           name=op.f("ck_location_events_longitude_range")),
        sa.CheckConstraint(
            "accuracy_meters > 0 AND accuracy_meters <= 100000",
            name=op.f("ck_location_events_accuracy_range"),
        ),
        sa.CheckConstraint(
            "(capture_status = 'CAPTURED') = "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
            name=op.f("ck_location_events_coordinates_match_status"),
        ),
        sa.CheckConstraint(
            "capture_status <> 'CAPTURED' OR accuracy_meters IS NOT NULL",
            name=op.f("ck_location_events_captured_has_accuracy"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.task_id"],
            name=op.f("fk_location_events_task_id_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.worker_id"],
            name=op.f("fk_location_events_worker_id_workers"),
        ),
        sa.PrimaryKeyConstraint("location_event_id",
                                name=op.f("pk_location_events")),
        sa.UniqueConstraint(
            "task_id", "location_event_id",
            name=op.f("uq_location_events_task_id_location_event_id"),
        ),
    )
    op.create_index("ix_location_events_task_type", "location_events",
                    ["task_id", "event_type"])

    op.create_table(
        "completion_submissions",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("completion_location_event_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("submitted_at", TS, nullable=False),
        sa.CheckConstraint(
            _in("status", ("SUBMITTED_FOR_VERIFICATION",)),
            name=op.f("ck_completion_submissions_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.task_id"],
            name=op.f("fk_completion_submissions_task_id_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.worker_id"],
            name=op.f("fk_completion_submissions_worker_id_workers"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "completion_location_event_id"],
            ["location_events.task_id", "location_events.location_event_id"],
            name=op.f("fk_completion_submissions_location_event"),
        ),
        sa.PrimaryKeyConstraint("submission_id",
                                name=op.f("pk_completion_submissions")),
        sa.UniqueConstraint("task_id",
                            name=op.f("uq_completion_submissions_task_id")),
        sa.UniqueConstraint(
            "task_id", "submission_id",
            name=op.f("uq_completion_submissions_task_id_submission_id"),
        ),
    )

    op.create_table(
        "completion_submission_evidence",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "submission_id"],
            ["completion_submissions.task_id",
             "completion_submissions.submission_id"],
            ondelete="CASCADE",
            name=op.f("fk_completion_evidence_submission"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "evidence_id"],
            ["evidence.task_id", "evidence.evidence_id"],
            name=op.f("fk_completion_evidence_evidence"),
        ),
        sa.PrimaryKeyConstraint(
            "submission_id", "evidence_id",
            name=op.f("pk_completion_submission_evidence"),
        ),
        sa.UniqueConstraint(
            "submission_id", "position",
            name=op.f("uq_completion_submission_evidence_submission_id_position"),
        ),
    )

    op.create_table(
        "completion_submission_steps",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.String(100), nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "submission_id"],
            ["completion_submissions.task_id",
             "completion_submissions.submission_id"],
            ondelete="CASCADE",
            name=op.f("fk_completion_steps_submission"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "step_id"],
            ["checklist_steps.task_id", "checklist_steps.step_id"],
            name=op.f("fk_completion_steps_checklist_step"),
        ),
        sa.PrimaryKeyConstraint(
            "submission_id", "step_id",
            name=op.f("pk_completion_submission_steps"),
        ),
        sa.UniqueConstraint(
            "submission_id", "position",
            name=op.f("uq_completion_submission_steps_submission_id_position"),
        ),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0",
                           name=op.f("ck_idempotency_records_key_not_blank")),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_idempotency_records_request_hash_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.task_id"],
            name=op.f("fk_idempotency_records_task_id_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["workers.worker_id"],
            name=op.f("fk_idempotency_records_worker_id_workers"),
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["completion_submissions.submission_id"],
            name=op.f(
                "fk_idempotency_records_submission_id_completion_submissions"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "task_id", "worker_id", "idempotency_key",
            name=op.f("pk_idempotency_records"),
        ),
    )

    # tasks <-> location_events / completion_submissions reference each
    # other, so these keys are added once both tables exist.
    op.create_foreign_key(
        "fk_tasks_arrival_location_event", "tasks", "location_events",
        ["task_id", "arrival_location_event_id"],
        ["task_id", "location_event_id"],
    )
    op.create_foreign_key(
        "fk_tasks_completion_location_event", "tasks", "location_events",
        ["task_id", "completion_location_event_id"],
        ["task_id", "location_event_id"],
    )
    op.create_foreign_key(
        "fk_tasks_completion_submission", "tasks", "completion_submissions",
        ["task_id", "completion_submission_id"],
        ["task_id", "submission_id"],
    )


def downgrade() -> None:
    # Destructive: removes every KAVACH table and its data.
    op.drop_constraint("fk_tasks_completion_submission", "tasks",
                       type_="foreignkey")
    op.drop_constraint("fk_tasks_completion_location_event", "tasks",
                       type_="foreignkey")
    op.drop_constraint("fk_tasks_arrival_location_event", "tasks",
                       type_="foreignkey")

    op.drop_table("idempotency_records")
    op.drop_table("completion_submission_steps")
    op.drop_table("completion_submission_evidence")
    op.drop_table("completion_submissions")
    op.drop_index("ix_location_events_task_type",
                  table_name="location_events")
    op.drop_table("location_events")
    op.drop_index("ix_evidence_task", table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("checklist_steps")
    op.drop_index("ix_tasks_worker_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("workers")
