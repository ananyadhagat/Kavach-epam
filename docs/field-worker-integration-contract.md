# KAVACH Field Worker Integration Contract

This is an audit of the repository contents at the time of writing, including
the current worktree. It records existing behavior separately from proposed
integration work. It is not an approved Dispatch, authentication, GPS,
Verification Agent, or database contract.

Labels used below:

- **VERIFIED** — directly supported by repository code or documentation.
- **UNVERIFIED** — not established from the repository, or not checked because
  doing so would require database access or executing tests.
- **PROPOSED** — recommendation only; requires team approval.

The original audit did not contact a database or run tests or migrations.
The workflow update below changed runtime validation and related tests without
changing database schemas or migrations; no database was accessed.

**UI and integration update (2026-10-30):** The current task details UI uses
the task's backend-provided `location.address`, latitude and longitude rather
than hardcoded coordinates or a site name. The backend schema has no separate
location-name field, and Dispatch ingestion is not implemented. Dispatch's
future approved integration must populate the existing location contract; a
separate name requires an approved API/schema change. The UI computes distance
for information only; there is no configured proximity threshold exposed by
the API. The backend alone assesses its configured GPS accuracy threshold.
Browser GPS remains worker-device data, not proof of identity or presence.
Completion records already persist task/worker IDs, BEFORE/AFTER evidence
references, arrival and completion location references, submission time,
notes, and status; blocker history is available through the existing worker
blocker API. These records are a possible future Verification Agent input,
but no verifier request, integration, or status transition is implemented.

**Workflow update (2026-10-28):** Checklist steps are no longer part of the
Field Worker execution flow. Legacy checklist routes, task fields, and
database structures remain for compatibility, but do not gate start, AFTER
evidence upload, or completion. New completion claims omit checklist step
references; new persisted submissions retain an empty legacy
`checklist_step_ids` response field.

## 1. Executive summary

- **VERIFIED** — A worker may accept or reject an owned `ASSIGNED` task using
  the Field Worker API. The repository has no Dispatch implementation or
  separate team contract that defines how Dispatch supplies or updates tasks
  or synchronizes these decisions.
- **VERIFIED** — The persistence layer has an insertion helper for tasks, but
  no Dispatch HTTP ingress route, task upsert, or assignment-update operation.
  A repeated `task_id` is rejected by the helper rather than treated as an
  idempotent delivery.
- **VERIFIED** — Worker and operator authentication are demo bearer-token
  dependencies. Production startup is refused until shared KAVACH
  authentication exists. Worker-facing task access is scoped to the task's
  `assigned_worker_id`; a different worker assigned to a checklist step cannot
  get past that task-level check.
- **VERIFIED** — The blocker API exposes a development operator listing route
  and task-level unblock route. Development has explicitly non-approved
  example reason codes; production blocker reporting requires a configured
  list and an explicit approval setting. No finalized list is present.
- **VERIFIED** — Completion is a worker claim with status
  `COMPLETION_SUBMITTED`, not a verification result. No Verification Agent
  endpoint, rejection status, or rework transition is implemented.
- **UNVERIFIED** — The report's live database revision claims (`kavach_test`
  at `0002`, `kavach` at `0001`) cannot be verified from static files. No
  database connection was made.
- **UNVERIFIED** — The reported “656 passing tests” was not verified. Tests
  were intentionally not run: their session fixture applies migrations and
  truncates the configured test database.

## 2. Verified current implementation

### Task and worker records

- **VERIFIED** — `WorkerTask` uses string `task_id` and
  `assigned_worker_id` values constrained to 1–100 characters. It also
  contains `incident_id`, `title`, `description`, `priority`, `status`,
  `location` (`latitude`, `longitude`, `address`), optional checklist
  definitions, timestamps, and optional arrival, completion-location, and
  completion-submission identifiers. `TaskLocation` restricts coordinates to
  geographic ranges and requires a non-empty address.
- **VERIFIED** — Checklist definitions contain `step_id`, `title`, `required`
  (default true), and optional `assigned_worker_id`. Omitted step owners are
  assigned to the task's primary worker when the repository inserts a task.
- **VERIFIED** — `WorkerRow` stores `worker_id`, `display_name`, `is_active`,
  and `created_at`. The database has foreign keys from tasks to workers and
  from checklist-step owners to workers. The demo authentication dependency
  returns the configured fixed demo ID; it does not resolve a token subject to
  a worker record or check `is_active`.

