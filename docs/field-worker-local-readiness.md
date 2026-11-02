# KAVACH Field Worker — Local Frontend Readiness

**Audit date:** 2026-10-28

This document records the current Field Worker backend/API and readiness for
its own worker-facing frontend. It is based on source, schemas, README, test
definitions, existing integration documents, and the current worktree. No
tests were run and no database was accessed.

**Implementation update (2026-10-30):** The current code now supports
worker accept/reject decisions for owned `ASSIGNED` tasks, rejection audit
persistence through migration `0003`, and an interactive Leaflet map using
task coordinates and explicitly captured browser GPS. Dispatch ingestion
and Verification Agent handoff remain external integration gaps.

**Workflow change (2026-10-28):** Checklist was removed from the current
worker workflow. Its legacy routes, model fields, and database structures
remain for compatibility, but checklist state is not a prerequisite for
start, AFTER evidence, or completion.

## 1. Executive summary

- **SOURCE REVIEW (2026-10-28):** This repository contains a FastAPI backend
  and a React/Vite worker frontend under `frontend/`. Frontend source includes
  an assigned-task list and task details; Start, Pause, and Resume controls;
  BEFORE/AFTER evidence upload and history; browser GPS capture and location
  submission; blocker reporting and history; and completion submission.
  This source inventory is not runtime or end-to-end verification.
- **VERIFIED:** The existing worker APIs cover assigned-task listing/details,
  lifecycle actions, legacy checklist reads/updates, multipart evidence
  upload, location-event submission, task blocker reporting/history, and
  completion submission. Checklist is no longer required by worker lifecycle.
- **VERIFIED:** A browser frontend can call the current worker APIs in local
  development using the worker bearer token and the current CORS allow-list.
  Production use is unavailable: startup refuses production until shared
  authentication is integrated.
- **VERIFIED:** The backend stores location events submitted by the caller;
  it does not acquire a location from a device. The frontend requests browser
  geolocation after an explicit worker action and submits the location as a
  separate event. The frontend's camera-capable file-selection hint does not
  guarantee that an image came from a physical camera.
- **VERIFIED:** Image upload and task-scoped evidence metadata history are
  available to the primary task worker. There is no API to retrieve image
  bytes; history deliberately does not expose the internal storage key.
- **VERIFIED:** No assignment-ingestion endpoint or Verification Agent
  endpoint exists in this module. Those remain external dependencies and are
  not part of this local frontend scope.

## 2. Scope and worktree inspection

### Repository structure

**VERIFIED:** The backend is organized as a Python FastAPI application under
`app/`, with API routers, Pydantic schemas, services, repositories,
PostgreSQL persistence, migrations, and pytest tests. The React/Vite
frontend under `frontend/` contains task list/details, lifecycle, evidence,
GPS location, blocker, and completion-submission surfaces. This structure
inventory does not establish that the application has been runtime tested.
The README documents Swagger at `/docs` as the API exploration surface.

### Pre-existing uncommitted work

At the original audit start, `git status --short --untracked-files=all` showed
51 changed paths other than the tagged `.env` file. The `.env` file was not
opened or read. These changes were preserved.

- **Modified:** `.env.example`, `README.md`; Python package, API, config,
  database, repository, schema, service, validator, and test files.
- **Untracked:** blocker API/repository/schema/service; blocker, checklist,
  completion, and start validators; related tests; migration
  `0002_blockers_step_owners.py`; and the existing integration-contract and
  mentor-decision documents.
- The prior task also left lint-only edits in Python files. This audit did not
  revert or overwrite any of those changes.

The original audit changed only this readiness document. The 2026-10-28
workflow update changed the frontend, lifecycle validation, related tests,
and field-worker documentation listed in the current change set.

## 3. Verified local workflow

### Tasks and details

`GET /api/v1/worker/tasks` returns tasks whose primary
`assigned_worker_id` matches the authenticated worker. The list is ordered by
creation time and task ID; no pagination or status filter is defined.
`GET /api/v1/worker/tasks/{task_id}` returns the same task representation.
Other workers' tasks are hidden as `404`.

The task representation contains:

- `task_id`, `incident_id`, `assigned_worker_id`
- `title`, `description`, `priority`, `status`
- `location`: `latitude`, `longitude`, `address`
- The API still serializes the legacy `checklist` definition field; the
  current worker interface ignores it.
