# Field Worker Frontend API Contract

This document describes the Field Worker backend contract verified in the
current routes, Pydantic schemas, services, configuration, and tests. It is
for the worker-facing frontend only. Every implemented API path below is
prefixed by `/api/v1`. Unless an endpoint is explicitly marked as a gap, it
is implemented and returns HTTP `200` on success.

**Workflow update (2026-10-28):** Checklist steps are no longer part of the
Field Worker execution flow. Legacy checklist endpoints, fields, and
database structures remain for compatibility, but do not gate start, AFTER
evidence upload, or completion.

## Authentication and authorization

### Current development behavior

All `/api/v1/worker/...` endpoints require:

```http
Authorization: Bearer <worker-token>
```

The current dependency compares this bearer token to the configured demo
worker token and maps it to one configured fixed worker ID. It does not
decode a user identity from a token. Missing or invalid credentials return
`401` with `{"detail":"Invalid authentication."}` and a `WWW-Authenticate:
Bearer` header. Demo authentication is explicitly refused when
`APP_ENV=production`.

The application also refuses production startup until shared KAVACH
authentication is integrated. The demo token and fixed worker identity are
development/test behavior, not a production login or identity contract.
There is no login, refresh, or logout endpoint in this module.

Task-scoped reads and actions verify the authenticated worker is the task's
primary `assigned_worker_id`. A task that does not exist or belongs to
another worker returns `404` (`{"detail":"Task not found."}`), rather than
revealing another worker's task. The retained legacy checklist update route
also checks the step's `assigned_worker_id`; it is not used by the current
worker workflow.

## Shared response and lifecycle facts

**Task location integration:** The current worker-task response keeps
`location.address`, `location.latitude`, and `location.longitude`. The
frontend renders the response values directly, maps valid coordinates, and
gracefully omits the map marker when coordinates are missing or invalid.
There is no Dispatch assignment-ingestion endpoint. Dispatch must populate
these fields through its future approved integration; a distinct
`location.name` is not part of the current backend schema and requires an
approved contract/schema change if it must be stored separately.

**GPS display and validation:** The frontend captures browser geolocation
only after an explicit worker action, using high-accuracy mode and no cached
position. It checks the device timestamp, shows the device-reported accuracy
and distance to the assigned coordinates, and asks the worker to confirm
before submitting. Acquisition watches for improving readings for up to 60 seconds
and only enables submission when the best reading meets the server-provided
accuracy threshold. The request uses `event_type`, `capture_status`,
`latitude`, `longitude`, `accuracy_meters` (metres), and
`captured_at_device` (ISO-8601 timestamp); frontend-only coordinate-source
metadata is not sent to the API. The backend applies
`MAX_GPS_ACCURACY_METERS` and returns `CAPTURED` or `INACCURATE`; the frontend
does not guess the configured threshold. Deployed pages need HTTPS for
browser geolocation; localhost is permitted for development. There is no
task-proximity threshold in the current API, so distance is informational.
GPS is not proof of identity or physical presence.

The worker task-details response includes the server-configured GPS accuracy
threshold and the latest arrival/completion event summaries. Each summary
includes event ID, capture status, accuracy, device/server timestamps,
whether that event is the task's accepted progression reference, and a
non-sensitive rejection reason when applicable. The task list response remains
unchanged. An inaccurate event is retained for audit but does not update the
task's arrival/completion reference. Once an acceptable reference exists,
retries return that same event instead of creating another accepted event;
the task row lock serializes concurrent submissions.

- Request/schema validation errors return `422`, normally as
  `{"detail":[{"loc":[...],"msg":"...","type":"..."}]}`. Business-rule
  failures return `{"detail":"..."}`.
- Database connection failures return `503` with
  `{"detail":"Database unavailable. Please retry later."}`. Database
  integrity conflicts return `409` with
  `{"detail":"Request conflicts with existing data."}`.
- The statuses defined for task records include `ASSIGNED`, `ACCEPTED`,
  `REJECTED`, `IN_PROGRESS`, `PAUSED`, `BLOCKED`, and
  `COMPLETION_SUBMITTED`. An assigned worker may accept (`ASSIGNED` →
  `ACCEPTED`) or reject (`ASSIGNED` → `REJECTED`) their own task. Acceptance
  is persisted in the task status; rejection also persists its reason, worker
  ID and timestamp. Field Worker does not set `VERIFIED` or `CLOSED`.
- Worker actions cannot transition a `BLOCKED` task. Unblock is an
  operator-owned route with demo-only authentication, not a worker frontend
  capability. After unblock, the service restores the task's recorded prior
  status.
