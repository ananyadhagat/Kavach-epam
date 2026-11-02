# KAVACH Field Worker Execution Task

A modular FastAPI backend for field-worker task execution,
GPS event capture, image evidence uploads, blocker reporting,
and completion submission. Checklist routes and data remain as
legacy compatibility features; checklist steps are not part of the current
worker lifecycle.

## Technology stack

- Python, FastAPI, Pydantic
- PostgreSQL (the only storage backend for application data)
- SQLAlchemy 2.0 (async) with asyncpg, Alembic migrations
- Pillow (image validation); image files stored on local disk
- Pytest

## Database setup (Windows, one time)

KAVACH requires PostgreSQL. The application refuses to start without
it; there is no in-memory or SQLite fallback.

1. **Install PostgreSQL 17.** Download the Windows installer from
   <https://www.postgresql.org/download/windows/> ("Download the
   installer", Windows x86-64) and run it:
   - Components: *PostgreSQL Server* and *Command Line Tools* are
     required; *pgAdmin 4* is optional; *Stack Builder* is not needed.
   - Set a password for the `postgres` superuser and keep it safe.
   - Port: `5432`. Locale: default.

   Alternative: `winget install --id PostgreSQL.PostgreSQL.17`
   (confirm the ID first with `winget search PostgreSQL`).

2. **Check the service is running** (PowerShell):

       Get-Service postgresql*

   Status should be `Running`. If not: `Start-Service postgresql-x64-17`.

3. **Create the application role and databases.** Open psql as the
   superuser (adjust the version folder if needed):

       & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -h localhost

   Then run, choosing your own password:

       CREATE ROLE kavach_app WITH LOGIN PASSWORD 'choose-a-strong-password';
       CREATE DATABASE kavach OWNER kavach_app;
       CREATE DATABASE kavach_test OWNER kavach_app;
       \q

   `kavach` holds your data. `kavach_test` is used only by the test
   suite, which empties it before every test.

4. **Configure the project.**

       Copy-Item .env.example .env

   Edit `.env`: put the `kavach_app` password into `DATABASE_URL` and
   `TEST_DATABASE_URL`, and choose a `DEMO_WORKER_TOKEN`. Percent-encode
   special characters in the password (`@` -> `%40`, `:` -> `%3A`,
   `/` -> `%2F`). Never commit `.env`.

5. **Install dependencies and create the schema.**

       py -m venv .venv
       .\.venv\Scripts\Activate.ps1
       pip install -r requirements.txt
       alembic upgrade head

6. **Load the demo task** (or set `SEED_DEMO_DATA=true` in `.env` to do
   this automatically at startup). Both only insert what is missing:

       python -m app.db.seed

### Troubleshooting setup

- **`permission denied for schema public`** during `alembic upgrade head`
  or tests: the databases are not owned by `kavach_app` (PostgreSQL 15+
  only lets the owner create tables in `public`). As `postgres`, run:

      ALTER DATABASE kavach OWNER TO kavach_app;
      ALTER DATABASE kavach_test OWNER TO kavach_app;

- **`DATABASE_URL host is malformed`**: the password contains an
  unencoded special character, or the `<placeholder>` brackets from
  `.env.example` were left in. Remove the brackets and percent-encode
  the password (`@` -> `%40`).

## Run the API

    uvicorn app.main:app --reload

- Swagger UI: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

Startup fails with a clear message if PostgreSQL is not configured,
not reachable, or the schema is not migrated (run `alembic upgrade head`).
If the database becomes unavailable while running, API requests return
HTTP 503.

## Demo authentication

Use the token from `DEMO_WORKER_TOKEN` (default `dev-worker-token`):

    Authorization: Bearer <DEMO_WORKER_TOKEN>

The demo worker ID is worker-001. Dispatch/Supervisor blocker routes
(`/api/v1/operator/...`) use a separate token, `DEMO_OPERATOR_TOKEN`
(default `dev-operator-token`), which must differ from the worker token.
Neither token works on the other's routes.

Both tokens are for local development only. Demo authentication is
refused when `APP_ENV=production`, and the application refuses to start
in production because the shared KAVACH authentication integration does
not exist yet.

