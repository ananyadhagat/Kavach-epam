# GeoSatya: Location-Verified Civic Reporting

GeoSatya is the geolocation module of **KAVACH**. It makes sure a civic incident is reported with photo and device-location evidence, and that a field worker's completion is accepted only when their reported position is inside a permitted radius of the place the incident was reported.

It lives in `services/geosatya/` and is the integration point for three KAVACH pieces: it sends each saved report to the **Incident Intelligence** agent (a separate service) for classification and severity, it assigns workers with the **Dispatch** agent's ranking rules, and it adds **live worker tracking, ETA and ETR**. The full integration design, feature matrix and status mapping are in [docs/INTEGRATION.md](docs/INTEGRATION.md).

```
Citizen report → saved → Incident Intelligence (priority) → Dispatch (worker) → worker shares location
→ ETA (arrival) + ETR (resolution) → completion photo → server geofence check → supervisor review → resolved
```

---

## 1. Project overview

A citizen photographs a civic problem; the browser attaches their device location at the moment of capture. The report becomes a field task automatically. When a worker submits completion evidence, the **server** recalculates the distance to the original location and returns an explainable result. A supervisor makes the final decision. Every location source is kept separately with its provenance, and no coordinate is ever invented.

## 2. Problem statement and objectives

Civic complaints are easy to file but hard to trust: a photo alone doesn't show *where* it was taken, and a worker can mark a job done without being at the site. GeoSatya's objectives:

- Bind each report's **photo and location** together at capture time.
- Lock the reported location so field work is measured against it.
- Verify worker completion against a **configurable geofence**, on the server.
- Be honest about uncertainty: weak GPS, missing location, conflicting sources and simulated coordinates are all reported, never hidden.
- Keep a human (the supervisor) as the decision-maker.

> **What location can and cannot show.** GPS and browser location show that a position is *consistent* with a place. They do **not** prove a person was physically there, and GPS proximity alone does **not** prove the identity of a particular physical asset (two potholes a few metres apart look the same to GPS). A `PASS` means "the reported position is consistent with the incident", nothing more.

## 3. Key features

- **Citizen reporting** with category, description, photo and automatic device location.
- **Incident Intelligence** (optional service): category/type suggestion, severity with safety-rule floor, summary and clarification questions, stored apart from the citizen's own words. If the agent is off or failing, the report is still saved and dispatched (priority NORMAL) and can be re-analysed later.
- **Dispatch** using the Dispatch agent's rules (skills, availability, capacity, fresh location within the radius; 70% distance + 30% workload). If nobody qualified has shared a recent location, a labelled workload fallback (or escalation to a supervisor, configurable). Supervisors can assign or reassign.
- **Live worker tracking** for an assigned task: the worker shares their location while travelling; the citizen and supervisor see the latest position, its age, and whether it is live or stale. Arrival is estimated from shared locations.
- **ETA** (approximate arrival range) and **ETR** (estimated resolution time, recalculated only on events), plus the **actual resolution time** from recorded timestamps.
- **Locked incident location** the worker cannot change; supervisors may correct it with an audited reason, keeping the original.
- **Server-side geofence check** returning `PASS` / `FAIL` / `REVIEW_REQUIRED` / `NOT_CHECKED`.
- **Configurable radius** (10–20 m, default 15 m) and GPS-accuracy limit (default ±25 m).
- **EXIF GPS extraction** and image validation.
- **Supervisor review**: approve, reject or request more evidence, with reasons for overrides.
- **Audit trail** of status changes, checks, decisions and corrections.

## 4. Citizen reporting workflow