- No endpoint in this contract accepts query parameters.

## Implemented worker endpoints

### Accept an assigned task

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/accept`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Request:** No body.
- **Success (`200`):** `{"task":<WorkerTask>,"message":"Task accepted."}`.
- **Errors:** `401`, `404`, `409`, `503`.
- **Lifecycle:** Only the task's assigned worker may accept it, and only
  while its status is `ASSIGNED`. The transition is persisted as `ACCEPTED`;
  repeats or decisions from other states return `409`.
- **Implementation:** Implemented.

### Reject an assigned task

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/reject`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Request:** `{"reason":"..."}`; reason is trimmed and must contain 1–500
  non-whitespace characters. Extra fields are rejected.
- **Success (`200`):** Includes the task with status `REJECTED`, a persisted
  rejection object containing `task_id`, `worker_id`, `reason`, and
  `rejected_at`, and a confirmation message.
- **Errors:** `401`, `404`, `409`, `422`, `503`.
- **Lifecycle:** Only the assigned worker may reject a task in `ASSIGNED`.
  Status and rejection audit data are committed in the same transaction.
  Rejection does not delete or reassign the task.
- **Implementation:** Implemented; persistence requires migration `0003`.

### 1. List assigned tasks

- **Method/path:** `GET /api/v1/worker/tasks`
- **Authentication:** Worker bearer token.
- **Path/query parameters:** None.
- **Request:** No body.
- **Success (`200`):** `{"tasks":[<WorkerTask>, ...]}`. Each task contains:
  `task_id`, `incident_id`, `assigned_worker_id`, `title`, `description`,
  `priority` (`LOW`, `MEDIUM`, `HIGH`), `status`, `location`,
  `checklist`, `created_at`, `updated_at`, `arrival_location_event_id`,
  `completion_location_event_id`, and `completion_submission_id`.
  `location` contains `latitude`, `longitude`, and `address`. Each checklist
  definition contains `step_id`, `title`, `required`, and
  `assigned_worker_id`; this field is legacy and ignored by the current
  worker interface.
- **Errors:** `401`, `503`.
- **Lifecycle:** Returns tasks for the authenticated primary worker; does
  not include other workers' tasks.
- **Implementation:** Implemented.

### 2. Get task details

- **Method/path:** `GET /api/v1/worker/tasks/{task_id}`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id` (string, 1–100 characters in the task
  schema).
- **Query parameters:** None.
- **Request:** No body.
- **Success (`200`):** One `WorkerTaskDetailsResponse`, including the fields
  documented for task list items plus `gps_accuracy_threshold_meters`
  (positive JSON number from the backend's effective
  `MAX_GPS_ACCURACY_METERS` setting), `arrival_location_accepted`,
  `completion_location_accepted`, `accepted_arrival_location`,
  `latest_arrival_location`, and `latest_completion_location`. The accepted
  arrival summary is the backend-confirmed task reference and may be `null`;
  it is separate from the latest audit event so a later poor-quality event
  cannot hide or replace the accepted worker marker. Latest summaries may
  also be `null`; when present they include event quality, accuracy,
  device/server timestamps, progression acceptance, and a non-sensitive
  rejection reason.
- **Errors:** `401`, `404`, `503`.
- **Lifecycle:** Only the task's assigned primary worker can retrieve it.
- **GPS contract:** The frontend must not start geolocation acquisition if
  the threshold is missing, non-numeric, or non-positive. Refresh task details
  and correct/restart the backend if this required response field is absent;
  the frontend does not substitute its own threshold.
- **Implementation:** Implemented.

### 3. Start or resume via start

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/start`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters/request body:** None.
- **Success (`200`):** `{"task":<WorkerTask>,"message":"Task started or
  resumed."}`.
- **Errors:** `401`, `404`, `409`, `422`, `503`.
- **Lifecycle:** For an `ACCEPTED` task, requires a stored `BEFORE` evidence
  record and a `CAPTURED` arrival location belonging to that task and
  worker. Missing prerequisites return `422`. A `PAUSED` task may also use
  this route to resume; that path does not repeat first-start prerequisites.
  Other states return `409`.
- **Implementation:** Implemented. This endpoint does not accept or reject
  an assignment; use the explicit accept/reject routes for an `ASSIGNED` task.

