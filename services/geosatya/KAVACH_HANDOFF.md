# KAVACH integration: checkpoint

Branch: `kavach-unified` (local). **Nothing from the work below is committed or pushed.** Teammate branches were only read.
Database backups: `data/backups/geosatya_v3-before-*.db` (taken before each stage; never delete).

## How to run (say "RUN KAVACH" to Claude, or do it yourself)
```
powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\run-kavach.ps1          # agents + server + Cloudflare link
powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\run-kavach.ps1 -NoTunnel # laptop only
powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\stop-kavach.ps1          # stop everything
```
`run-kavach.ps1` checks every port first and never stops a process that is not a KAVACH one (it names the process and suggests a
free port instead; `-StopOldKavach` only stops processes whose command line is a KAVACH one). It starts the four agents and the server,
checks that each answers and that the server reaches each agent, starts the tunnel, **tests the link from outside** (health, locked
without the code, code accepted) and only then prints the link and a random access code. Nothing is written to a file.
Tests: `python -m pytest -q` in `services/geosatya` -> **264 passed** (190 original GeoSatya + Kavach platform, agents, verification, citizen/worker, women's safety). New this round: `tests/test_womens_safety.py` (20), `tests/test_kavach_citizen_worker.py` (9).
Browser checks done on a throwaway copy (port 8100, temporary database, stopped afterwards): 360, 375, 768, 1280 and 1440 px wide, no sideways scrolling; no console errors on the checked pages.
Not tested: a real phone (camera, GPS, install), the confirm() pop-ups of cancel/end SOS in a browser, the Cloudflare tunnel with the new scripts (they were syntax-checked and their port-conflict path was run; a full run happens at RUN KAVACH).

## Ports (all on 127.0.0.1; only the tunnel makes the server reachable from outside)
| Service | Port | Env var |
|---|---|---|
| KAVACH server (API + frontend, same origin) | 8000 | `KAVACH_PORT` |
| Incident Intelligence agent | 8001 | `INTELLIGENCE_PORT` |
| Duplicate Detection agent | 8002 | `DUPLICATE_PORT` |
| Supervisor agent | 8003 | `SUPERVISOR_PORT` |
| Sanitation Planning agent | 8004 | `SANITATION_PORT` |
Verification runs inside the server. Databases are SQLite files (`data/geosatya_v3.db`, `services/agents/_data/duplicates.db`,
`data/verification_audit.db`): there is no database port. Frontend and API share one origin, so no CORS is needed
(`CORS_ORIGINS` exists for a separately hosted frontend). The frontend has no hardcoded server addresses.

## Done earlier
- Tenancy and workspaces (organizations, events, platform admin), photo-free public reports with authority suggestion, public tracking/dashboard.
- Team agents: Intelligence, Duplicate Detection, Supervisor, Sanitation (HTTP, advisory) and Verification (in-process adapter). Original authors kept in `services/agents/*/ORIGIN.md` and on the About page.
- Worker before photo + checklist.

## This round (design, women's safety, citizen and worker features)
- **Logo**: the supplied logo (`frontend/icons/kavach-logo-source.webp`) is used as is. `scripts/make_kavach_logo.py` makes the transparent versions
  (`kavach-logo.png/.webp`, shield `kavach-mark.png`) and the app icons / favicon from it. Used in the nav, landing, sign-in/registration pages (public bar),
  dashboards (sidebar), phone header, favicon, PWA icons and the loading screen.
- **Design**: `theme.css` (white/light grey, deep navy, subtle green; Inter + Manrope), `home.css`, `safety.css`. New home page `js/kavach/home.js`
  (hero, scrolling category experience, how it works, GeoSatya, five stages, audiences, women's safety, live numbers, FAQ, footer). Mobile bottom bar and a floating SOS shortcut for citizens.
- **Categories**: the 12 requested; 4 new ones (public toilet, sanitation, waste disposal, highway). The category picked on the home page stays selected into the form (`js/kavach/categories.js`).
- **Citizen**: one description is enough (title optional), five stages Reported, Verified, Assigned, In progress, Resolved (own and public tracking pages), feedback after resolution (`kavach_feedback`).
- **Worker**: Available jobs page (open complaints in the worker's own workspace, matching skills, within the dispatch radius of the location they shared) and claiming (`geosatya/kavach/citizen_worker.py`).
- **Women's safety**: `geosatya/kavach/women.py` (API `/api/v1/women/...`), `js/kavach/safety.js`. Trusted allies with consent, SOS (hold 1 s or Enter, 5-second cancel countdown),
  real phone GPS only (simulated is refused), manual labelled point as fallback, live updates while the SOS screen is open, cancel / "I'm safe", history, private per-ally links
  (`#/sos/<token>`), tel: links for 100, 108, 112 + disclaimer. Tables: `kavach_trusted_allies`, `kavach_sos`, `kavach_sos_events`, `kavach_sos_notifications` (private, not in the shared audit log).
- **Not connected, and shown honestly**: SMS, WhatsApp and push. Notification rows stay `PENDING_INTEGRATION`; the user sends each ally's link with WhatsApp / SMS / share buttons from their own phone.

## Round 3 (2026-11-17): real sign-in, central authorization, camera-first complaints, simpler UI
Backup before this round: `data/backups/geosatya_v3-before-auth-20261117-064443.db`. Only nullable columns were added (`users.login_id`,
`password_hash`, `auth_epoch`, `registered_at`, `last_login_at`) plus a unique index on `login_id`. No data was deleted.
- **Sign-in** (`geosatya/security.py`, `geosatya/api/auth_routes.py`, follows KAVACH_Authentication_Authorization_Flows.pdf). `AUTH_MODE=jwt` is now the default.
  Citizen: `POST /auth/citizen/register`, `POST /auth/login`. Worker: `POST /auth/worker/register` with `WORKER_ACCESS_CODE`, then `/auth/login`.
  Supervisor: no sign-up; account made with `scripts/kavach_accounts.py` (password typed hidden), then `POST /auth/supervisor/login` with
  `SUPERVISOR_ACCESS_CODE`; platform admins need `ADMIN_ACCESS_CODE` instead. Passwords: scrypt. Tokens: HS256 JWT (stdlib), role checked
  against the database on every request; sign-out raises `auth_epoch` (all devices). Sign-in is rate limited. Codes exist only in env vars.
  `AUTH_MODE=demo` still works (demo identities + JWT); all old tests use it.
- **Central authorization** (`geosatya/authz.py`): every API route passes `authorize()` (JWT -> user -> role -> POLICY table), then the existing
  ownership/workspace loaders. A route missing from POLICY is refused (403) and a test fails. Wrong role = 403; another person's record = 404.
- **Complaints need a camera photo + GPS**: `POST /kavach/public/reports` is now multipart (`payload` + `photos`). No photo -> PHOTO_REQUIRED,
  no device GPS -> LOCATION_REQUIRED, map pin or gallery file refused. `geosatya/kavach/reportcheck.py` = GeoSatya check (accuracy, photo-time
  vs GPS-time, freshness, simulated, EXIF comparison) -> LOCATION_VERIFIED or NEEDS_REVIEW; `GET /kavach/incidents/{id}/check`. 15 m geofence unchanged.
- **Frontend**: "+" menu (3 options) in the public bar and `#/start`; sign-in pages `js/kavach/auth.js`; camera-first form `js/kavach/complaint.js`;
  profile / share location / available workers `js/kavach/profile.js`; shorter home page (7 sections); per-role menus with "More"; `auth.css`; SW cache kavach-v7.
- **run-kavach.ps1**: new random worker / supervisor / admin codes and JWT secret each run (printed, never saved); `-Demo` for demo mode; checks `/auth/options`.
- **Registered workers only** (AUTH_MODE=jwt): dispatch, the supervisor's worker list and manual assign/reassign skip workers without a sign-in
  account (`dispatch.needs_registered_workers`); a real complaint is never routed into a sample (is_demo) authority's workspace.
  GS-Y2XHH8 was moved from Imran (sample) to the registered worker W-34099B35 (audited; backup `geosatya_v3-before-reassign-20261117-122104.db`).
- Tests: full suite **306 passed** (2026-11-17). New: `tests/test_auth.py` (24), `tests/test_complaint_photo_gps.py` (16); old public-report tests send a photo now.
  Browser (throwaway server, port 8100, stubbed camera/GPS in the test page only): citizen register -> report (denied GPS, weak GPS, good GPS -> verified),
  worker register (wrong code refused), supervisor sign-in (wrong code refused); 360 px wide: no sideways scroll on 13 pages.

## Round 4 (2026-11-23): Aurora redesign, team wall, radar allocation, voice notes, dev access
No database rows were changed or deleted; one new table only (`kavach_audio_notes`, created on start).
- **Design system** `frontend/aurora.css` (loaded last): dark glass tokens and surfaces for every page, glass forms (focus glow,
  select arrow, date picker, file button, invalid shake), dark maps. Light logo `icons/kavach-logo-light.webp` / `kavach-mark-light.png`.
- **Home** `js/kavach/home.js`: Digital Serenity hero (port: `js/kavach/serenity.js`, scoped listeners, rAF glow, reduced motion),
  9-step Report→Learn flow, live public stats, categories, GeoSatya + dispatch, women's safety, team wall, CTA.
- **Team** `#/team` + home: TeamLanyardRail port `js/kavach/lanyard.js`, data `js/kavach/team-data.js` (the 10 people in the README,
  Namrata = Team Lead, work taken from each person's branch). Photos `frontend/icons/team/`. Shubhrit has no photo yet (silhouette);
  Om Gupta's work isn't in the repo, so his card only says "Team member". See `frontend/components/ui/README.md`.
- **Worker allocation**: read-only `GET /incidents/{id}/dispatch/candidates` (`dispatch.preview_candidates`, the same pool + Dispatch
  ranking, writes nothing). `js/kavach/allocate.js`: radar dialog (blips at real bearing/distance), glass worker cards, assign /
  reassign through the existing endpoints. Automatic dispatch unchanged. `#/workers` uses the same cards.
- **Voice notes** `geosatya/kavach/audio.py`: `POST/GET /women/sos/{id}/audio-notes`, `GET /women/share/{token}/audio-notes/{note}`
  (only while the SOS is active), `POST/GET /tasks/{id}/audio-notes` (assigned worker; workspace supervisors can play). Real audio
  only (bytes sniffed: webm/ogg/mp4/wav/mp3), 6 MB, 3 min, 5 per SOS, 3 per attempt; private storage `private_uploads/audio`;
  task notes audited (`VOICE_NOTE_ADDED`), SOS notes in the SOS event log. Optional everywhere. UI `js/kavach/voice.js`.
- **Development access**: `run-kavach.ps1` now starts with AUTH_MODE=demo by default (no login, DEV role chips in the top bar,
  sign-in pages show the role picker). `-RealLogin` = JWT only. Demo stays refused when APP_ENV=production; JWT code untouched.
  Registered-workers-only dispatch applies in JWT mode only, so in dev mode the seeded test workers get jobs again.
- Tests: **317 passed** (new `tests/test_audio_notes.py`: 9 voice-note + 2 worker-search). Browser (throwaway port 8100 DB):
  home, team flip + panel, radar with real distances, task + SOS recording (test tone stream), owner + ally playback,
  no sideways scroll at 375 px on 20 pages, no console errors. Not tested: a real microphone / phone, a full reassign click-through.

## Team live demo (2026-11-25): `run-kavach.ps1 -TeamDemo`
Own database `data/kavach_team_demo.db` + `private_uploads_team/` (the normal database is not touched). `TEAM_DEMO=1`
(`geosatya/kavach/teamdemo.py`) creates the ten members: Namrata = supervisor; Divyansh, Shreya, Shweta = citizens;
Kavyansh, Yash, Shubhrit, Ananya, Karanveer, Om = field workers (all skills, open civic team). The base sample identities are
switched off in that database only. Sign-in screen (`js/kavach/teamlogin.js`): tap your name, password `kavach123`, but
any password is accepted (it only looks like a sign-in). Refused unless AUTH_MODE=demo and not production.
Tests: `tests/test_team_demo.py` (only the 10, full report → assign → complete → approve, refused in JWT mode).

## Not done / next
1. A real SMS / WhatsApp / push provider for SOS (needs an account and credentials). Until then delivery is user-sent.
2. Background SOS tracking when the phone locks (a browser cannot; needs a native app or push-based wake).
3. Public ally link while the access code is on: allies must enter the dev access code first. Remove the code for a real deployment.
4. OTP / password reset, PostgreSQL + Alembic before any deployment. Token is kept in localStorage (XSS-exposed); HttpOnly cookie + CSRF is better for production.
   Workspace members added by an organization (and invite joins) still have no password: give them one with `kavach_accounts.py set-login`.
   Not tested on a real phone camera / GPS yet.
5. Field Worker agent (needs PostgreSQL), merge of dispatch-work's 31 Oct update, zone-aware dispatch.
6. The footer contact (`hello@kavach.example`) is a placeholder.
7. `.claude/launch.json` is a local dev file; do not commit it.