- `created_at`, `updated_at`
- `arrival_location_event_id`, `completion_location_event_id`,
  `completion_submission_id`

### Lifecycle

- `POST .../{task_id}/start` starts an `ACCEPTED` task only after stored
  BEFORE evidence and a captured arrival location exist; it also resumes a
  `PAUSED` task.
- `POST .../{task_id}/resume` resumes a `PAUSED` task. It does not repeat the
  first-start evidence/location prerequisite check.
- `POST .../{task_id}/pause` pauses an `IN_PROGRESS` task.
- Worker transitions are guarded by the state machine and return `409` for
  disallowed transitions. Blocked tasks cannot upload evidence or submit
  completion. Field Worker does not transition tasks to `VERIFIED` or
  `CLOSED`.
- These routes accept no JSON request body. Each returns `{"task": ..., "message": ...}`.

### Legacy checklist API and retained structures

The existing GET/PATCH checklist routes and their ownership/state checks
remain available for compatibility, but are not used by the current worker
workflow. They do not gate starting, AFTER evidence, or completion. Checklist
definitions/records and completion-step link tables remain in the database
and migrations; no data or schema was removed. Optional step-specific blocker
associations also remain legacy behavior.

### Evidence upload

`POST .../{task_id}/evidence` accepts multipart form data:

- `evidence_type`: `BEFORE` or `AFTER`
- `file`: uploaded image

On success it returns `{"evidence": ..., "duplicate": boolean, "message": ...}`.
The evidence object contains `evidence_id`, `task_id`, `worker_id`,
`evidence_type`, `storage_key`, `original_filename`, `mime_type`, `size_bytes`,
`sha256`, `status`, and `uploaded_at`.

The service validates JPEG, PNG, or WebP content, rejects empty/malformed
images and oversized uploads, and defaults to a 5 MiB limit. It reuses an
identical image for the same task, worker, and evidence type. BEFORE evidence
is accepted for `ACCEPTED`, `IN_PROGRESS`, or `PAUSED` tasks. AFTER evidence
is accepted only while `IN_PROGRESS`; checklist state is not a prerequisite.
`GET /worker/tasks/{task_id}/evidence` returns all stored
evidence metadata for the authorized task worker, ordered by upload time and
evidence ID; older records, including earlier AFTER photos, remain in the
history. Its response includes IDs, type, filename, MIME type, size, status,
and server `uploaded_at`, but omits the internal `storage_key`. The evidence
model has no device capture timestamp or associated location-event reference.
The API does not return image bytes.

### Location events

`POST .../{task_id}/arrival` and `POST
.../{task_id}/completion-location` accept a JSON `LocationEventCreate`:

- `event_type`: `ARRIVAL` or `COMPLETION` and must match the endpoint
- `capture_status`: `CAPTURED`, `UNAVAILABLE`, or `INACCURATE`
- optional `latitude`, `longitude`, `accuracy_meters`,
  `captured_at_device`

`CAPTURED` requires finite coordinates and accuracy. Latitude must be in
`-90..90`, longitude in `-180..180`, and accuracy greater than zero and at
most 100,000 metres. Non-captured states must not include coordinates. The
service downgrades a `CAPTURED` fix above configured
`MAX_GPS_ACCURACY_METERS` (default 100 metres) to `INACCURATE` and drops its
coordinates.

Success returns `{"location_event": ...}` with `location_event_id`,
`task_id`, `worker_id`, `event_type`, `capture_status`, `latitude`,
`longitude`, `accuracy_meters`, `captured_at_device`, and
`received_at_server`. Unavailable/inaccurate events can be stored, but only
CAPTURED events meet start/completion prerequisites. No exception policy
exists.

**Important distinction:** These are location-event records submitted as
separate API requests. The backend has no device-location acquisition code.
The evidence schema has no EXIF/GPS fields, and image validation does not
extract image-embedded GPS metadata. The uploaded image bytes and separate
location event are not joined by EXIF inspection.

### Blockers

- `POST .../{task_id}/blockers` accepts
  `{"reason_code": string, "description": string, "step_id": string | null}`.
  The code must match `^[A-Z][A-Z0-9_]*$` and be present in the centrally
  configured allow-list; description is trimmed/non-empty and at most 500
  characters; step ID is optional and 1–100 characters.
- Success returns `blocker`, updated `task`, and `message`. The blocker
  contains `blocker_id`, `task_id`, `worker_id`, `step_id`, `reason_code`,
  `description`, `status`, `previous_status`, `reported_at`, `resolved_at`,
  `resolved_by`, and `resolution_note`.