### 4. Pause task

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/pause`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters/request body:** None.
- **Success (`200`):** `{"task":<WorkerTask>,"message":"Task paused."}`.
- **Errors:** `401`, `404`, `409`, `503`.
- **Lifecycle:** Only the allowed transition from `IN_PROGRESS` to `PAUSED`
  succeeds. A `BLOCKED` task cannot be paused by the worker.
- **Implementation:** Implemented.

### 5. Resume paused task

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/resume`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters/request body:** None.
- **Success (`200`):** `{"task":<WorkerTask>,"message":"Task resumed."}`.
- **Errors:** `401`, `404`, `409`, `503`.
- **Lifecycle:** Requires `PAUSED`; returns the task to `IN_PROGRESS`.
  `ACCEPTED` and `BLOCKED` tasks cannot use this endpoint.
- **Implementation:** Implemented.

### 6. Legacy checklist reads

- **Method/path:** `GET /api/v1/worker/tasks/{task_id}/checklist`
- **Current workflow:** Not used. Retained for compatibility only.
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters:** None.
- **Request:** No body.
- **Success (`200`):** `{"task_id":"...","steps":[...]}`. Each step contains
  `step_id`, `task_id`, `assigned_worker_id`, `status`
  (`PENDING`, `COMPLETED`, `BLOCKED`), `note`, `updated_at`, and
  `completed_at`.
- **Errors:** `401`, `404`, `503`.
- **Lifecycle/authorization:** Task's primary worker only. Step assignment
  is returned, but it does not grant secondary workers access to the task.
- **Implementation:** Implemented.

### 7. Legacy checklist updates

- **Method/path:** `PATCH /api/v1/worker/tasks/{task_id}/checklist/{step_id}`
- **Current workflow:** Not used. Retained for compatibility only.
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`, `step_id`.
- **Query parameters:** None.
- **Request JSON:** `{"status":"PENDING|COMPLETED|BLOCKED","note":null|string}`.
  `status` is required. `note` is optional and limited to 500 characters.
  Unknown fields are rejected.
- **Success (`200`):** `task_id`, `step_id`, `status`, `note`, `updated_at`,
  `completed_at`, and `message`.
- **Errors:** `401`, `403`, `404`, `409`, `422`, `503`.
- **Lifecycle/authorization:** Task must be `IN_PROGRESS`; authenticated
  worker must be both the primary task worker and the step's assigned
  worker. A missing/non-owned task or missing step returns `404`; a step
  assigned to another worker returns `403`.
- **Implementation:** Implemented.

### 8. Upload BEFORE or AFTER evidence

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/evidence`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters:** None.
- **Request:** `multipart/form-data` with required `evidence_type`
  (`BEFORE` or `AFTER`) and required image `file`.
- **Success (`200`):** `{"evidence":<EvidenceRecord>,"duplicate":boolean,
  "message":string}`. The current `EvidenceRecord` serialization contains
  `evidence_id`, `task_id`, `worker_id`, `evidence_type`, `storage_key`,
  `original_filename`, `mime_type`, `size_bytes`, `sha256`, `status`
  (`STORED`), and `uploaded_at`. An exact duplicate for the same task,
  worker, evidence type, and image content reuses the existing record and
  file, with `duplicate: true`.
- **Errors:** `401`, `404`, `409`, `413`, `422`, `503`. Invalid/empty
  images, unsupported media, MIME/content mismatch, and missing/invalid form
  values return `422`. Files larger than the configured maximum return
  `413` (default maximum is 5 MiB).
- **Lifecycle:** `BEFORE` upload is allowed in `ACCEPTED`, `IN_PROGRESS`, or
  `PAUSED`. `AFTER` upload is allowed only in `IN_PROGRESS`; checklist state
  is not a prerequisite. Neither evidence type can be
  uploaded while `BLOCKED` or after completion submission. Accepted image
  formats are JPEG, PNG, and WebP; content is decoded and checked against
  declared MIME type.
- **Implementation:** Implemented.
- **Contract/security inconsistency:** The upload response currently exposes
  `storage_key` and `sha256` because it serializes the full `EvidenceRecord`.
  The read-only history response omits those fields. `storage_key` is an
  internal storage reference, not a supported image URL. The frontend must
  not treat it as a download path; this response-shape inconsistency is
  documented for API owners, not silently normalized here.

### 9. Read evidence history

- **Method/path:** `GET /api/v1/worker/tasks/{task_id}/evidence`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters/request body:** None.
- **Success (`200`):** `{"task_id":"...","evidence":[...]}`. Each history
  item contains `evidence_id`, `task_id`, `worker_id`, `evidence_type`,
  `original_filename`, `mime_type`, `size_bytes`, `status`, and
  `uploaded_at`. Records are historical and ordered by upload time and
  evidence ID.
- **Errors:** `401`, `404`, `503`.
- **Lifecycle/authorization:** Task's primary worker only. Older `AFTER`
  records remain in history. Checklist changes do not affect evidence
  validity or completion.