### Task statuses and transitions

- **VERIFIED** — The current application/model status set is `ASSIGNED`,
  `ACCEPTED`, `REJECTED`, `IN_PROGRESS`, `PAUSED`, `BLOCKED`, and
  `COMPLETION_SUBMITTED`. An assigned worker may transition an owned
  `ASSIGNED` task to `ACCEPTED` or `REJECTED`. The demo seed creates
  `TASK-001` as `ACCEPTED`.
- **VERIFIED** — Worker transitions are `ACCEPTED` to `IN_PROGRESS`;
  `IN_PROGRESS` to/from `PAUSED`; execution states `ACCEPTED`,
  `IN_PROGRESS`, or `PAUSED` to `BLOCKED`; and `IN_PROGRESS` to
  `COMPLETION_SUBMITTED`. An operator unblock restores the recorded previous
  state. There is no `VERIFIED` or `CLOSED` status in the current
  Field Worker state machine.
- **VERIFIED** — A task is fetched/listed for a worker only when its
  `assigned_worker_id` matches the authenticated worker ID. Other workers'
  task requests return `404`.

### Authentication

- **VERIFIED** — Worker and operator dependencies use HTTP Bearer headers and
  separate configured demo tokens/IDs. The demo worker defaults are
  `worker-001` and a development token; the operator defaults are
  `operator-demo` and a separate development token. The code compares tokens
  with `secrets.compare_digest`.
- **VERIFIED** — Both dependencies reject demo authentication in production.
  The application lifespan raises `AuthenticationConfigurationError` and
  refuses production startup before opening a database connection.
- **VERIFIED** — There is no shared KAVACH identity provider, token
  validation configuration, canonical worker-subject mapping, or production
  operator authorization contract in the inspected repository.
- **VERIFIED** — The concrete worker integration points are
  `get_worker_id()` in `app/api/worker_task_routes.py` (currently returns the
  demo ID), `TaskRepository.get_for_worker()` in
  `app/repositories/task_repository.py` (compares the supplied ID to
  `tasks.assigned_worker_id`), and `WorkerRow.worker_id` /
  `TaskRow.assigned_worker_id` in `app/db/models.py`. A future approved auth
  integration must provide the canonical authenticated worker ID to this
  existing ownership check and ensure Dispatch's assigned worker uses the
  same canonical identifier. The operator-side integration point is
  `get_operator_id()` in `app/api/blocker_routes.py`; it also currently
  returns only a configured demo ID.

## 3. Existing API contracts, using actual repository definitions

The routes are mounted under `/api/v1`. The README lists the routes, and the
route definitions and schemas establish the request/response details below.
No separate Dispatch or Verification Agent API contract was found.

### Assignment ingestion boundary

- **VERIFIED — local schema, not a Dispatch payload** — There is no
  assignment-ingestion route or dedicated ingestion schema. The local
  repository insertion helper accepts `WorkerTask`: required model fields
  include `task_id`, `incident_id`, `assigned_worker_id`, `title`,
  `description`, and `location` (`latitude`, `longitude`, `address`).
  `priority` defaults to `MEDIUM`; `status` defaults to `ASSIGNED`. The
  assigned worker can accept or reject an `ASSIGNED` task using the worker
  decision routes; an already `ACCEPTED` task can enter execution directly.
  Checklist is optional; each step contains `step_id`, `title`, `required`,
  and optional `assigned_worker_id`. Timestamps default in the model. The
  helper requires the primary worker and every step owner to already exist in
  `workers`.
- **VERIFIED — ingestion limits** — `TaskRepository.add_task` rejects a
  duplicate task ID and does not update or cancel assignments. The shape
  above is the module's current internal model, not an approved Dispatch
  request body or a promise that Dispatch has these fields. Dispatch must
  map its worker-facing location label/address and coordinates to
  `location.address`, `location.latitude`, and `location.longitude`.
  A separate location name is not currently persisted. The external handoff,
  decision synchronization, and field mapping must be agreed before
  integration.

### Worker task and execution routes

- **VERIFIED** — `GET /worker/tasks` returns `{"tasks": [...]}`; each task
  has the `WorkerTask` fields described above. `GET /worker/tasks/{task_id}`
  returns the task. Both require worker bearer authentication.
