# KAVACH integration — checkpoint

Branch: `kavach-unified` (local, cut from `geosatya-location-verification`). **Nothing committed or pushed.**
Teammate branches were only read. DB backup before this work: `data/backups/geosatya_v3-before-kavach-*.db`.

## Run
```
cd D:\Desktop\Kavach-epam-team\services\geosatya
D:\Desktop\Kavach-epam\.venv\Scripts\python.exe -m uvicorn geosatya.main:create_app --factory --port 8000
```
Open http://localhost:8000 → "Sign in / Register" → pick an identity (development access, no passwords).
Tests: `python -m pytest -q` → 211 passed (190 original GeoSatya + 21 KAVACH).

## Done (stages 1–8 first pass)
- Tenancy: nullable `workspace_id` on users/incidents; `platform_role` (ORG_ADMIN / EVENT_ORGANIZER / PLATFORM_ADMIN act as SUPERVISOR inside their own workspace only). All GeoSatya supervisor queries scoped server-side (`geosatya/scope.py`, `api/deps.py`, `api/routes.py`, `services/board.py`, `services/dispatch.py`). Workspace None = original civic scope, unchanged.
- Platform-wide verification limits + demo reset: civic supervisors only.
- New tables `geosatya/platform_models.py`: workspaces, departments, zones, invites, plans (no prices), authorities.
- API `geosatya/kavach/api.py` (`/api/v1/kavach/...`): registration (dev only), events, members, invites/join, departments, zones, settings, workspace reports, photo-free public reports + authority suggestion/routing, public track/stats (aggregates only), platform admin, manual-forwarding record.
- `create_incident(require_photo=False)` only for the new channels; GeoSatya's own `/incidents` still requires a photo.
- Event incident categories added to `data/categories.json` (scope: event).
- Frontend: Kavach logo (`icons/kavach-mark.svg`), green palette (styles.css tokens), `kavach.css`, public site + workspaces in `js/kavach/*`, router `js/app.js`. GeoSatya pages reused (incident, tasks, live map, board, review, history, settings).

## Team agents (done)
- Copied unchanged into `services/agents/<name>/` (each has ORIGIN.md: developer, branch, commit). Branches untouched.
- Start them: `services/agents/start-agents.ps1` (ports 8001–8004, offline modes). URLs go in `services/geosatya/.env` (git-ignored).
- Pipeline after every report (`geosatya/kavach/agents.py`): Intelligence → Duplicate Detection (public reports only) → Supervisor → Sanitation (waste incidents only). Results stored in `kavach_agent_runs`, shown on incident → Dispatch & AI → Team agents; retry button. Advisory: never changes GeoSatya's report, verification or dispatch.
- Verified live: two similar reports → DUPLICATE (score 0.98). Intelligence mock gives severity UNKNOWN for some text → Supervisor NEEDS_REVIEW → Sanitation holds the plan (their rules; not overridden).
- Tests: `tests/test_team_agents.py` (11). Full suite 222 passed.

## Verification agent (done)
- `services/agents/verification/` (unchanged copy) runs in-process via `geosatya/integrations/verification.py`: its three repository interfaces are backed by GeoSatya (task target + geofence radius, report photo = before, completion photo = after, completion device fix; SIMULATED fix never passed as GPS). Runs after each completion with a photo; result in `kavach_agent_runs` (agent VERIFICATION); shown on the review screen and incident Team agents card.
- `VERIFICATION_AGENT=off|mock|gemini` (default mock). Mock = real OpenCV quality/alignment + GPS check, no AI vision → INCONCLUSIVE, never a made-up PASS. Needs `opencv-python-headless`, `numpy` (added to requirements.txt). Audit DB: `data/verification_audit.db`.
- Tests: `tests/test_verification_agent.py` (8). Full suite 230 passed.

## Before photo + checklist (done)
- Worker Step 3 (on site): optional before photo (role BEFORE, EXIF + device location recorded, offline queue, Idempotency-Key). Step 4: checklist above the completion photo. Supervisor review screen shows both read-only.
- API: `GET /kavach/tasks/{id}/work-check`, `POST .../checklist`, `POST .../before-photo` (`geosatya/kavach/workcheck.py`, table `kavach_task_checklists`). GeoSatya completion rules unchanged; both optional.
- Steps = Sanitation plan tasks if present, else category instructions; ids like `ROAD_DAMAGE-01` (never the agent's built-in STEP-01..03 waste meanings). Verification gets the worker's before photo first, and only ticked steps (as True; unticked = UNKNOWN).
- The agent marks a step SUPPORTED only when its vision confirms it; in mock mode ticks stay "claimed". Real scoring needs `VERIFICATION_AGENT=gemini`.
- Tests: 13 in `tests/test_verification_agent.py`. Full suite 235 passed.

## Not done / next
1. Field Worker (shwetamishra1910): needs PostgreSQL, overlaps GeoSatya worker flow — port blockers/pause as a feature instead.
2. Merge dispatch-work's 31 Oct ranking update (needs review; GeoSatya has the earlier version).
3. Zone-aware dispatch preference (zones are stored and shown; ranking ignores them).
4. PNG app icons still GeoSatya-style; regenerate with the Kavach mark (`scripts/make_app_icons.py`).
5. Real authentication + PostgreSQL/Alembic migration before any deployment.
6. Phone test through Cloudflare tunnel (`cloudflared tunnel --url http://localhost:8000`).
7. `.claude/launch.json` at repo root is a local dev file — don't commit it.