- **Implementation:** Implemented. Response does not expose a storage key,
  image bytes, device capture timestamp, or linked location-event ID.

### 10. Submit arrival location

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/arrival`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters:** None.
- **Request JSON (`LocationEventCreate`):**
  - `event_type`: required, must be `ARRIVAL`.
  - `capture_status`: required; `CAPTURED`, `UNAVAILABLE`, or `INACCURATE`.
  - `latitude`, `longitude`, `accuracy_meters`, `captured_at_device`:
    optional fields; `CAPTURED` requires latitude, longitude, and accuracy.
    Latitude range is -90..90, longitude -180..180, and accuracy must be
    greater than 0 and at most 100,000 metres. Non-captured states must not
    include coordinates.
  - Extra fields are rejected.
- **Success (`200`):** `{"location_event":{ "location_event_id","task_id",
  "worker_id","event_type","capture_status","latitude","longitude",
  "accuracy_meters","captured_at_device","received_at_server" }}`.
- **Errors:** `401`, `404`, `409`, `422`, `503`.
- **Lifecycle:** Allowed while task is `ACCEPTED`, `IN_PROGRESS`, or
  `PAUSED`. A captured reading whose accuracy exceeds configured
  `MAX_GPS_ACCURACY_METERS` (default 100 metres) is stored as
  `INACCURATE`, with coordinates removed. Only a captured arrival satisfies
  first-start requirements.
- **Implementation:** Implemented as event validation/storage. Device GPS
  acquisition is not implemented by this backend.

### 11. Submit completion location

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/completion-location`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters:** None.
- **Request JSON:** Same `LocationEventCreate` fields and validation as
  arrival, but `event_type` must be `COMPLETION`.
- **Success (`200`):** Same location-event response shape as arrival.
- **Errors:** `401`, `404`, `409`, `422`, `503`.
- **Lifecycle:** Allowed while `IN_PROGRESS` or `PAUSED`. Only a captured
  completion event belonging to the task and worker can satisfy completion.
  Unavailable/inaccurate states may be recorded but do not satisfy the
  completion prerequisite.
- **Implementation:** Implemented as event validation/storage. Device GPS
  acquisition and GPS exception policy are not implemented.

### 12. Retrieve permitted blocker reason codes

- **Method/path:** `GET /api/v1/worker/blockers/reason-codes`
- **Authentication:** Worker bearer token.
- **Path/query parameters/request body:** None.
- **Success (`200`):** `{"reason_codes":[{"code":"..."}]}`. Codes come from
  the same configured allow-list used by blocker reporting. No display
  labels or descriptions exist in configuration, so the endpoint returns
  only `code`. The default development list includes `DEV_ACCESS`,
  `DEV_EQUIPMENT`, and `OTHER`; deployments with an explicit allow-list must
  include `OTHER` if workers should be able to select it.
- **Errors:** `401`, `503`.
- **Lifecycle/configuration:** Empty, unavailable, malformed, or duplicate
  configuration fails closed with `503`. In production, a non-empty
  configured list and `BLOCKER_REASON_CODES_APPROVED=true` are required.
  However, production app startup remains blocked pending shared
  authentication, so this endpoint is currently usable only in
  development/test environments.
- **Implementation:** Implemented.