- **VERIFIED** — `POST /worker/tasks/{task_id}/start`, `/resume`, and
  `/pause` return `{"task": ..., "message": ...}`. Start/resume requires
  `ACCEPTED` or `PAUSED`; the first start additionally requires a stored
  `BEFORE` image and a captured arrival location. Resume from `PAUSED` does
  not repeat that initial prerequisite check.
- **VERIFIED (legacy API)** — `GET /worker/tasks/{task_id}/checklist` returns
  `{"task_id": ..., "steps": [...]}`. `PATCH
  /worker/tasks/{task_id}/checklist/{step_id}` accepts
  `ChecklistStepUpdate` (`status`, optional `note`) and returns task/step IDs,
  status, note, timestamps, and a message. Updates require `IN_PROGRESS`.
- **VERIFIED** — Both checklist routes first require that the authenticated
  worker owns the task (`assigned_worker_id`). The PATCH route then also
  requires that worker to equal the step's `assigned_worker_id`. Therefore a
  secondary worker named as step owner cannot currently fetch that task's
  checklist or update the step; the primary-task-owner check fails before
  the step-owner check can authorize them. No crew-membership access rule is
  implemented.
- **VERIFIED** — `POST /worker/tasks/{task_id}/evidence` accepts multipart
  `evidence_type` (`BEFORE` or `AFTER`) and an uploaded file. The response
  contains an evidence record, a `duplicate` flag, and a message. The service
  validates JPEG/PNG/WebP content and applies task-state rules. AFTER upload
  requires `IN_PROGRESS` but no checklist state.

### Blocker routes

- **VERIFIED — report request** — `POST
  /worker/tasks/{task_id}/blockers` accepts `BlockerReport`:
  - `reason_code`: trimmed uppercase code matching
    `^[A-Z][A-Z0-9_]*$`, 1–50 characters;
  - `description`: trimmed, non-empty, 1–500 characters;
  - optional `step_id`: 1–100 characters.
  Extra fields are forbidden.
- **VERIFIED — report response** — On success the JSON object contains
  `blocker`, `task`, and `message`. The blocker record includes
  `blocker_id`, `task_id`, `worker_id`, optional `step_id`, `reason_code`,
  `description`, `status`, `previous_status`, `reported_at`, and resolution
  fields. The task status becomes `BLOCKED`; the blocker begins `OPEN`.
- **VERIFIED — reason-code behavior** — The central settings location
  provides `DEV_ACCESS`, `DEV_EQUIPMENT`, and `OTHER` only as non-approved development
  examples when no list is explicitly configured. An explicitly empty list
  returns `503`. Production reporting returns `503` unless a list is
  configured and `BLOCKER_REASON_CODES_APPROVED=true`; that flag represents
  deployment configuration, not evidence that a mentor has approved the
  vocabulary. A code outside the configured list returns `422`. Invalid or
  duplicate configured codes are rejected by settings validation. An
  unrelated database connection failure can also surface as `503` through
  the database error handler. Every configured reason code requires a
  non-empty description; `OTHER` uses the same description field to explain
  the issue.
- **VERIFIED — list routes** — `GET
  /worker/tasks/{task_id}/blockers` returns task ID and blocker history for
  that task. `GET /operator/blockers` returns all open blockers as
  `{"blockers": [...]}`. The latter is the existing way an operator caller
  can discover blockers; it is protected by the demo operator dependency in
  non-production only.
- **VERIFIED — unblock request/response** — `POST
  /operator/tasks/{task_id}/unblock` accepts an optional
  `BlockerResolution` body with an optional trimmed `resolution_note` of
  1–1000 characters. Success returns `blocker`, `task`, and `message`.
- **VERIFIED — authorization and state** — A worker cannot call the
  operator route. Unblock requires an existing `BLOCKED` task and its open
  blocker; otherwise it returns `404` or `409`. The demo operator ID is
  recorded as `resolved_by`. The operator dependency is not a shared
  production authorization mechanism.
- **VERIFIED — step behavior** — Reporting a blocker for a checklist step
  sets that step to `BLOCKED` and puts the description in its note. Unblock
  restores the task's previous status; it does not automatically change the
  checklist step from `BLOCKED`.
- **VERIFIED — current limitations** — At most one blocker can be open per
  task (also enforced by a PostgreSQL partial unique index). Resolved blocker
  records remain as history. The operator list has no pagination, cursor,
  acknowledgement, or event-delivery mechanism in the route/service.

### Location routes and current requirements