In Swagger UI, click **Authorize** (top right) and paste only the token
value, without the `Bearer ` prefix.

## Resetting the local TASK-001 demo execution

The optional `scripts/reset_demo_task.py` utility inspects TASK-001 by
default; it does not change task records or files unless `--execute` is
provided. It only permits the existing PostgreSQL database named `kavach`.
The utility preserves TASK-001, its worker assignment and task details, and
checklist definitions while clearing that task's execution data.

Dry-run:

    .\.venv\Scripts\python.exe scripts\reset_demo_task.py

Execution is disabled by default. For an explicitly authorized local demo
environment only, set these values in the current PowerShell process (not
in a shared or production configuration), run the command, and type
`RESET TASK-001` when prompted:

    $env:APP_ENV = "development"
    $env:KAVACH_DEMO_RESET_ENABLED = "true"
    $env:KAVACH_DEMO_RESET_LOCAL_ONLY = "true"
    .\.venv\Scripts\python.exe scripts\reset_demo_task.py --execute

The second opt-in flag makes the utility remain disabled in integrated
environments unless a separate local demo environment is deliberately
authorized. The utility checks record ownership, task references, foreign-key
relationships and evidence file hashes; unexpected state causes refusal.
Image files are removed only after the database transaction commits. Do not
run the execute command against live, shared or production data.

## Running tests

Requires `TEST_DATABASE_URL` (in `.env` or the environment) pointing to
a PostgreSQL database whose name ends in `_test`:

    pytest -q
    pytest -q --cov=app --cov-report=term-missing

The suite applies migrations to the test database, then empties its
tables and reseeds the demo task before each database-backed test. It
refuses to run against a database whose name does not end in `_test`
or that matches `DATABASE_URL`. Without `TEST_DATABASE_URL`,
database-backed tests **fail** (they are not skipped). Uploads use
temporary directories; `private_uploads/` is never touched.

## Migrations

    alembic upgrade head         # apply
    alembic current              # show the applied revision
    alembic upgrade head --sql   # print the SQL without a database

`alembic downgrade` drops tables and **deletes all data**. Do not run
it against a database whose data you need.