- `GET .../{task_id}/blockers` returns `task_id` and blocker history.
- `GET /api/v1/worker/blockers/reason-codes` requires the worker bearer token
  and returns `{"reason_codes": [{"code": "..."}]}` from the same configured
  allow-list used by blocker reporting. No display labels are configured, so
  the API does not invent them. Explicit empty/unavailable or invalid
  configuration returns `503`.
- Development examples remain non-approved defaults. In production, the
  endpoint returns codes only when a configured allow-list and explicit
  `BLOCKER_REASON_CODES_APPROVED=true` are present; otherwise it returns
  `503`. Production startup currently remains blocked by missing shared
  authentication. An unconfigured submitted code continues to return `422`.
  Do not hard-code a supposed approved list in the frontend.
- Reporting an optional `step_id` blocks that step and copies the description
  into its note. The task becomes `BLOCKED`; one open blocker per task is
  enforced. A worker cannot unblock it.

There are also development-only operator routes:

- `GET /api/v1/operator/blockers` returns `{"blockers": [...]}` for open
  blockers.
- `POST /api/v1/operator/tasks/{task_id}/unblock` accepts an optional body
  `{"resolution_note": string | null}`; a supplied note must be
  non-empty after trimming and at most 1,000 characters. Success returns
  `blocker`, `task`, and `message`.

These are not worker routes or a production Dispatch contract. Operator
authentication is demo-only; the worker-facing frontend should show blocked
state/history and direct the worker to the established operational process,
not expose an unblock control.

### Completion submission

`POST .../{task_id}/completion` requires the `Idempotency-Key` header and a
JSON body:

- `evidence_ids`: list of at least two unique strings
- optional `completion_location_event_id`
- optional `notes`, maximum 2,000 characters

Extra fields and duplicate evidence IDs are rejected. The server verifies
that the task is `IN_PROGRESS`, submitted evidence belongs to this task and
worker and includes BEFORE and AFTER, an arrival reference exists, and the
referenced completion location is captured and matches task, worker, and event
type. Checklist status and evidence freshness relative to checklist steps do
not gate completion.

Success returns `{"submission": ..., "message": ...}`. Submission fields are
`submission_id`, `task_id`, `worker_id`, `checklist_step_ids`, `evidence_ids`,
`completion_location_event_id`, `notes`, `submitted_at`, and `status`.
New submissions have an empty `checklist_step_ids` response field retained
for compatibility with historical submission records. Status is
`COMPLETION_SUBMITTED`; this is not a verification result.
Reusing the same key and identical request returns the existing submission;
using the same key with a different request returns `409`.

## 4. Complete Field Worker API inventory

All paths below are mounted under `/api/v1`. Unless called out as public,
worker routes require `Authorization: Bearer <worker-token>`; current
authentication maps the development token to a configured fixed worker ID.
Production startup is refused pending shared authentication.