- **VERIFIED** — `POST /worker/tasks/{task_id}/arrival` and
  `/completion-location` accept `LocationEventCreate` with `event_type`,
  `capture_status`, optional latitude/longitude, optional accuracy, and
  optional device-capture time. The endpoint requires the event type to
  match its route.
- **VERIFIED** — Supported capture states are `CAPTURED`, `UNAVAILABLE`,
  and `INACCURATE`. A `CAPTURED` request requires both coordinates and
  accuracy. Coordinates must be finite and within latitude `-90..90` and
  longitude `-180..180`; accuracy must be finite, greater than zero, and no
  greater than 100,000 metres. Non-captured states must not include
  coordinates.
- **VERIFIED** — Captured accuracy worse than
  `MAX_GPS_ACCURACY_METERS` (default 100m) is stored as `INACCURATE` and
  coordinates are dropped. The event endpoint can still return success for
  unavailable/inaccurate readings; these states do not satisfy workflow
  prerequisites.
- **VERIFIED** — Arrival captures are accepted while task state is
  `ACCEPTED`, `IN_PROGRESS`, or `PAUSED`; completion-location captures while
  `IN_PROGRESS` or `PAUSED`. Invalid payloads return `422`, unsupported
  state returns `409`, missing/other-worker task returns `404`.
- **VERIFIED** — Repeated captures are retained; the task points to the
  latest event. A captured arrival is required to start. Completion
  submission requires a captured arrival and a captured completion event
  matching the task, authenticated primary worker, and `COMPLETION` type.
  An unavailable, inaccurate, missing, mismatched, or wrong-type completion
  event prevents submission with `422`.
- **VERIFIED** — No exception policy exists for unavailable GPS or
  inaccurate readings. The validators explicitly require captured fixes.
  GPS is recorded worker-device data, not proof of identity or presence.

### Completion submission

- **VERIFIED — request** — `POST /worker/tasks/{task_id}/completion` requires
  an `Idempotency-Key` header and a `CompletionClaim` body:
  - `evidence_ids`: list of unique evidence IDs, at least two by schema;
  - optional `completion_location_event_id`;
  - optional `notes`, up to 2,000 characters.
  Extra fields and duplicate references are rejected. The location field is
  optional at schema level, but completion validation requires a valid
  captured completion event.
- **VERIFIED — validation** — Submission requires task `IN_PROGRESS`,
  evidence for the same task and primary worker including at least one
  `BEFORE` and one `AFTER`, an arrival reference, and a valid captured
  completion-location event. Checklist status, step references, and AFTER
  freshness relative to checklist completion are not requirements.
- **VERIFIED — response and status** — Success returns
  `{"submission": ..., "message": ...}`. The submission contains its IDs,
  worker, checklist/evidence references, optional completion-location
  reference and notes, submission timestamp, and status
  `COMPLETION_SUBMITTED`. The task is set to the same status and stores the
  submission ID.
- **VERIFIED — current Verification input** — The current successful
  completion response's `submission` contains `submission_id`, `task_id`,
  `worker_id`, `checklist_step_ids`, `evidence_ids`,
  `completion_location_event_id`, `notes`, `submitted_at`, and `status`.
  For new submissions `checklist_step_ids` is empty and retained only for
  compatibility with historical records. The worker request body contains
  `evidence_ids`,
  `completion_location_event_id`, and `notes`; the key is in the
  `Idempotency-Key` header. Evidence file bytes are not embedded in that
  response; the listed IDs refer to persisted evidence records. The
  repository does not establish a Verification Agent transport, read
  permission, acknowledgement format, acknowledgement route, or retry
  contract. Whether an acknowledgement is required and its semantics remain
  an approval decision; no acknowledgement payload or endpoint is defined
  here.
- **VERIFIED — idempotency** — A nonblank key up to 200 characters is
  required. Same key and same canonicalized body returns the original
  submission, including after restart; same key with a different body
  returns `409`. Failed attempts do not consume the key. A database
  uniqueness race is mapped to `409`. After successful submission the task
  has no implemented worker transition back to `IN_PROGRESS`.
- **VERIFIED** — No verification result, verifier-facing read route, reject
  action, rework status, or resubmission process is present. The task is
  unique in `completion_submissions`, so repeated/new completion requests
  cannot create a later submission under current behavior.
