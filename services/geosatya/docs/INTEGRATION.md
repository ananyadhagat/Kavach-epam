# KAVACH integration: GeoSatya + Incident Intelligence + Dispatch + tracking, ETA, ETR

Status as of 30 Oct 2026. Working copy: `services/geosatya/` on branch `geosatya-location-verification`.

## 1. Sources inspected

| Source | What it actually contains |
|---|---|
| `geosatya-location-verification` (`e4e3e91`) | GeoSatya: FastAPI + SQLAlchemy/SQLite, vanilla-JS frontend, 110 passing tests. Reporting with photo + device GPS, EXIF, automatic task (fewest open tasks), server geofence PASS/FAIL/REVIEW_REQUIRED/NOT_CHECKED, supervisor review, audit. |
| `incident-intelligence-agent` (`e2ff0e9`; ZIP identical) | Separate FastAPI service (`src/kavach`). `POST /api/v1/incidents` (multipart, `X-Request-ID` idempotency) returns a `StructuredIncidentRecord`: category/type taxonomy, severity (LLM + deterministic Hindi/English safety floor), summary, facts, clarification questions, location consistency. LLM = Gemini or an explicit offline `mock` keyword stub. In-memory or PostgreSQL repository. Its CHANGES.md reports 130 passing tests (not re-run here). |
| `dispatch-work` (`6ef3bf9`; ZIP identical) | 4 files. `dispatch_task()` ranking (eligibility + 0.7 distance / 0.3 workload). `POST /api/v1/dispatch/assign` over a hard-coded in-memory list of 4 workers near Ujjain (23.18, 75.79), whose location timestamps are set at import time; empty `requirements.txt`; package file named `_init_.py`. |

## 2. Integration matrix

| Feature | Where it existed | Status before | Owner | Reused / adapted | What was added |
|---|---|---|---|---|---|
| Citizen report (photo + GPS + EXIF) | GeoSatya; also in Intelligence | Working in both | GeoSatya (stays the intake) | GeoSatya's kept unchanged | Optional `Idempotency-Key` |
| Classification / severity / summary | Intelligence | Working (Gemini or mock) | Intelligence agent | Called as-is over HTTP | Client, storage table, retry, UI card |
| Duplicate-detection handoff | Intelligence → Agent 2 | Draft contract | Intelligence | Untouched (happens inside the agent) | — |
| Worker ranking | Dispatch | Working function; unusable service data | Dispatch rules | Function reused (3 small documented changes) | Worker profiles from GeoSatya DB, fallback, escalation, manual assign, reassign |
| Assignment record | GeoSatya `tasks` (one per incident) | Working | GeoSatya | Kept; unique per incident = no duplicates | `dispatch_records` history |
| Worker location | Dispatch (fake, static) | Not real | GeoSatya | — | Check-in + task tracking feed it |
| Live tracking | none | Missing | GeoSatya | — | `location_pings`, endpoints, UI |
| ETA | none | Missing | GeoSatya | — | `services/estimates.py` |
| ETR + actual duration | none | Missing | GeoSatya | — | `task_progress`, estimates |
| Geofence verification | GeoSatya; Intelligence has a different "consistency" check | Working | GeoSatya | Unchanged; still uses the task's stored target | — |
| Supervisor review / audit | GeoSatya | Working | GeoSatya | Unchanged | New audit actions |
| Ratings | none | Missing, not in code | — | — | Not implemented (proposal §8) |

**Duplicates avoided.** Intelligence also has its own incident store, image validation and location check. GeoSatya does not copy them: it keeps its own record as the system of record and stores only the agent's output plus the agent's incident id (`external_incident_id`). No second incident, task, worker or status system was created.

## 3. Architecture

```
Browser (citizen / worker / supervisor)
   │  /api/v1 (demo header or bearer token)
   ▼
GeoSatya (FastAPI, :8000) ──HTTP──► Incident Intelligence agent (:8001, separate service)
   │  services/incidents.py   create → COMMIT → process_incident()
   │  services/intelligence.py   run_intelligence()  (never raises; status recorded)
   │  services/dispatch.py       dispatch_incident() → dispatch/ranking.py (Dispatch agent rules)
   │  services/tracking.py       pings, arrival, check-in, privacy
   │  services/estimates.py      ETA, ETR, actual durations
   │  services/tasks.py          start / completion (geofence) / review  → milestones
   ▼
SQLite (create_all; additive tables only)
```

Order matters: the report is **committed before** the agent is called, so an unavailable agent can never lose it. Dispatch then runs even if intelligence failed (priority `NORMAL`).

## 4. Contracts

**GeoSatya → Intelligence agent** (`geosatya/integrations/intelligence.py`)
- `POST {INTELLIGENCE_URL}/api/v1/incidents`, header `X-Request-ID: geosatya-<incident_id>` (stable → the agent returns the stored record on retry; a different payload → 409).
- Form: `complaint_text` = title + description (+ asset id); `selected_latitude/longitude` = GeoSatya's locked incident location; `device_*` only when the incident location is a user-selected pin and a device fix also exists; up to 4 report photos as `images`.
- Outcome mapping: 200/201 → `COMPLETED`; 409 → `CONFLICT`; 429/5xx (not 502)/timeout/connection error → `UNAVAILABLE`; 502 or other 4xx or non-JSON → `FAILED`. Not configured → `NOT_CONFIGURED`.
- Stored: category, incident_type, severity, severity reason and rule matches, summary, clarification questions, missing information, location-check status, prompt version, the agent's incident id, attempts, last error, times.
- Priority = severity (`HIGH`/`MEDIUM`/`LOW`), otherwise `NORMAL`. The citizen's own category is **not** overwritten; the agent's classification is shown to supervisors as a separate, system-generated suggestion.