### 13. Report a blocker

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/blockers`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters:** None.
- **Request JSON (`BlockerReport`):**
  - `reason_code`: required string, trimmed, 1–50 characters, pattern
    `^[A-Z][A-Z0-9_]*$`, and must be present in the configured allow-list.
  - `description`: required string, trimmed, 1–500 characters.
  - `step_id`: optional nullable string, 1–100 characters when provided.
  - Extra fields are rejected.
  A description is required for every reason code; when `OTHER` is selected,
  it should explain the issue that is not covered by the other choices.
- **Success (`200`):** `{"blocker":<BlockerRecord>,"task":<WorkerTask>,
  "message":"Blocker reported; Dispatch must resolve it."}`. A blocker
  record contains `blocker_id`, `task_id`, `worker_id`, `step_id`,
  `reason_code`, `description`, `status` (`OPEN`), `previous_status`,
  `reported_at`, `resolved_at`, `resolved_by`, and `resolution_note`.
- **Errors:** `401`, `404`, `409`, `422`, `503`. `422` includes an invalid
  or unconfigured submitted code; `503` means the list is unavailable or
  production approval is missing.
- **Lifecycle:** Only `ACCEPTED`, `IN_PROGRESS`, or `PAUSED` tasks may be
  blocked. There can be only one open blocker per task. If `step_id` is
  supplied, it must exist and be assigned to this worker; that step is
  marked `BLOCKED` with the description as its note. The task becomes
  `BLOCKED`. The worker cannot unblock it.
- **Implementation:** Implemented. Dispatch notification/polling is not
  implemented as a shared integration contract.

### 14. Get task blocker history

- **Method/path:** `GET /api/v1/worker/tasks/{task_id}/blockers`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters/request body:** None.
- **Success (`200`):** `{"task_id":"...","blockers":[<BlockerRecord>, ...]}`.
- **Errors:** `401`, `404`, `503`.
- **Lifecycle/authorization:** Task's primary worker only. Includes stored
  blocker history; it does not provide operational unblock controls.
- **Implementation:** Implemented.

### 15. Submit completion

- **Method/path:** `POST /api/v1/worker/tasks/{task_id}/completion`
- **Authentication:** Worker bearer token.
- **Path parameters:** `task_id`.
- **Query parameters:** None.
- **Required header:** `Idempotency-Key`, non-blank, maximum 200 characters.
- **Request JSON (`CompletionClaim`):**
  - `evidence_ids`: required array of at least two unique strings.
  - `completion_location_event_id`: optional string.
  - `notes`: optional string, maximum 2,000 characters.
  - Extra fields are rejected.
- **Success (`200`):** `{"submission":{ "submission_id","task_id","worker_id",
  "checklist_step_ids","evidence_ids","completion_location_event_id",
  "notes","submitted_at","status" },"message":"Completion claim recorded
  for independent verification."}`. `status` is
  `COMPLETION_SUBMITTED`. New submissions return an empty
  `checklist_step_ids` field for compatibility with the persisted response
  model and historical records.
- **Errors:** `401`, `404`, `409`, `422`, `503`. `409` includes a task in
  the wrong state, conflicting reuse of an idempotency key, or a concurrent
  submission. `422` includes invalid evidence or location prerequisites.
- **Lifecycle:** Task must be `IN_PROGRESS`. Submitted evidence must belong
  to the same task and worker and include at least one `BEFORE` and one
  `AFTER`. An arrival reference must exist on the task, and a captured
  completion location ID must be submitted; it must belong to the same task
  and worker and be a `COMPLETION` event. Blocked tasks cannot submit
  completion. Checklist state, references, and AFTER-photo freshness relative
  to checklist completion are not requirements. The Field Worker records
  `COMPLETION_SUBMITTED`; it does not mark work verified or closed.
- **Idempotency:** Repeating the same task/worker/key and identical request
  returns the existing submission. Reusing the key with a different
  request returns `409`. List order is significant when comparing request
  bodies.
- **Implementation:** Implemented. Verification acknowledgement, rejection,
  rework, reassignment, and resubmission contracts are not implemented.

## Relevant documented gaps (not endpoints)

The following are not available as worker frontend API operations:

- **Shared production authentication / login:** No identity provider,
  production token validation contract, or login route exists here.
- **Assignment ingestion:** No Dispatch-to-Field-Worker assignment
  ingestion/confirmation endpoint exists. Tasks must be present in the
  backend before the worker can list them. Worker accept/reject decisions
  are supported for `ASSIGNED` tasks, but do not integrate Dispatch handoff,
  reassignment, or cancellation.
- **Image retrieval:** The evidence history API returns metadata only. There
  is no safe image URL or image-byte retrieval endpoint. The upload response
  includes internal `storage_key`, but that is not a supported retrieval
  contract.
- **Device camera and GPS capture:** Backend accepts multipart images and
  location-event data but does not invoke a device camera or browser/mobile
  Geolocation API. The frontend must acquire these locally and submit the
  resulting data. GPS metadata is not extracted from EXIF and is not linked
  to evidence records.
- **Legacy checklist access:** Checklist routes and secondary step-owner
  restrictions remain for compatibility, but checklist is not required by
  the current workflow.
- **Operator unblock control:** Existing operator routes use demo
  authentication and are not production/shared-auth or worker UI contracts.
- **Dispatch blocker delivery and Verification handoff:** No event/polling,
  completion acknowledgement, rejection, or rework API contract is defined.
- **GPS exceptions:** Unavailable/inaccurate event records can be stored,
  but no exception lets them satisfy start or completion prerequisites.

## Source/test basis and verification note

This contract was derived from the current `app/api` routes,
`app/schemas` models, `app/services` and validator behavior, application
authentication/configuration, and the corresponding tests for task actions,
checklists, evidence, locations, blocker reason codes, completion,
authentication, and OpenAPI operations. Tests were not run for this
documentation task.