Revision `0002` adds the BLOCKED task status, checklist step owners
(existing steps are assigned to their task's worker), step completion
times, the `task_blockers` table, and renames the stored submission
status to `COMPLETION_SUBMITTED`. It keeps all existing data while updating
the specified status values and adding/backfilling columns.

Revision `0003` adds a `task_rejections` audit table. It records the
assigned worker's reason and timestamp when a worker rejects an ASSIGNED
task. Workers can now accept or reject only their own ASSIGNED tasks;
acceptance persists as the task's ACCEPTED status.

## Evidence files and orphan cleanup

Image files are stored in `IMAGE_STORAGE_DIR` (default
`private_uploads/`); their metadata is stored in PostgreSQL. A file is
written (atomically) before its record is committed, and deleted if the
transaction fails, so a record never points at a missing file. If the
server crashes between those two steps, an orphan file can remain. To
list orphans older than 60 minutes (nothing is deleted):

    python -m app.db.check_orphans

To delete them: `python -m app.db.check_orphans --delete`.

## Main endpoints

Worker (worker token):

    GET    /api/v1/worker/tasks
    GET    /api/v1/worker/tasks/{task_id}
    POST   /api/v1/worker/tasks/{task_id}/accept
    POST   /api/v1/worker/tasks/{task_id}/reject
    POST   /api/v1/worker/tasks/{task_id}/arrival
    POST   /api/v1/worker/tasks/{task_id}/evidence
    POST   /api/v1/worker/tasks/{task_id}/start      (start or resume)
    POST   /api/v1/worker/tasks/{task_id}/resume     (PAUSED only)
    POST   /api/v1/worker/tasks/{task_id}/pause
    POST   /api/v1/worker/tasks/{task_id}/completion-location
    GET    /api/v1/worker/tasks/{task_id}/checklist       (legacy)
    PATCH  /api/v1/worker/tasks/{task_id}/checklist/{step_id} (legacy)
    POST   /api/v1/worker/tasks/{task_id}/blockers
    GET    /api/v1/worker/tasks/{task_id}/blockers   (history)
    POST   /api/v1/worker/tasks/{task_id}/completion

Dispatch/Supervisor (operator token):

    GET    /api/v1/operator/blockers                 (open blockers)
    POST   /api/v1/operator/tasks/{task_id}/unblock

## Business rules

Task states: ASSIGNED -> ACCEPTED | REJECTED (assigned worker only);
ACCEPTED -> IN_PROGRESS; IN_PROGRESS <-> PAUSED;
ACCEPTED | IN_PROGRESS | PAUSED -> BLOCKED (worker reports a blocker);
BLOCKED -> the previous status (Dispatch/Supervisor only);
IN_PROGRESS -> COMPLETION_SUBMITTED. Nothing here marks a task VERIFIED
or CLOSED; verification is downstream. Rejection requires a reason of
1–500 characters and stores the assigned worker, task, reason and timestamp.
Accepted or rejected decisions cannot be changed through worker routes.
Invalid transitions return 409. Other workers' tasks return 404.

- Starting an ACCEPTED task requires at least one BEFORE image of this
  task stored by the server and a CAPTURED arrival location (an
  UNAVAILABLE or INACCURATE fix does not count); otherwise start returns
  422. Resuming a PAUSED task does not repeat this check.
- Checklist routes and step-owner restrictions are retained for legacy
  compatibility only. Checklist definitions and step status do not gate
  starting work, AFTER uploads, or completion.
- Blockers: a worker reports a blocker with a reason code and a
  description (max 500 characters), optionally naming a legacy checklist
  step, which is then set BLOCKED with the description as its note. The task
  becomes BLOCKED and cannot be worked on or completed. Only one blocker
  can be open per task; every report and its resolution are kept. Dispatch
  or a Supervisor lists open blockers and unblocks the task, which returns
  to the status it had when it was blocked. Reason codes must be listed
  in `BLOCKER_REASON_CODES`. Development defaults to the explicitly
  non-approved `DEV_ACCESS`, `DEV_EQUIPMENT`, and `OTHER` examples. Every
  report requires a non-empty description, including `OTHER`. Production blocker
  reporting remains disabled unless an approved list is configured and
  `BLOCKER_REASON_CODES_APPROVED=true`; missing configuration returns 503 and
  an unlisted code returns 422. The development examples are not an approved
  KAVACH vocabulary.
- Evidence must be JPEG/PNG/WebP, max 5 MB, content checked by Pillow.
  Oversized files return 413; invalid or unsupported files return 422.
  Identical re-uploads of the same type reuse the existing record, but
  only if the upload rules below still allow the upload.
- BEFORE images can be uploaded while ACCEPTED, IN_PROGRESS or PAUSED.
- AFTER images can be uploaded only while IN_PROGRESS (otherwise 409).
  Checklist state is not a prerequisite. Earlier AFTER images are never
  replaced or deleted.
- Coordinates must be finite numbers within latitude -90..90 and
  longitude -180..180; accuracy must be finite and positive. NaN and
  Infinity return 422. The database enforces the same ranges.
- Arrival location: ACCEPTED, IN_PROGRESS or PAUSED. Completion location:
  IN_PROGRESS or PAUSED. Repeat captures are kept; the task references
  the latest one. Fixes worse than `MAX_GPS_ACCURACY_METERS` are stored
  as INACCURATE without coordinates. These are technical checks only:
  GPS data is a worker-device report, not proof of identity or presence.
- Completion requires IN_PROGRESS, at least one BEFORE and one AFTER image
  of this task, a recorded arrival, a CAPTURED completion location, and an
  `Idempotency-Key` header. Checklist status, step references, and AFTER
  evidence freshness relative to checklist completion are not requirements.
  New submissions return an empty legacy `checklist_step_ids` field for
  compatibility with historical persisted records.
  The submission and the task both end as `COMPLETION_SUBMITTED`.
  Replaying the same key with the same body returns the original
  submission (also after a restart); the same key with a different body
  returns 409. Failed attempts do not consume the key and leave no
  partial records.

## Important limitations

Before production deployment, configure real worker authentication,
private object storage for images, backups, audit logging, and
deployment security.

Completion submission records a worker claim. Nothing in this service
verifies photos or locations; the Verification Agent is responsible for
independently assessing the reported work.