- **Future Verification Agent boundary (not implemented):** An approved
  consumer would need to associate the task and worker IDs, BEFORE/AFTER
  evidence IDs, arrival and completion location event IDs, completion
  timestamp and notes from the task/submission records, plus blocker history
  from the worker blocker read API. The current task and completion APIs
  provide structured references but do not expose location-event history;
  access to the persisted event records must be designed and approved. No
  request is sent to a Verification Agent, and no verification result is
  created by this module.
- **PROPOSED boundary** — Until an approved cross-module contract exists,
  this module does not implement verification rejection or task reassignment.
  Dispatch retains assignment/reassignment ownership; Verification owns its
  independent assessment. The responsible teams must agree how findings and
  any rework instruction cross that boundary.

### Error response shape

- **VERIFIED** — Business `HTTPException` responses use `{"detail": "..."}`
  with statuses including `401`, `403`, `404`, `409`, `422`, and `503`;
  oversized evidence can return `413`. Request-schema validation also returns
  `422`, but its `detail` is a list of encoded validation errors rather than
  a string. Database connection failures return `503`; integrity conflicts
  return `409`.
- **PROPOSED** — Consumers should handle status code and `detail` shape
  explicitly until a cross-module error envelope is agreed. This audit does
  not propose a new error format.

## 4. Integration gap table

**Implementation update (2026-10-30):** The worker API now supports
accepting or rejecting the authenticated worker's own `ASSIGNED` task.
Acceptance persists as `ACCEPTED`; rejection requires a reason and writes a
`task_rejections` audit record in migration `0003`. This is a Field Worker
local task-decision workflow, not a Dispatch assignment-ingestion integration.
Dispatch still owns delivery, reassignment, and cancellation; no shared
handoff contract is implemented.

| Dependency | Current state | Missing decision/contract | Owning module/person | Blocking impact |
|---|---|---|---|---|
| Dispatch task handoff | **VERIFIED** — Field Worker reads stored tasks; `TaskRepository.add_task` inserts them. No Dispatch ingress route or Dispatch source is present. | **UNVERIFIED** — Transport, trigger, producer/consumer ownership, accepted-assignment payload mapping, retry semantics, duplicate delivery, and task/assignment update semantics. | **UNVERIFIED** — Dispatch and Field Worker integration owners are not named in repository documents. | **VERIFIED** — No defined production mechanism supplies accepted assignments. |
| Duplicate and changed assignments | **VERIFIED** — Existing `task_id` is rejected by the insert helper; there is no upsert or assignment-update method. | **PROPOSED** — Decide whether retries are idempotent and how reassignment, cancellation, changed location/details, and a changed primary worker affect execution history. | **UNVERIFIED** — Dispatch plus Field Worker maintainers. | **VERIFIED** — Re-delivery or an assignment change cannot be safely reconciled through the current insertion-only path. |
| Shared worker authentication | **VERIFIED** — Fixed demo Bearer credentials only; production startup is refused. | **UNVERIFIED** — Provider, token/claims contract, issuer/audience, validation ownership, revocation and active-worker handling, none of which should be inferred here. | **UNVERIFIED** — Shared-auth/KAVACH identity owner and Field Worker maintainers. | **VERIFIED** — Production service startup is blocked. |
| Canonical worker identity | **VERIFIED** — Task ownership compares the dependency's worker ID to `tasks.assigned_worker_id`; worker records use `worker_id`. | **PROPOSED** — Define an approved mapping from authenticated canonical worker identity to the existing `worker_id`; define behavior for unknown, inactive, or changed workers. | **UNVERIFIED** — Shared identity and Dispatch owners. | **VERIFIED** — Demo identity does not establish a production-safe worker-to-assignment check. |
| Blocker reason codes | **VERIFIED** — Development has non-approved example defaults; production reports `503` unless a configured list is explicitly marked approved; unknown configured code causes `422`. | **UNVERIFIED** — Final shared reason-code vocabulary and ownership of changes. | **UNVERIFIED** — Dispatch/operations and Field Worker maintainers. | **VERIFIED** — Production blocker reporting remains disabled until an approved list is configured. |
| Dispatch blocker discovery | **VERIFIED** — `GET /operator/blockers` lists all open blockers, protected by demo operator auth; no paging, eventing, acknowledgement, or production auth. | **PROPOSED** — Agree polling/event delivery, freshness/retry, pagination, acknowledgement/ownership, authorization, and resolution consistency. No Dispatch endpoint is specified here. | **UNVERIFIED** — Dispatch and Field Worker integration owners. | **VERIFIED** — Only the module's development-oriented listing path exists; production Dispatch integration is not defined. |
| Blocker resolution authorization | **VERIFIED** — Operator demo token resolves task blockers; worker token cannot. | **UNVERIFIED** — Shared role/permission and actor-identity contract for Dispatch/Supervisor operations. | **UNVERIFIED** — Shared auth and Dispatch/operations owners. | **VERIFIED** — Demo operator credentials are refused in production. |
| GPS exceptions | **VERIFIED** — Captured, sufficiently accurate events are required for start and completion. | **UNVERIFIED** — Decisions for unavailable GPS, inaccurate readings, and any permitted exception/approval trail. | **UNVERIFIED** — Product/operations/Dispatch and Field Worker maintainers. | **VERIFIED** — No exception path exists; affected workers cannot start or submit completion using only unavailable/inaccurate fixes. |
| Checklist crew access | **VERIFIED** — Step records can name another worker, but every route first requires task primary-worker ownership. | **UNVERIFIED** — Crew membership, per-task access, worker scope, updates, revocation, and primary-worker reassignment contract. | **UNVERIFIED** — Dispatch/crew owner and Field Worker maintainers. | **VERIFIED** — A non-primary step owner cannot access or update that task's step via current APIs. |
| Verification Agent handoff | **VERIFIED** — Completion claim and evidence references are persisted; status is `COMPLETION_SUBMITTED`. No verifier API exists. | **UNVERIFIED** — How the verifier discovers/reads a submission and evidence; result, authorization, acknowledgement, and delivery contract. | **UNVERIFIED** — Verification Agent and Field Worker owners. | **VERIFIED** — No implemented handoff exposes submissions to a separate Verification Agent. |
| Verification rejection/rework | **VERIFIED** — Completion is terminal in current worker transitions; no rejection/rework status or resubmission path exists. | **UNVERIFIED** — Rework decision, reasons, evidence retention, who can reopen, and whether a new submission/idempotency generation is allowed. | **UNVERIFIED** — Verification Agent, Dispatch, and Field Worker owners. | **VERIFIED** — A rejected claim cannot currently be returned to worker execution through this module. |
| Database readiness | **VERIFIED** — PostgreSQL only; current migration head in source is `0002`. Test fixtures migrate and truncate a database explicitly guarded as `_test`. | **UNVERIFIED** — Actual revisions of `kavach_test` and `kavach`; approved deployment window, backups, operator and validation procedure are not established in repository files. | **UNVERIFIED** — Database owner/mentor and Field Worker maintainer. | **VERIFIED** — Application refuses startup if database revision differs from source head. |

