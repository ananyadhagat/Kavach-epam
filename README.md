# KAVACH Field Worker Execution Agent

A modular FastAPI backend for field-worker task execution,
GPS event capture, image evidence uploads, checklist updates,
and completion submission.

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

The demo worker ID is worker-001. This token is for local development
only; demo authentication is refused when `APP_ENV=production`.

In Swagger UI, click **Authorize** (top right) and paste only the token
value, without the `Bearer ` prefix.

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
GET    /api/v1/worker/tasks/{task_id}/checklist
PATCH  /api/v1/worker/tasks/{task_id}/checklist/{step_id}
POST   /api/v1/worker/tasks/{task_id}/completion

## Business rules

Task states: ASSIGNED -> ACCEPTED | REJECTED; ACCEPTED -> IN_PROGRESS;
IN_PROGRESS <-> PAUSED; IN_PROGRESS -> COMPLETION_SUBMITTED.
Invalid transitions return 409. Other workers' tasks return 404.

- Checklist updates require IN_PROGRESS.
- Evidence (JPEG/PNG/WebP, max 5 MB, content checked by Pillow) can be
  uploaded while ACCEPTED, IN_PROGRESS or PAUSED. Oversized files return
  413; invalid or unsupported files return 422. Identical re-uploads of
  the same type reuse the existing record.
- Coordinates must be finite numbers within latitude -90..90 and
  longitude -180..180; accuracy must be finite and positive. NaN and
  Infinity return 422. The database enforces the same ranges.
- Arrival location: ACCEPTED, IN_PROGRESS or PAUSED. Completion location:
  IN_PROGRESS or PAUSED. Repeat captures are kept; the task references
  the latest one. Fixes worse than `MAX_GPS_ACCURACY_METERS` are stored
  as INACCURATE without coordinates. These are technical checks only:
  GPS data is a worker-device report, not proof of identity or presence.
- Completion requires IN_PROGRESS, all required checklist steps
  COMPLETED and referenced, at least one BEFORE and one AFTER image of
  this task, and an `Idempotency-Key` header. Replaying the same key with
  the same body returns the original submission (also after a restart);
  the same key with a different body returns 409. Failed attempts do not
  consume the key and leave no partial records.

## Important limitations

Before production deployment, configure real worker authentication,
private object storage for images, backups, audit logging, and
deployment security.

Completion submission records a worker claim. Nothing in this service
verifies photos or locations; the Verification Agent is responsible for
independently assessing the reported work.