| Method and path | Request | Success response | Access and important rules |
|---|---|---|---|
| `GET /health` | None | `status`, `service` | Public; no worker token. |
| `GET /worker/tasks` | None | `tasks`: array of task objects | Worker bearer; only tasks assigned to authenticated primary worker. |
| `GET /worker/tasks/{task_id}` | None | Task object | Worker bearer; other/missing task is `404`. |
| `POST /worker/tasks/{task_id}/start` | None | `task`, `message` | Worker bearer; ACCEPTED requires stored BEFORE and CAPTURED arrival; PAUSED resumes. |
| `POST /worker/tasks/{task_id}/resume` | None | `task`, `message` | Worker bearer; PAUSED only. |
| `POST /worker/tasks/{task_id}/pause` | None | `task`, `message` | Worker bearer; transition rules apply. |
| `GET /worker/tasks/{task_id}/checklist` | None | `task_id`, `steps` | Worker bearer; primary task owner only. |
| `PATCH /worker/tasks/{task_id}/checklist/{step_id}` | `status`, optional `note` | `task_id`, `step_id`, `status`, `note`, timestamps, `message` | Worker bearer; task must be IN_PROGRESS and step owner must match. |
| `GET /worker/tasks/{task_id}/evidence` | None | `task_id`, `evidence`: array of evidence-history items (`evidence_id`, `task_id`, `worker_id`, `evidence_type`, `original_filename`, `mime_type`, `size_bytes`, `status`, `uploaded_at`) | Worker bearer; primary task owner only; chronological metadata, no storage key or image bytes. |
| `POST /worker/tasks/{task_id}/evidence` | multipart `evidence_type`, `file` | `evidence`, `duplicate`, `message` | Worker bearer; JPEG/PNG/WebP; size and task-state gates. |
| `POST /worker/tasks/{task_id}/arrival` | `LocationEventCreate` | `location_event` | Worker bearer; event type must be ARRIVAL. |
| `POST /worker/tasks/{task_id}/completion-location` | `LocationEventCreate` | `location_event` | Worker bearer; event type must be COMPLETION. |
| `POST /worker/tasks/{task_id}/blockers` | `reason_code`, `description`, optional `step_id` | `blocker`, `task`, `message` | Worker bearer; configured reason code required; task must be blockable; one open blocker maximum. |
| `GET /worker/tasks/{task_id}/blockers` | None | `task_id`, `blockers` | Worker bearer; primary task owner only. |
| `GET /worker/blockers/reason-codes` | None | `reason_codes`: array of `{code}` | Worker bearer; returns the configured codes permitted by blocker-reporting policy; `503` if unavailable, invalid, or not production-approved. |
| `POST /worker/tasks/{task_id}/completion` | `evidence_ids`, optional location ID/notes, plus required `Idempotency-Key` header | `submission`, `message` | Worker bearer; IN_PROGRESS and evidence/location validations pass. |
| `GET /operator/blockers` | None | `blockers` | Separate demo operator bearer only; development only. |
| `POST /operator/tasks/{task_id}/unblock` | Optional `resolution_note` body | `blocker`, `task`, `message` | Separate demo operator bearer only; development only; resolves open blocker and restores prior task status. |

Business errors use `{"detail": ...}`. Important statuses include `401` for
missing/invalid demo credentials, `403` for a non-owner checklist step, `404`
for missing or non-owned tasks/steps, `409` for state conflicts,
`413` for oversized images, `422` for invalid payload/business prerequisites,
and `503` for unavailable database or blocker reason-code configuration.
Request validation details may be an array under `detail`.

No Field Worker assignment-ingestion, task-cancel/update, evidence image
download, location-history, verification, or production operator-auth route
is defined.

## 5. Frontend APIs usable now vs. blocked dependencies

### Usable for a local development frontend

- Task list and detail; current task status and location target.
- Start, resume, and pause actions. Start requires BEFORE evidence and arrival.
- Checklist endpoints remain for legacy compatibility only; checklist is not
  required for the current worker flow.
- BEFORE and AFTER uploads with immediate evidence ID and duplicate signal,
  plus stored evidence metadata history.
- Arrival and completion location-event submission, once a browser/device fix
  is obtained by the client.
- Blocked status and task blocker history; blocker reporting only when the
  local configured reason-code list accepts the submitted code. The
  authenticated reason-code discovery endpoint supplies the current allowed
  codes without official labels.
- Idempotent completion submission with existing evidence/location IDs.
- Public health endpoint.

The backend permits browser origins `http://localhost:3000` and
`http://127.0.0.1:3000`, methods GET/POST/PATCH, and headers Authorization,
Content-Type, and Idempotency-Key. A local web client on another origin would
need a separately reviewed CORS adjustment. No change is made here.

### Blocked or incomplete

- **Production UI authentication:** blocked until shared KAVACH auth is
  supplied; demo tokens and demo operator routes are not production
  contracts.
- **Initial task delivery and assignment changes:** no Field Worker ingress
  API; no accepted-assignment payload, duplicate-delivery, update, or
  cancellation contract exists in this module.
- **Evidence after page reload:** metadata is available through the history
  route; image bytes are not served by an API. A frontend cannot display
  previously uploaded image content from backend storage without a separately
  approved image-read design.
- **Blocker reason choice UX:** `GET /api/v1/worker/blockers/reason-codes`
  returns the active configured codes to an authenticated worker. The
  response has no display labels; development examples remain non-approved,
  and production requires explicit approval. The frontend must handle
  `503` when configuration is unavailable or unapproved.
- **Legacy checklist routes:** still enforce primary task ownership and step
  owner checks but are not used or required by the worker interface.
- **Completion verification/rework:** no Verification Agent API, rejection
  findings, or reassignment/resubmission contract.

## 6. Remaining integration limitations