## 5. Proposed integration sequence

The following is **PROPOSED**, not an approved contract or an instruction to
implement now.

1. **Approve ownership and vocabulary.** Name Dispatch, shared-auth,
   Verification Agent, database, and Field Worker owners. Agree canonical
   task, worker, incident, assignment, checklist-step, and status meanings.
   Preserve the distinction between Dispatch offer statuses and Field Worker
   execution statuses.
2. **Approve shared identity before production handoff.** Define the
   sanctioned authentication mechanism and how its canonical worker identity
   maps to `worker_id`. Decide active-worker and operator authorization
   behavior. Do not substitute a locally invented token or endpoint.
3. **Specify Dispatch assignment delivery and lifecycle.** Define the exact
   accepted-assignment fields and mapping to `WorkerTask`, the delivery
   trigger, retry/duplicate behavior, and changes/cancellations/reassignment.
   Decide whether Dispatch owns writing the shared database or calls an
   approved Field Worker integration surface; no such surface is defined by
   this audit.
4. **Approve blocker operations.** Agree the reason-code list, who maintains
   it, how Dispatch discovers new/open blockers, and how resolution is
   authorized and recorded. Decide whether the current unpaged open-blocker
   list is sufficient before specifying any polling or event delivery.
5. **Resolve crew and GPS policy.** Agree the task/crew access rule for
   secondary step owners. Separately decide GPS unavailable/inaccurate
   exception policy and audit requirements. Until approval, retain current
   strict validation.
6. **Define completion verification and rework.** Specify how the
   Verification Agent receives a submission and reads associated evidence,
   the verification outcome vocabulary, and a controlled rework/resubmission
   lifecycle. Do not treat `COMPLETION_SUBMITTED` as verified.