**Dispatch ranking** (`geosatya/dispatch/ranking.py`, from `dispatch-work/app/dispatch.py`)
- Unchanged: eligibility reasons, 0.70·distance/radius + 0.30·active/max, ascending, worker id tie-break, haversine.
- Changed (documented in the file): (1) worker with no location → "Location unavailable" instead of a crash; (2) 900 s freshness is a parameter with the same default; (3) `now` injectable for tests.
- Inputs from GeoSatya: `worker_profiles` (skills, equipment, availability, max tasks), open-task counts, last shared location; category → required skills/equipment/work minutes in `categories.json`.
- No candidate: `DISPATCH_FALLBACK=workload` picks the least-loaded worker among those whose **only** failures are location-related, labelled `WORKLOAD_FALLBACK` ("distance not considered"); `escalate` leaves the incident `SUBMITTED` with an `UNASSIGNED` dispatch record for a supervisor.
- Idempotent: `tasks.incident_id` is unique, `dispatch_incident()` returns the existing task, `assign` refuses if a task exists.

## 5. Status mapping (no new status enums)

| Conceptual state | GeoSatya representation |
|---|---|
| Reported / unassigned | incident `SUBMITTED`, dispatch record `UNASSIGNED` |
| Assigned | task `ASSIGNED` (`assigned_at`) |
| Accepted | **not supported**: there is no accept step |
| En route | task `ASSIGNED` + `task_progress.tracking_started_at`, tracking active |
| Arrived | `task_progress.arrived_at` (estimated within `ARRIVAL_RADIUS_M`, accuracy ≤ 50 m) |
| Work in progress | task `IN_PROGRESS` (`work_started_at`) |
| Completion submitted / verification pending / supervisor review | task `AWAITING_VERIFICATION` (`completion_submitted_at`); the geofence check is synchronous |
| Resolved | task `RESOLVED` (`resolved_at` = review time) |
| Rejected / more evidence | back to `ASSIGNED`, attempt + 1 (existing behaviour) |
| Reassigned | same task, new worker, `ASSIGNED`; incident `IN_PROGRESS → ASSIGNED` is now an allowed, audited transition |
| Cancelled | **not supported** |

## 6. Tracking, ETA, ETR

- **Who can share:** only the assigned worker, for their own `ASSIGNED`/`IN_PROGRESS` task. Coordinates and accuracy are validated on the server; simulated positions are refused in production.
- **Who can see:** reporter (latest position only while sharing is active), assigned worker, supervisor (also last-known and the recent points). Everyone else gets 404.
- **Retention:** at most `TRACKING_HISTORY_KEEP` points per task; all deleted on completion submission or reassignment.
- **Throttling:** updates closer than `TRACKING_MIN_INTERVAL_S` are acknowledged but not stored; the client sends at most every 10 s, and viewers poll every 15 s while the tab is visible.
- **States:** `NOT_STARTED`, `LIVE`, `STALE` (> `TRACKING_STALE_S`), `STOPPED`, `ENDED`; the location is labelled `CURRENT` or `LAST_KNOWN`.
- **ETA:** straight-line remaining distance × `ETA_ROUTE_FACTOR` ÷ speed. The speed is the observed approach speed (distance drop over ≥ 60 s within 10 min, 0.5–20 m/s), else `ETA_ASSUMED_SPEED_KMH`. Shown as a minute range (×0.8 … ×1.3). States: `WAITING_FOR_LOCATION`, `AVAILABLE`, `STALE`, `ARRIVED`, `NOT_APPLICABLE`. Always `APPROXIMATE_STRAIGHT_LINE`, never road routing.
- **ETR:** recomputed only on events (`ASSIGNED`, `FIRST_LOCATION`, `ARRIVED`, `WORK_STARTED`, `COMPLETION_SUBMITTED`, `REWORK`, `REASSIGNED`, `RESOLVED`). It is travel (ETA upper bound, or `ETR_DEFAULT_TRAVEL_MIN` when the location is unknown) + work (median of ≥ 3 resolved jobs in the category, else the category baseline) + `ETR_REVIEW_BUFFER_MIN`. It is shown as approximate with its basis, and `OVERDUE` when passed.
- **Actual resolution:** from recorded timestamps only. It covers report → resolved, plus to-assignment, travel (tracking start → arrival), work (start → submission) and review (submission → approval). Missing milestones stay empty.

## 7. Decisions taken (please confirm with the team)

1. GeoSatya stays the citizen intake and system of record; the intelligence agent is called as a service, not merged (merging the branch would collide at the repo root).
2. The dispatch branch's HTTP service and in-memory workers are not used; only its ranking rules are.
3. The default `DISPATCH_FALLBACK=workload` keeps the demo usable when nobody has shared a location. Set `escalate` to follow the Dispatch agent's "escalate to supervisor" rule strictly.
4. A worker check-in shares **one** location for dispatch; continuous tracking happens only during an assigned task.
5. Ratings were not implemented (§8).

## 8. Proposal: resolution rating (not implemented)

There is no rating anywhere in the inspected code. A minimal compatible version would be a `resolution_ratings` table (incident_id PK, citizen_id, stars 1–5, optional comment ≤ 500 chars, created_at). A single `POST /incidents/{id}/rating` would be open to the reporting citizen only, once, after `RESOLVED`, and the result would be shown to supervisors. It needs one decision from the team: whether a low rating should reopen the job or only be reported.

## 9. Known issues found in partner branches (not changed here)

- `incident-intelligence-agent`: `config.py` imports `dotenv`, but `python-dotenv` is not in `requirements.txt`.
- `dispatch-work`: `requirements.txt` is empty, `app/_init_.py` should be `__init__.py`, and the worker list is static in memory. Its timestamps are taken at import, so every worker becomes "Location is stale" 15 minutes after start-up.
