# KAVACH Field Worker Frontend Setup

## Status and scope

The worker-facing frontend uses React, JavaScript/JSX, Vite, and React Router.
It lives in `frontend/` and is separate from the FastAPI backend under
`app/`. The interface includes an assigned-task list and task details with an
interactive assigned-location map, Accept/Reject decisions for assigned
tasks, Start/Pause/Resume controls; BEFORE/AFTER evidence upload and metadata
history; browser GPS capture and separate arrival/completion location
submission; blocker reporting and history; and completion submission.
Checklist UI and requests are not part of the current worker workflow.

The frontend includes a reusable API client and development-token handling.
Shared production authentication is not integrated.

The interactive map uses Leaflet with OpenStreetMap tiles. It renders task
location fields returned by the backend and device coordinates only after an
explicit browser GPS capture. The current backend contract is
`location.address`, `location.latitude`, and `location.longitude`; the worker
page displays those response values and does not choose a default site or
coordinate. A separate `location.name` is displayed if a compatible response
provides one, but it is not part of the current backend schema. Map rendering
requires internet access to the OpenStreetMap tile service; the worker's
coordinates are used to choose map tiles and are therefore disclosed to that
tile provider. Dispatch assignment ingestion is not integrated. Its future
mapping must supply the existing location fields; agreeing and persisting a
separate location name requires a Dispatch/API contract change.

## Structure

```text
frontend/
  index.html
  package.json
  vite.config.js
  src/
    main.jsx
    App.jsx
    api/
      client.js
      errors.js
      tasks.js
    auth/
      session.js
    components/
      AppLayout.jsx
      BlockerSection.jsx
      Button.jsx
      CompletionSection.jsx
      EvidenceSection.jsx
      ErrorMessage.jsx
      InteractiveMap.jsx
      LoadingState.jsx
      LocationSection.jsx
      StatusBadge.jsx
    pages/
      NotFoundPage.jsx
      TaskDetailsPage.jsx
      TaskListPage.jsx
    styles/
      global.css
```

Routes are `/tasks`, `/tasks/:taskId`, and a not-found route; `/` redirects
to `/tasks`.

## Prerequisites and local startup

Install Node.js 20 LTS and npm, then from PowerShell:

```powershell
Set-Location C:\Users\sm237\Desktop\FieldWorkerExecutionTask\frontend
npm install
npm run dev
```

The Vite server binds to `127.0.0.1:3000` and uses strict port behavior. If
port 3000 is occupied, Vite exits rather than silently selecting a different
port. Open `http://127.0.0.1:3000`.

The production bundle can be generated with `npm run build`; preview it with
`npm run preview`. These commands describe the available local workflow and
do not indicate that the application or full workflow has been runtime
verified.

## API base URL

The API client reads `VITE_API_BASE_URL`. If it is unset or blank, it uses:

```text
http://127.0.0.1:8000/api/v1
```

Set a local override in the PowerShell process before starting Vite:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
npm run dev
```

Vite client variables are bundled into frontend code; configure only a
non-secret API URL there. The frontend does not configure a proxy. Backend
CORS currently allows `http://localhost:3000` and `http://127.0.0.1:3000`;
do not change the Vite origin without reviewing CORS.

## Development authentication

The backend currently uses development-only bearer authentication, maps the
configured demo token to one fixed worker ID, and has no login endpoint.
Production startup is refused until shared KAVACH authentication is
integrated.

For local development only, enter the worker demo token into the password
field in the frontend header and select **Save token**. It is stored in
`sessionStorage` for that browser tab and is attached to API requests only
when explicitly entered. It is not stored in source code or a Vite
environment variable. Clear the browser tab/session to remove it. Never
paste a production credential into this frontend or treat the demo token as
a production login.

## API client and current limitations

The client supports JSON requests and multipart bodies without setting a
multipart content type manually. It does not send an Authorization header
unless a development token has been explicitly configured. It handles
non-JSON responses without displaying their raw body, provides status-aware
messages for common API errors, preserves useful JSON `detail` messages,
redacts bearer/token-like text, and maps network failures to a safe message.
It does not log tokens or secrets.

The following documented backend gaps remain:

- Shared production authentication, worker identity mapping, and login are
  not available.
- There is no Dispatch assignment-ingestion endpoint. Tasks must already be
  present in the backend. A worker can accept/reject their own `ASSIGNED`
  task; that local decision does not implement Dispatch delivery,
  reassignment, or cancellation.
- The backend still exposes legacy checklist routes, task definition fields,
  and database tables for compatibility. The frontend no longer reads or
  updates checklist data, and checklist state is not a lifecycle prerequisite.
- Task access is limited to the primary assigned worker. Legacy checklist
  step owners do not receive cross-worker task access.
- Evidence upload returns internal `storage_key` and `sha256` fields, but
  the evidence history response omits them. `storage_key` is not a supported
  image URL. There is no image-byte retrieval endpoint.
- Browser GPS capture and location submission are implemented in the
  frontend. They require explicit worker action and browser geolocation
  permission. Production deployments must use HTTPS because browsers restrict
  geolocation to secure contexts; localhost is permitted for development.
  Workers must also enable Location/GPS in phone settings and allow the site
  in browser permissions. The website cannot turn phone location services on.
  Capture uses high-accuracy, uncached browser readings and rejects readings
  older than two minutes. It watches for improving fixes for up to 60 seconds
  and only enables submission when the best reading meets the server-provided
  accuracy threshold. The backend still validates separate location events
  and does not acquire device data or extract GPS EXIF metadata.
- The backend applies its configured `MAX_GPS_ACCURACY_METERS` threshold when
  saving a location event. The frontend displays the device-reported
  accuracy, distance from the assigned coordinates, and the backend's
  returned capture status. The API does not expose a task-proximity threshold;
  distance is informational, not a pass/fail test. Neither GPS nor proximity
  proves worker identity or physical presence.
- The task response exposes a completion-location event reference, but there
  is no location-event history read endpoint. After reload, the frontend
  cannot independently verify that referenced event's capture status.
- Unavailable/inaccurate location events may be recorded but do not satisfy
  task start or completion prerequisites. No GPS exception policy exists.
- Blocker reason-code discovery is available at
  `GET /api/v1/worker/blockers/reason-codes`, but the response supplies codes
  only, not labels. Empty/invalid configuration and missing production
  approval fail closed.
- Completion is recorded as `COMPLETION_SUBMITTED`. Verification
  acknowledgement, rejection/rework, reassignment, and resubmission are not
  integrated.
- The frontend does not integrate Dispatch assignment ingestion or
  Verification/approval workflows.

The frontend code provides task-list/details, lifecycle, evidence, GPS
location, blocker, and completion-submission surfaces. This implementation
status is not a claim that the application or complete end-to-end workflow
has been tested or verified.