7. **Approve and execute database rollout separately.** First review
   migration history and generated SQL, verify exact PostgreSQL targets and
   current revisions, back up, and obtain database-owner approval. Apply the
   reviewed migration only under the approved procedure in section 7.
8. **Run cross-module acceptance tests after contracts are approved.**
   Validate handoff retries/updates, canonical identity and authorization,
   crew access, blocker discovery/resolution, GPS decisions, verification
   handoff/rework, and migration compatibility in a safe staging environment.

## 6. Compatibility and regression risks

### Verified behavior and compatibility constraints

- **VERIFIED** — No accept/reject route is defined in `worker_task_routes.py`
  or the current OpenAPI contract. Repository search found only explanatory
  comments/docs about Dispatch ownership, not a remaining route implementation.
- **VERIFIED** — `ASSIGNED` and `REJECTED` remain in the model/database status
  constraint but have no Field Worker transition. Existing records in those
  states cannot be advanced by this worker state machine.
- **VERIFIED** — Migration `0001` stores completion submissions as
  `SUBMITTED_FOR_VERIFICATION`; migration `0002` changes the stored value to
  `COMPLETION_SUBMITTED`. The current model and API use
  `COMPLETION_SUBMITTED`. The historical name in `0001` is an intentional
  migration predecessor, not evidence that the current API still emits that
  value.
- **VERIFIED** — API request validation errors and business validation errors
  both use status `422`, but their `detail` JSON shapes differ (validation
  error list versus string). Consumers that assume one shape risk breakage.
- **VERIFIED** — The README lists routes and high-level rules, but it does not
  fully specify request/response schemas, Dispatch handoff, shared auth,
  crew access, GPS exception policy, blocker delivery semantics, or
  verification/rework.
- **VERIFIED** — There is no SQLite fallback. URL parsing accepts PostgreSQL
  URLs only; models/migrations include PostgreSQL-specific behavior, including
  regex constraints and a partial unique blocker index.
- **VERIFIED** — A step-specific blocker leaves its checklist step `BLOCKED`
  after task unblock. A worker may later update a step only if they pass the
  task-level primary-worker check and the task is `IN_PROGRESS`.

### Coverage observed statically

- **VERIFIED** — Tests are present for authentication, route/schema shape,
  task transitions, checklist rules, blockers, completion validation and
  idempotency, location validation, evidence, and test-database guards.
- **VERIFIED** — The auth tests check demo authentication refusal in
  production; the task-level checklist authorization tests check access to a
  different worker's task.
- **UNVERIFIED** — No tests were executed in this audit, so no passing count
  or runtime behavior is asserted.
- **VERIFIED** — Repository tests exercise current module behavior; the
  inspected test set does not establish a real Dispatch handoff, shared
  identity provider, secondary-worker access to another worker's task,
  verifier delivery, or completion rework contract. Those integrations are
  absent from the source inspected.

### Potential risks, not confirmed defects

- **UNVERIFIED** — Dispatch may have external contracts or integration code
  outside this repository. None was available to inspect, so compatibility
  with it cannot be claimed.
- **PROPOSED** — Treat duplicate assignment delivery and reassignment as
  explicit contract cases before connecting a producer to the insertion-only
  helper.
- **PROPOSED** — Treat the current error-shape difference, unpaged blocker
  listing, and terminal completion status as consumer integration risks to
  resolve in the owning contracts rather than silently normalizing them.

## 7. Database migration safety notes

- **VERIFIED** — Migration history in source is linear: `0001` then `0002`;
  the source migration head is `0002`. `0002` adds `BLOCKED`, step owner and
  completion-time fields, blocker storage, and changes the completion
  submission status value. Its upgrade statements backfill existing step
  owners and completion timestamps.
- **VERIFIED** — The application checks that a PostgreSQL database's
  `alembic_version` matches source head during startup and refuses to start
  when it does not. PostgreSQL is the only supported application database.
- **VERIFIED** — Test setup requires a configured database name ending in
  `_test`, checks that it is not the configured application database by name,
  checks the server-reported database name before migration/reset, applies
  `alembic upgrade head`, then truncates application tables and reseeds before
  database-backed tests. Therefore running tests can migrate and modify the
  configured test database.
- **VERIFIED** — Migration `0002` downgrade drops blocker history and refuses
  to proceed if tasks remain `BLOCKED`. Migration `0001` downgrade drops all
  KAVACH tables/data. Downgrade is not a routine rollback option for data
  that must be preserved.