1. Choose a category and write a short title and description.
2. **Take a photo.** The in-app camera (or phone camera, or an existing file) captures the image, and the browser reads the device location at the same moment.
3. The device location is stored with the photo. Four timestamps are kept **separately**:
   - image capture time (device clock, in-app camera only),
   - location reading time (the GPS fix's own timestamp),
   - upload time (device clock when sent),
   - server receipt time (trusted).
4. If location can't be obtained, a clear message and **Retry** appear. The citizen can instead pick the spot on a map; that is labelled **user-selected, not verified GPS**.
5. Submit. The report gets one reference ID, for example `GS-T4E42E`.

**Captured device location vs. upload-time location.** A photo taken through the in-app camera carries the location read at capture. A photo *uploaded from the gallery* has no known capture location: the device location recorded is where the user is at upload time, not where the photo was taken. The app flags gallery photos and never treats the two as equivalent. A photo's own EXIF GPS, when present, is read and compared but never trusted on its own.

## 5. Worker task-completion workflow

1. A new report is analysed (if the intelligence agent is configured) and dispatched to a worker, using the citizen's original location as the target.
2. The worker may press **Share my location while travelling**; the citizen and supervisor then see an approximate ETA. Sharing stops when the worker stops it, leaves the page, or submits the completion.
3. The worker opens the task and presses **Start work**.
3. At the site, the worker takes a completion photo; the device location is read at the same time.
4. On submit, the **server** computes the distance (Haversine) from the reported position to the **original** incident location and applies the geofence rule.
5. `FAIL` and `NOT_CHECKED` attempts are recorded but **not accepted**: the task stays in progress and the worker can move and retry. `PASS` and `REVIEW_REQUIRED` attempts go to the supervisor.

The worker cannot change the target location, and the request cannot override it: extra fields are rejected and the distance is always measured against the stored target.

## 6. Location verification and geofence logic

The rule lives in `geosatya/location/geofence.py` and is pure (no I/O), so it is directly unit-tested. For a reported position at distance *d* with accuracy *a*, radius *R* and accuracy limit *A*:

| Result | Condition |
|---|---|
| `NOT_CHECKED` | no target coordinates, or no usable location (permission denied, timeout, unavailable, unsupported) |
| `FAIL` | `d − (a or A) > R` — clearly outside even allowing for GPS error |
| `REVIEW_REQUIRED` | inside, but: accuracy missing or `a > A`; at the boundary; photo EXIF GPS conflicts with the device or incident; a gallery photo whose location is unverified; a duplicate photo; or a simulated location that may not pass |
| `PASS` | inside `R` with acceptable accuracy and no conflicts |

Distance is **always recalculated on the server**; a distance sent by the client is never trusted (unknown fields are rejected).

**Insufficient accuracy or conflicting evidence.** A reading weaker than the accuracy limit (for example ±80 m while 10 m away) is `REVIEW_REQUIRED`, not a pass — the position cannot be established. When the photo's EXIF GPS disagrees with the device location or the incident, the result is `REVIEW_REQUIRED` with a `SOURCE_CONFLICT` reason code. Missing location is `NOT_CHECKED`; it is never replaced with the target coordinates or any default.

**Simulated GPS is demonstration-only.** For machines without GPS, a "Simulate GPS (demo)" switch provides labelled test coordinates. They are always marked `SIMULATED`, are refused entirely when `APP_ENV=production`, and can only produce a `PASS` in development mode. They must never be represented as genuine location evidence.

## 7. EXIF GPS and image validation

- **Validation** (`geosatya/media/image_checks.py`): uploads are decoded to confirm they are real JPEG/PNG/WebP images (not by extension), size-capped (8 MB) and pixel-capped, then hashed (SHA-256 and a perceptual hash). Files are stored under server-generated names in a private folder and served only through an access-checked route.
- **EXIF GPS** (`geosatya/location/exif_gps.py`, Pillow): latitude/longitude are read from the GPS IFD, converted from degrees-minutes-seconds with N/S/E/W signs, and validated. The claimed capture time is read too. Missing, malformed or unreadable metadata is recorded (`NO_EXIF`, `NO_GPS`, `GPS_INVALID`, `UNREADABLE`) and is **not** held against the submission — many legitimate photos have no GPS metadata. EXIF is stored as a separate evidence source and never overwrites the device fix.

## 8. Supervisor review workflow

- The **verification queue** lists accepted completions (`PASS` and `REVIEW_REQUIRED`).
- A review page shows both photos, the map with the incident location, the worker's position, the allowed radius, the distance, the GPS accuracy and the reason codes.
- The supervisor can **approve**, **reject** or **request more evidence**. Approving a result the checks did not pass, or rejecting one they did, is an override and requires a reason; rejection and request-more-evidence always require one.
- Approve resolves the incident; reject and request-more-evidence send it back to the worker as a new attempt.
- A supervisor can **correct the task's target location** with a reason. The citizen's original coordinates are kept, and the correction is audited.

## 9. Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 (tested with 3.13.5) |
| API | FastAPI, Pydantic 2, pydantic-settings, Uvicorn |
| Database | SQLAlchemy 2 with SQLite (default); any SQLAlchemy URL can be configured |
| Images | Pillow (format checks, hashing, EXIF GPS) |
| Frontend | Plain JavaScript ES modules, HTML, CSS — no build step, no npm |
| Maps | Leaflet with OpenStreetMap tiles (default); Google Maps JavaScript API optional |
| Tests | pytest |

GeoSatya itself uses no AI. Classification and severity come from the separate Incident Intelligence agent (Gemini, or its explicit offline `mock` mode), called over HTTP with `httpx`. Distance, geofence, dispatch ranking, ETA and ETR are deterministic code.

## 10. Architecture and folder structure

```
services/geosatya/
├── geosatya/                      Python backend (FastAPI)
│   ├── main.py                    application factory; also serves the frontend
│   ├── config.py                  settings from environment variables
│   ├── models.py                  SQLAlchemy tables
│   ├── db.py                      engine and schema creation
│   ├── categories.py              loads data/categories.json
│   ├── data/categories.json       incident categories and worker steps
│   ├── location/
│   │   ├── geofence.py            PASS / FAIL / REVIEW_REQUIRED / NOT_CHECKED rule (pure)
│   │   ├── coordinates.py         validation and Haversine distance
│   │   └── exif_gps.py            GPS and capture time from photo metadata
│   ├── media/                     image validation, hashing, private storage
│   ├── dispatch/ranking.py        worker ranking reused from the dispatch-work branch
│   ├── integrations/intelligence.py  HTTP client for the Incident Intelligence agent
│   ├── services/                  reporting, intelligence, dispatch, tracking, estimates (ETA/ETR), tasks, review
│   ├── api/                       routes, request contracts, access rules, response shapes
│   ├── seed.py                    demo users + one labelled demo incident
│   └── synthetic_images.py        generated test photos (labelled SYNTHETIC)
├── frontend/                      static web app
│   ├── index.html, styles.css, config.js
│   └── js/                        app shell, pages, camera + location capture, map adapter,
│                                  live.js (progress, ETA/ETR, tracking, intelligence + dispatch panels)
├── docs/                          integration design, handoff, JSON report, PDF report
├── tests/                         pytest suite (139 tests)
├── scripts/make_demo_images.py    writes sample photos for manual upload
├── requirements.txt
├── pytest.ini
├── .env.example                   placeholder settings only
└── .gitignore
```

## 11. Prerequisites

- Python 3.11 or newer (developed and tested on 3.13).
- A modern browser (Chrome or Edge) for the location and camera features.
- No database server, API key or npm toolchain is required for local use.

## 12. Installation and local setup (Windows, VS Code)

From a PowerShell terminal in VS Code:

```powershell
cd services\geosatya
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env    # optional; defaults work without it
```

If PowerShell blocks `Activate.ps1`, either run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or call the venv Python directly (`\.venv\Scripts\python -m uvicorn ...`).

## 13. Environment variable configuration

All optional; set them in `.env`, which must never be committed. See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` or `production`. Production refuses demo sign-in and simulated GPS. |
| `AUTH_MODE` | `demo` | `demo` = seeded demo roles, no sign-in. `token` = bearer tokens from `AUTH_TOKENS`. |
| `AUTH_TOKENS` | empty | Token mode only: `token:user_id` pairs. Never commit real tokens. |
| `DATABASE_URL` | `sqlite:///data/geosatya_v3.db` | Database location (any SQLAlchemy URL). |
| `STORAGE_DIR` | `private_uploads/` | Private photo storage; served only through an access-checked route. |
| `GEOFENCE_RADIUS_M` | `15` | Starting radius; allowed 10–20 m; supervisors can change it in Settings. |
| `MAX_ACCURACY_M` | `25` | Readings weaker than this never pass; allowed 10–100 m. |
| `EXIF_TOLERANCE_M` | `50` | Photo GPS further than this from the device/incident is a conflict. |
| `LOCATION_FRESHNESS_S` | `30` | A location reading older than this at photo time is refreshed first. |
| `SIMULATED_CAN_PASS` | unset | Whether simulated GPS may pass. Unset = development only; production always refuses it. |
| `GOOGLE_MAPS_BROWSER_KEY` | empty | Optional. Google Maps when set, OpenStreetMap otherwise. A browser key is visible to users by design — restrict it in Google Cloud. |
| `SEED_DEMO_DATA` | `true` | Creates demo users and one labelled demo incident on first start. |
| `CORS_ORIGINS` | empty | Only needed if the frontend is hosted on another origin. |
| `INTELLIGENCE_URL` | empty | Incident Intelligence agent base URL, e.g. `http://127.0.0.1:8001`. Empty = not configured (reports still accepted). |
| `INTELLIGENCE_TIMEOUT_S` | `8` | Per-call timeout; a slow agent never blocks the report. |
| `DISPATCH_MAX_RADIUS_KM` | `2` | Dispatch radius (the Dispatch agent's default). |
| `DISPATCH_LOCATION_MAX_AGE_S` | `900` | A worker location older than this is stale for dispatch (Dispatch agent's 15 min rule). |
| `DISPATCH_FALLBACK` | `workload` | `workload` = labelled least-loaded fallback when nobody qualified shared a location; `escalate` = leave it for a supervisor. |
| `TRACKING_MIN_INTERVAL_S` | `10` | Location updates closer together are ignored (not stored). |
| `TRACKING_STALE_S` | `120` | After this, the last location is shown as stale. |
| `TRACKING_HISTORY_KEEP` | `20` | Recent points kept per task; all deleted when field work ends. |
| `ARRIVAL_RADIUS_M` | `50` | Arrival is estimated inside this distance (not the geofence). |
| `ETA_ASSUMED_SPEED_KMH` | `20` | Speed used when no approach speed can be observed. |
| `ETA_ROUTE_FACTOR` | `1.4` | Straight line → road distance allowance (no routing service). |
| `ETR_DEFAULT_TRAVEL_MIN` | `30` | Travel allowance when the worker's location is unknown. |
| `ETR_REVIEW_BUFFER_MIN` | `30` | Allowance for supervisor review. |
| `ETR_HISTORY_MIN_SAMPLES` | `3` | Resolved jobs per category needed before the historical median replaces the baseline. |

## 14. Running the backend and frontend

The backend also serves the frontend, so one command runs both:

```powershell
uvicorn geosatya.main:create_app --factory --reload
```

Open **http://localhost:8000**. There is no sign-in screen; pick a demo role (citizen, field worker, supervisor) in the top bar.

### Optional: run with the Incident Intelligence agent (two terminals)

The agent is on the `incident-intelligence-agent` branch. Check it out into a separate folder (this does not touch your GeoSatya checkout), and run it on **port 8001** in its offline `mock` mode (no Gemini key needed):

```powershell
git -C <team-repo> worktree add ..\kavach-intelligence origin/incident-intelligence-agent
cd ..\kavach-intelligence
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt python-dotenv
$env:KAVACH_LLM_MODE = "mock"
.\.venv\Scripts\python -m uvicorn kavach.main:app --app-dir src --port 8001
```

(`python-dotenv` is imported by the agent but missing from its `requirements.txt`; `tzdata` is required on Windows and is listed.) Then start GeoSatya with `INTELLIGENCE_URL=http://127.0.0.1:8001` in `.env` (or `$env:INTELLIGENCE_URL=...`). Health checks: http://127.0.0.1:8001/health and http://localhost:8000/health. If port 8000 or 8001 is busy, pass another `--port` and update `INTELLIGENCE_URL`.

With `KAVACH_LLM_MODE=mock` the agent's classifier is a keyword stub, labelled "development only" by its authors. Real classification needs `KAVACH_LLM_MODE=gemini` and a `GEMINI_API_KEY` in the agent's own `.env` (a paid Google API; none is configured here).

- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

**Browser location & camera** work only on a secure context (`https://` or `http://localhost`). On first use, allow the location (and camera) permission. If blocked, open the site settings via the lock/tune icon by the address bar, set Location (and Camera) to Allow, and press Retry. On a phone, plain `http://192.168.x.x` will not work — use HTTPS. Without GPS, use the **Simulate GPS (demo)** switch (always labelled, demo-only).

## 15. API endpoints

All under `/api/v1` except `/health`. Access is role-based: citizens see their own reports, field workers their assigned tasks, supervisors everything. Identify the caller with `X-GeoSatya-Demo-User: <id>` (demo mode) or `Authorization: Bearer <token>` (token mode).

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/health` | anyone | service status |
| GET | `/config` | anyone | map provider, limits, simulation status |
| GET | `/categories` | anyone | categories and worker steps |
| GET | `/demo/users` | anyone (demo only) | seeded demo identities |
| GET | `/me` | signed in | current user |
| GET | `/dashboard` | signed in | counts and recent items for the caller's role |
| GET | `/settings` | signed in | current radius and accuracy limit |
| PUT | `/settings` | supervisor | change the radius and accuracy limit |
| POST | `/incidents` | citizen | create a report (multipart: `payload` JSON + photos) |
| GET | `/incidents` | any role, filtered | reports the caller may see |
| GET | `/incidents/{incident_id}` | reporter / assigned worker / supervisor | detail: location, photos, attempts, timeline |
| POST | `/incidents/{incident_id}/correct-location` | supervisor | correct the task target (reason required; original kept) |
| GET | `/tasks` | worker, supervisor | task list |
| GET | `/tasks/{task_id}` | assigned worker, supervisor | task detail |
| POST | `/tasks/{task_id}/start` | assigned worker | start work |
| POST | `/tasks/{task_id}/completion` | assigned worker | submit completion photo and location (multipart) |
| GET | `/verification-queue` | supervisor | accepted completions and their status |
| GET | `/completions/{completion_id}` | supervisor | one completion with its checks and photo |
| POST | `/completions/{completion_id}/review` | supervisor | approve / reject / request more evidence |
| GET | `/evidence-history` | supervisor | audit events (coordinates are never written here) |
| GET | `/media/{media_id}` | permitted users only | a stored photo |
| POST | `/demo/reset` | supervisor (demo only) | rebuild the demo database |
| POST | `/incidents` + `Idempotency-Key` header | citizen | optional: a retried submission with the same key returns the first report |
| POST | `/incidents/{id}/intelligence/retry` | supervisor | re-run Incident Intelligence (same request id; never duplicates) |
| POST | `/incidents/{id}/dispatch/retry` | supervisor | re-run Dispatch for an unassigned incident (never creates a second task) |
| POST | `/incidents/{id}/assign` | supervisor | assign an unassigned incident to a worker |
| POST | `/tasks/{task_id}/reassign` | supervisor | move an active task to another worker (reason required) |
| GET | `/incidents/{id}/tracking` | reporter / assigned worker / supervisor | latest worker location (citizen: only while live), ETA, ETR |
| GET | `/tasks/{task_id}/tracking` | assigned worker, supervisor | same, by task (supervisor also gets recent history) |
| POST | `/tasks/{task_id}/location` | assigned worker | share current location (active task only) |
| POST | `/tasks/{task_id}/tracking/stop` | assigned worker | stop sharing |
| GET | `/workers` | supervisor | workers' skills, load, availability, location freshness |
| GET | `/workers/me` | worker | own availability and dispatch profile |
| POST | `/workers/me/check-in` | worker | set availability; optionally share one location for dispatch |

`GET /incidents/{id}` now also returns `progress` (milestone times and ETR) and `intelligence` (status and priority for everyone; full output for supervisors), and `dispatch` for supervisors.

## 16. Database and storage behavior

- **Database:** SQLite by default, in `data/`. Tables are created automatically at start-up (SQLAlchemy `create_all`); there are no migrations. Any SQLAlchemy URL (e.g. PostgreSQL) can be set via `DATABASE_URL`.
- **Integration schema change (additive only):** new tables `incident_intelligence`, `worker_profiles`, `dispatch_records`, `task_progress`, `location_pings`, `request_keys`. No existing table or column changed, so an existing `geosatya_v3.db` gains them on the next start and keeps its data. Tasks created before this change get a `task_progress` row on first use; existing workers get a profile with no skills (demo workers get demo skills).
- **Photos:** stored under `STORAGE_DIR` (default `private_uploads/`) with random server-generated filenames, never as public files; a stored photo is returned only to a permitted user through `/media/{id}`.
- **Location evidence:** each source (device GPS, photo EXIF, user-selected pin, supervisor correction) is its own record with provenance; sources never overwrite one another.
- `data/`, `private_uploads/`, `demo_images/` and `.venv/` are git-ignored.

## 17. How to run automated tests

From `services/geosatya/` with the virtual environment active:

```powershell
pytest
```

**Actual result on this copy:** `139 passed, 1 warning` (110 original + 29 integration tests in `tests/test_integration.py`: intelligence success, unavailable/timeout/502/409/invalid-JSON, retry with the same request id; dispatch ranking rules, unavailable workers, workload fallback, escalation, manual assign, retry without duplicates, idempotent report submission; tracking authorization and privacy, invalid/NaN coordinates, throttling, ETA states and observed speed, stale locations, arrival vs. geofence, history limit and purge, reassignment; ETR on events, historical median, rework, actual resolution time; pre-existing tasks without progress rows).

Before the integration: `110 passed, 1 warning`. The warning is a deprecation notice from a dependency (Starlette's test client), not a failure. The suite covers the geofence rule (valid/invalid/NaN/infinite coordinates, inside/outside radius, poor/missing accuracy, boundary, denied/timed-out/unavailable location, EXIF conflicts, gallery and duplicate photos, simulated locations, configurable radius); EXIF and image validation (N/S/E/W references, missing/malformed/oversized/unsupported files, storage-key safety); and the full HTTP workflow (report → automatic task → worker inside/outside the radius → retries → missing evidence → supervisor approve/reject/request-more with reasons → the SUBMITTED → ASSIGNED → IN_PROGRESS → AWAITING_VERIFICATION → RESOLVED lifecycle → location correction with audit → role/access checks, token mode, and production refusing demo mode and simulation).

## 18. Demo data and demonstration

`SEED_DEMO_DATA=true` creates demo users (citizens, workers, a supervisor) and one clearly **labelled synthetic** incident whose location is marked `SIMULATED`. A suggested demonstration:

1. **Citizen:** *Report an Incident* → *Pothole / Road Damage* → title and description → **Take photo** → **Next** → **Submit**; note the reference ID.
2. **Field worker** (the one shown as assigned): *Worker Tasks* → open the task → **Start work**.
3. Without GPS, choose *Simulate: 45 m away* → **Take completion photo** → describe the work → **Submit** → *Not accepted: outside the permitted radius*.
4. Choose *At the spot* → retake → **Submit** → *Verified on site*.
5. **Supervisor:** *Verification Queue* → open the item → review the map, distance, accuracy and both photos → **Approve**.
6. **Citizen:** *My Reports* now shows *Resolved*.

**Integrated demo (live tracking, ETA, ETR).** Turn on *Simulate GPS (demo)*.
1. **Field worker (Meena):** Dashboard → *Share my location once (simulated)* so Dispatch can use distance.
2. **Citizen:** report an issue. On the report page, *Live progress* shows *Assigned* and an ETR.
3. **Supervisor:** open the report: the *Incident Intelligence* card (if the agent runs) and the *Dispatch* card with the ranking.
4. **Assigned worker:** open the task → *Share location (simulated travel)*. Every 10 s the simulated position moves ~100 m closer.
5. **Citizen or supervisor:** the page refreshes every 15 s with the ETA range, the distance and the live/stale state; *Arrived* appears within 50 m.
6. **Worker:** *Start work* → completion photo at the spot → submit. Sharing stops and its points are deleted.
7. **Supervisor:** approve. The citizen sees *Resolved in …* with the actual durations.

`scripts/make_demo_images.py` writes sample photos (some with EXIF GPS) to `demo_images/` for manual upload.

## 19. Security and privacy considerations

- **Access control:** citizens see only their own reports; workers only their assigned tasks; supervisors everything. Photos are served only to permitted users.
- **No secrets in the repo:** `.env`, the database, uploaded photos and generated images are git-ignored; `.env.example` holds placeholders only.
- **Input safety:** images are validated by decoding; coordinates are range- and finiteness-checked (NaN/Infinity rejected); unknown request fields are rejected.
- **Honest provenance:** device vs. upload-time location, and real vs. simulated GPS, are always distinguished in the UI and the data.
- **Audit:** supervisor decisions and location corrections are recorded with reasons; coordinates are never written to the audit log.
- **Not production-ready auth:** demo roles are not authentication, and token mode is a stand-in for a real identity provider (`get_actor` in `geosatya/api/deps.py`).

## 20. Current limitations and future improvements

- Browser GPS can be spoofed; EXIF and device clocks are client-reported. A `PASS` means consistency, not proof of presence.
- GPS proximity does not identify a specific asset; the supervisor confirms the photo shows the right issue.
- SQLite with auto-created tables and local photo storage: fine for a prototype, not production. A real deployment needs PostgreSQL, migrations and private object storage.
- Dispatch uses distance only when workers have shared a location in the last 15 minutes; otherwise the labelled workload fallback is used and "nearest" is not claimed. Worker skills come from `worker_profiles` (demo workers are seeded; others need their skills set; there is no admin screen for it yet).
- ETA is approximate: straight-line distance × 1.4 at an observed or assumed speed. No road-routing service is configured (a routing provider such as OSRM or Google Directions would be a new dependency; Google needs billing).
- A web page cannot track in the background: sharing stops when the page is closed, the device sleeps, goes offline or permission is revoked. The UI shows this as stale. A native app would be needed for background tracking.
- ETR uses category baselines in `categories.json` until 3 jobs per category are resolved; the baselines are placeholders, not measured data.
- There is no "accept" step and no "cancelled" status; reassignment is supported. Ratings are not implemented (see docs/INTEGRATION.md for a proposal).
- No notifications (status is shown in the app only); single-instance design with no locking for simultaneous decisions on one task.
- Not tested on a real phone camera/GPS, or with Google Maps (no key); browser testing used simulated GPS and a test video stream.

## Integration with other KAVACH agents

**Integrated now** (details in [docs/INTEGRATION.md](docs/INTEGRATION.md)):

- **Incident Intelligence** (`incident-intelligence-agent`): called over HTTP after each report is saved; its output is stored in `incident_intelligence` and its severity becomes the dispatch priority.
- **Dispatch** (`dispatch-work`): its ranking function is reused in `geosatya/dispatch/ranking.py` with GeoSatya's workers. The branch's own HTTP service is not called: its workers are hard-coded in memory near Ujjain and go stale 15 minutes after start-up, so it could never assign a GeoSatya incident.

**Still separate**, for the team to decide:
- **Field Worker** (`Field-worker-agent`) also stores worker evidence and GPS (PostgreSQL + Alembic); merging means one database and migrations.
- **Verification** (`verification-agent`) has its own GPS/Haversine checks; its outcomes (`PASS`/`FAIL`/`INCONCLUSIVE`/`MANUAL_REVIEW`) differ from GeoSatya's and would need mapping.
- **Duplicate Detection** could take GeoSatya's reports as input; GeoSatya itself does not detect duplicates.

A sensible first step is to agree a shared incident ID and category vocabulary, then decide which module owns the citizen report and which owns the worker verdict.