The frontend source includes task list/details, lifecycle controls,
BEFORE/AFTER evidence upload/history, browser GPS capture and location
submission, blocker reporting/history, and completion submission. The
following are outstanding backend or external integration limitations, not
unimplemented frontend features:

| Priority | Task | Current evidence / boundary |
|---|---|---|
| P1 | Integrate shared production authentication and worker identity. | **VERIFIED limitation:** the current frontend uses the development-token flow; production authentication is not integrated and production startup is blocked pending shared authentication. |
| P1 | Integrate Dispatch assignment ingestion and updates. | **VERIFIED gap:** no assignment-ingestion endpoint or assignment-change contract exists in this module. |
| P1 | Provide a location-event history/read contract if completion location must be re-verified after reload. | **VERIFIED gap:** the task carries a completion-location reference, but no event-history read endpoint independently confirms capture status after reload. |
| P1 | Integrate Verification acknowledgement, approval/rejection, and rework. | **VERIFIED gap:** completion is recorded as `COMPLETION_SUBMITTED`; no Verification Agent integration is defined. |
| P2 | Decide whether the backend needs worker-scoped historical image retrieval. | **VERIFIED gap:** history returns metadata only; no route serves image bytes. The local selected-file preview is not persisted image retrieval. |
| P2 | Continue blocker reason-code policy integration as configuration/approval evolves. | **VERIFIED limitation:** the frontend loads codes without labels; unavailable or unapproved production configuration fails closed with `503`. |
| P2 | Define Dispatch blocker delivery/notification if required. | **VERIFIED gap:** blocker history/reporting exist, but no Dispatch event or polling contract is defined. |
| P3 | Review CORS only if frontend hosting origin differs from the two current localhost origins. | **VERIFIED:** exact local origins/methods/headers are set in `app/main.py`. |

### Camera and image GPS metadata requirements

- Use the existing multipart contract and accepted image types; do not assume
  the backend will convert HEIC or other unsupported formats.
- Keep BEFORE/AFTER evidence type explicit in the UI; completion still
  requires evidence IDs, but checklist step IDs are not part of the claim.
- Camera capture and file selection are frontend responsibilities. The
  backend only validates and stores uploaded image bytes and ordinary upload
  metadata.
- Browser/device geolocation is a separate frontend permission/capture flow.
  Send it to the arrival/completion endpoint as a structured location event.
- EXIF GPS embedded in a camera image is distinct from the separate location
  event. The backend neither extracts EXIF GPS nor uses it to satisfy the
  event prerequisites. The current API has no field linking an EXIF location
  to a location event.

## 7. Current frontend structure

**SOURCE REVIEW (updated 2026-10-28):** The React + Vite application source
includes task list/details, Start/Pause/Resume, BEFORE/AFTER evidence
upload/history, browser GPS capture and arrival/completion location
submission, blocker reporting/history, and completion submission. It uses a
shared API client and development-token handling. Checklist UI and requests
were removed. Vite is configured for `127.0.0.1:3000` with strict port
behavior, matching the backend CORS allow-list. This source inventory is not
runtime or end-to-end verification and does not establish production hosting
or authentication. Do not store production credentials in frontend source,
Vite environment variables, or bundle configuration.

## 8. External dependencies deliberately out of scope

- **Dispatch:** accepted-assignment ingestion, canonical identifiers, updates,
  cancellation, duplicate delivery, blocker discovery/notification, and
  operational unblock authority.
- **Verification Agent:** completion discovery/acknowledgement, findings,
  rejection/rework, reassignment, and resubmission process.
- **Shared KAVACH authentication:** production worker identity, operator
  roles/permissions, and token validation. The current app refuses production
  startup without this.
- **Legacy step ownership:** no cross-worker task access contract exists for
  the retained checklist APIs.
- **Product/operations policy:** approved blocker reason codes and any GPS
  exception policy. No unavailable/inaccurate GPS exception is implemented
  or assumed.

None of these dependencies should be invented or implemented as part of the
local frontend preparation.

## 9. Audit boundaries

- **VERIFIED:** This audit inspected source, schemas, routes, services,
  validators, README, existing integration documents, test fixture and API
  contract definitions, and the pre-existing worktree status.
- **NOT RUN:** Tests, frontend build, migrations, and database checks.
- No database was contacted. The workflow update changed source, related
  tests, and documentation but did not change database schemas or migrations.