- **UNVERIFIED** — The implementation report's database states (`kavach_test`
  at `0002` and development `kavach` at `0001`) were not checked. Static
  source cannot establish a live database revision, and no database was
  accessed.
- **PROPOSED** — Before a later approved rollout: obtain database-owner and
  mentor approval; identify each target by connection configuration and
  server-reported database name; take and verify a restorable backup; record
  `alembic current` for each target without relying on the report; review
  migration SQL and data-impact assumptions against a staging copy; schedule
  the upgrade with the application version requiring head `0002`; apply only
  `alembic upgrade head` to the explicitly approved PostgreSQL target; then
  verify the revision and perform approved read-only integrity/smoke checks.
  Keep the backup until acceptance. Do not run test fixtures against a
  non-disposable database and do not use downgrade as a substitute for a
  recovery plan.
- **UNVERIFIED** — No approved migration runbook, maintenance window, named
  operator, or rollback/recovery approval is recorded in inspected repository
  documents. The procedure above is a recommendation, not an already
  approved procedure.

## 8. Acceptance checklist for integration

The items below are **PROPOSED acceptance gates**; none is marked complete by
this static audit.

- [ ] Dispatch and Field Worker owners approve accepted-assignment field
  mapping, identifiers, status semantics, delivery/retry behavior, duplicate
  handling, and assignment updates/cancellations.
- [ ] Shared-auth owner approves the production identity contract; an
  authenticated canonical worker is mapped and authorized against the
  assignment's `worker_id`, with inactive/unknown-worker behavior defined.
- [ ] Production startup succeeds only with the approved shared auth setup;
  demo worker/operator credentials remain development-only.
- [ ] Dispatch blocker discovery and resolution contracts are approved,
  including authorization, pagination or delivery semantics, and the final
  reason-code vocabulary.
- [ ] Secondary-worker/crew access to tasks and checklist steps is explicitly
  decided and tested, or multi-worker assignment is explicitly excluded.
- [ ] Unavailable/inaccurate GPS policy and any permitted exception are
  approved, audited, and tested without weakening current validation by
  assumption.
- [ ] Verification Agent submission discovery/read access, outcome handling,
  and evidence access are approved and tested.
- [ ] Rejected completion/rework behavior is approved, including task
  transitions, evidence history, resubmission and idempotency semantics.
- [ ] Route request/response/error contracts are documented for consumers,
  including the existing validation-versus-business `422` response shape.
- [ ] Database owner verifies exact PostgreSQL target revisions and backup;
  approved migration `0002` is applied and checked through the approved
  procedure.
- [ ] Integration/regression tests run against an explicitly disposable
  PostgreSQL test database and cover the approved cross-module cases.

## 9. Open decisions requiring mentor/team approval

1. **UNVERIFIED** — Which Dispatch system/team owns assignment creation and
   accepted-task delivery, and what authoritative contract governs it?
2. **UNVERIFIED** — Which task and incident IDs are canonical across modules,
   and what happens when the same task is delivered more than once or later
   reassigned/updated/cancelled?
3. **UNVERIFIED** — What shared authentication provider and validated
   identity claims does KAVACH approve? How does the authenticated subject
   map to `worker_id`, and how are inactive workers and operator roles
   handled?
4. **UNVERIFIED** — What blocker reason-code list is finalized, who owns it,
   and what Dispatch discovery/acknowledgement/resolution workflow is
   approved?
5. **UNVERIFIED** — Can a checklist step be assigned to a worker who is not
   the task's primary worker? If yes, what gives that worker task-level API
   access and how is access revoked?
6. **UNVERIFIED** — What should happen when GPS is unavailable or fails the
   accuracy threshold at arrival or completion? Are exceptions allowed, and
   who approves and audits them?
7. **UNVERIFIED** — How does the Verification Agent receive and read a
   completion submission and its evidence, and what outcome states and
   authorization are approved?
8. **UNVERIFIED** — If verification rejects a claim, who reopens the task,
   what reason/evidence is retained, and how can a subsequent submission be
   distinguished and made idempotent?
9. **UNVERIFIED** — Are the reported live revisions for `kavach_test` and
   `kavach` correct, and who approves and performs the safe migration rollout?
10. **UNVERIFIED** — Which team/person owns the final cross-module contract
    and acceptance sign-off? No named owner or approved contract was found in
    the inspected repository documents.
