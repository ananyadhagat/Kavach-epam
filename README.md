# Kavach: AI-driven Multi-Agent Incident Management

**Team Codyssey** · EPAM Learning Track project · *"AI-driven Intelligence for Smarter Incident Resolution"*

Kavach takes a citizen complaint about sanitation or a public incident and carries it all the way to a **verified resolution**: structuring the complaint, detecting duplicates, prioritising it, getting approval, assigning a worker, tracking the field work, and checking the result with before/after photos and GPS.

> **Project status (23 Oct 2026): all seven agents are built as standalone services, each on its own branch. They are not merged or wired together yet.**
> `main` holds only this README. Section 5 shows what works today, section 6 shows what is still missing, and section 7 lists the next steps.

---

## 1. Problem and solution

Complaint handling for sanitation and public incidents is slow, workers are not accountable, and emergencies are poorly coordinated. There is no central view of problem-prone areas, repeat issues go unnoticed, and citizens cannot track their complaint.

Kavach replaces that with a pipeline of cooperating AI agents. The design principle used across the code is that **the LLM suggests or describes, and deterministic Python rules decide**. Gemini never has the final say on priority, approval or pass/fail.

## 2. Agent workflow

```
Citizen complaint (text / voice transcript / photos / GPS pin)
        │
  1. Incident Intelligence ──► structured incident record
        │
  2. Duplicate Detection ──► NEW / REVIEW_REQUIRED / DUPLICATE (link to existing)
        │ (new)
  3. Supervisor ──► department + priority + approval
        │             APPROVED_TO_PROCEED │ PENDING_APPROVAL (admin) │ NEEDS_REVIEW
        │ (approved)
  4. Sanitation (domain agent) ──► cleaning plan, resources, time, checklist
        │
  5. Dispatch ──► best available worker + equipment (or escalate to Supervisor)
        │
  6. Field Worker ──► accept → start → checklist → before/after photos + GPS → submit completion
        │
  7. Verification ──► PASS / FAIL / INCONCLUSIVE / MANUAL_REVIEW
        │
   Pass → incident closed        Fail → sent back to Supervisor / re-dispatch
```

## 3. Repository map: one branch per agent

Every branch was created from the `Initial commit` and is independent of the others.

| Branch | Agent | Owner (GitHub) | Stack | Storage | Maturity |
|---|---|---|---|---|---|
| `incident-intelligence-agent` | 1. Incident Intelligence | Shreya Kaushik (`shreyakaushik878-cloud`) | FastAPI, Gemini, Pillow | memory or PostgreSQL (JSONB) | Most complete, v1.1.1 with audit fixes |
| `duplicate-detection-agent` | 2. Duplicate Detection | Yash Dadlani | Pure Python library, Pydantic, scikit-learn | in-memory + synthetic data | Core engine done, **no HTTP layer yet** |
| `supervisor-agent` | 3. Supervisor | Karanveer Singh Malhotra (`Karanveersm`) | FastAPI, Gemini (google-genai) | none | Stage 1, no tests |
| `sanitation-work` | 4. Sanitation | Namrata Digarse (team lead) | FastAPI, **LangGraph**, Gemini | none | Plan and handoff working |
| `dispatch-work` | 5. Dispatch | Ananya Dhagat (`ananyadhagat`) | FastAPI | in-memory demo workers | Stage 1, no tests |
| `Field-worker-agent` | 6. Field Worker | Shweta Mishra (`shwetamishra1910`) | FastAPI, async SQLAlchemy, Alembic, Pillow | **PostgreSQL (required)** | Most thorough backend and test suite |
| `verification-agent` | 7. Verification | `MrBadDrip` | FastAPI, OpenCV, Gemini vision | memory or SQLite audit log | Complete prototype with requirements-coverage doc |

The design specifications for the agents (flowcharts and technical explanations, PDF) are stored on the `verification-agent` branch in `docs/specs/`.

## 4. What each agent does

### 1. Incident Intelligence (`incident-intelligence-agent`)
Turns a raw complaint into a validated `StructuredIncidentRecord`.
- **Endpoints:** `POST /api/v1/incidents` (multipart: text, voice transcript, map pin, device GPS and accuracy, up to 4 images), `GET /api/v1/incidents/{id}`, `GET /api/v1/incidents/{id}/duplicate-detection-request`, `GET /health`. A browser map tester is served at `/tester/`.
- Gemini classifies the complaint and extracts facts. Deterministic code handles everything else: category/type taxonomy, severity floor (including Hindi and Hinglish danger words), EXIF GPS extraction, and distance and source-conflict checks.
- The citizen's pin, device GPS and photo EXIF are kept as separate evidence and never overwrite each other.
- Production-minded behaviour: `X-Request-ID` idempotency, per-IP rate limit, read access via `X-API-Key`, image safety checks (real format, size, pixel cap), and clear 502/503/413/429 error mapping.
- `handoff.py` maps the record to the Duplicate Detection request. This mapping is a **draft** (`a1-to-a2-draft-1`).

### 2. Duplicate Detection (`duplicate-detection-agent`)
Decides whether a new complaint matches an existing one. It is advisory only and never merges or deletes anything.
- **Implemented:** request/response schemas, repository abstraction (in-memory and synthetic fixtures), four comparators (text TF-IDF, location Haversine, category, time), a `WeightedScoringEngine` (default weights text 0.40, location 0.30, category 0.15, time 0.15), and a `DecisionPolicy` that returns `DUPLICATE`, `REVIEW_REQUIRED` or `NEW` with reason codes and tie/ambiguity handling.
- **Not implemented:** FastAPI routes, candidate retrieval from real data, image similarity.
- Seven design documents sit in `docs/duplicate_detection/` (architecture, API contract, matching policy, integration, scoring, decision policy, implementation plan). Thresholds are provisional and not yet tuned on labelled data.

### 3. Supervisor (`supervisor-agent`)
Chooses the department, sets the priority, drafts the action plan and decides if it can proceed. It lives under `kavach-supervisor__/kavach-supervisor/`.
- **Endpoints:** `GET /samples`, `POST /supervisor/evaluate`.
- Gemini only *suggests* department, actions and risks. Python rules validate everything and decide. Invented actions or conflicting departments are rejected.
- Output `approval_status`: `APPROVED_TO_PROCEED` (routine), `PENDING_APPROVAL` (HIGH priority needs a human) or `NEEDS_REVIEW` (missing or conflicting evidence, no domain agent for that department, duplicate, or Gemini failure). `reason_codes` explains why.
- `LLM_PROVIDER=mock` lets you test without a Gemini key.

### 4. Sanitation (`sanitation-work`)
The domain agent for waste and sanitation issues.
- **Endpoints:** `POST /api/v1/sanitation/plan`, `POST /api/v1/sanitation/handoff`, `GET /health`.
- A **LangGraph** workflow classifies the complaint with Gemini (`overflowing_dustbin`, `garbage_pile`, `dirty_public_toilet`, `waste_spill`, or none) and then builds the plan from a rules policy, with resource and time estimators and a safety validator.
- The handoff endpoint only accepts **approved** complaints and returns a `DispatchContract` that is always `PROPOSED` with `requires_human_review = true`. It never assigns workers itself.

### 5. Dispatch (`dispatch-work`)
Deterministic worker assignment.
- **Endpoints:** `POST /api/v1/dispatch/assign`, `GET /api/v1/dispatch/tasks/{incident_id}`, `GET /api/v1/workers`, `GET /api/v1/dispatch/health`.
- Workers are rejected with explicit reasons: unavailable, at capacity, missing skills or equipment, stale location (over 15 minutes), or outside the radius (default 2 km). The rest are ranked by distance and workload.
- Assignment is idempotent per incident. With no eligible worker the result is `UNASSIGNED: Escalate to Supervisor`. Data is a 4-worker in-memory demo.

### 6. Field Worker (`Field-worker-agent`)
The execution backend for the worker app.
- **Endpoints:** list/get tasks; `accept`, `reject`, `start`, `pause`, `resume`; checklist `GET`/`PATCH`; `evidence` upload; `arrival` and `completion-location` GPS capture; `completion` submission.
- Enforced task state machine: `ASSIGNED → ACCEPTED | REJECTED`, `ACCEPTED → IN_PROGRESS`, `IN_PROGRESS ↔ PAUSED`, `IN_PROGRESS → COMPLETION_SUBMITTED`. Invalid moves return 409.
- PostgreSQL with 9 tables and an Alembic migration (`0001_initial_schema`), idempotency keys, image validation and private storage, GPS accuracy handling, and demo bearer-token auth (refused in production).

### 7. Verification (`verification-agent`)
Decides whether the completed work really solved the problem.
- **Endpoint:** `POST /api/v1/tasks/{task_id}/verification` (versioned contract, header `X-KAVACH-Contract-Version: 1.1`), plus `/health`.
- Checks evidence completeness and ownership, runs OpenCV quality checks (blur, brightness, resolution, near-duplicate before/after photos), a vision model (mock or Gemini) that **only describes** the scene, GPS Haversine verification, and checklist/plan compliance.
- A deterministic decision engine combines a weighted score (pass threshold 75) with mandatory rules: a contradicted mandatory requirement fails regardless of score. Outcomes are `PASS`, `FAIL`, `INCONCLUSIVE` or `MANUAL_REVIEW`.
- Audit records are persisted and idempotent. `docs/REQUIREMENTS_COVERAGE.md` maps all 20 stages of the design guide to code and tests, and `docs/INTEGRATION.md` describes the contracts.

## 5. Test results (re-run on 23 Oct 2026)

| Branch | Result | Notes |
|---|---|---|
| `duplicate-detection-agent` | **280 passed** | fully offline |
| `incident-intelligence-agent` | **132 passed, 3 skipped** | skipped tests need PostgreSQL; mock LLM mode |
| `verification-agent` | **103 passed** | mock vision; real Gemini path not covered |
| `sanitation-work` | **58 passed, 6 failed** | the 6 failures call the live Gemini API and need a real `GEMINI_API_KEY` |
| `Field-worker-agent` | not run | ~200 tests need a PostgreSQL `*_test` database |
| `supervisor-agent` | no test suite | manual mock-mode check returned `APPROVED_TO_PROCEED` for a routine case |
| `dispatch-work` | no test suite | app imports and lists its 4 demo workers |

## 6. Plan vs. repository

| Planned in the project slides | In the repository today |
|---|---|
| 7 cooperating agents | All 7 built, **each standalone** |
| LangGraph orchestration of the full workflow | LangGraph is used only inside the Sanitation agent |
| React + Tailwind portals (citizen, worker, admin) | **Not started.** Only a single-page map tester exists on the intelligence branch |
| FastAPI gateway with JWT and RBAC | **Not started.** Each service has its own stop-gap auth (demo token, API keys) |
| Central PostgreSQL | Only Field Worker (required) and Intelligence (optional) |
| Gemini API | Used by Intelligence, Supervisor, Sanitation and Verification, each with its own client |
| MCP tool access, LangChain RAG | Not present in the code |
| Geolocation and hotspot map | Location verification exists (Intelligence, Verification, Field Worker); hotspot map not started |
| Deployment (Vercel) | Not started |
| Predictive monitoring, crowd safety, women SOS, worker rewards | Future scope, not started |

## 7. Known issues and next steps

**Quick fixes**
- [ ] `Field-worker-agent/README.md` still contains unresolved merge-conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`). Clean them up.
- [ ] `dispatch-work`: `requirements.txt` is empty (needs `fastapi`, `uvicorn`) and the package file is named `app/_init_.py` (should be `__init__.py`).
- [ ] `supervisor-agent`: the API key is read from an env variable literally named `key_needed`, and the default model ID `gemini-3.8-flash` should be confirmed against what your key can actually use.
- [ ] `sanitation-work`: mock Gemini in the 6 network-dependent tests. The branch also pins Python 3.14, so agree one Python version for the team.
- [ ] `verification-agent/docs/specs/`: one spec file is missing its `.pdf` extension, and `REQUIREMENTS_COVERAGE.md` refers to an `AUDIT.md` and a guide PDF that are not in the branch.

**Integration work (in this order)**
1. **Agree one shared contract**: incident ID format, category vocabulary and the field names passed between agents. The agents currently use different vocabularies, for example Intelligence `WASTE_OVERFLOW`, Sanitation `overflowing_dustbin`, and Duplicate's examples `ROAD_DAMAGE`. The Supervisor's input is documented as an assumption, and the Intelligence→Duplicate handoff is a draft.
2. **Restructure into one repo layout**, for example `services/<agent>/`. Five branches use a top-level `app/` package, so they cannot be merged as they are.
3. **Merge the branches into `main`** one by one, with a shared Python version and a CI job that runs each agent's tests.
4. **Add the Duplicate Detection HTTP layer** and real candidate retrieval.
5. **Build the orchestrator** (LangGraph) that runs agents 1→7, including the fail → re-dispatch loop and the admin approval step.
6. **Build the gateway and auth** (JWT, RBAC) and one shared database.
7. **Build the three portals** (citizen, worker, admin with map and hotspots), then deploy.
8. **Test the real Gemini paths** in Supervisor, Sanitation and Verification, which are currently verified only with mocks or fakes.

## 8. Running an agent locally

Clone and switch to the branch you want:

```bash
git clone https://github.com/ananyadhagat/Kavach-epam.git && cd Kavach-epam
git checkout <branch>        # see the table in section 3
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

| Branch | Install and run |
|---|---|
| `incident-intelligence-agent` | `pip install -r requirements.txt pytest httpx` · `cp .env.example .env` (set `GEMINI_API_KEY`, `KAVACH_LLM_MODE=gemini`) · `cd src && uvicorn kavach.main:app --reload --env-file ../.env` · tester at `/tester/` · tests: `pytest` |
| `duplicate-detection-agent` | `pip install -r requirements.txt` · `pytest` |
| `supervisor-agent` | `cd kavach-supervisor__/kavach-supervisor` · `pip install -r requirements.txt` · `.env` with `LLM_PROVIDER=mock` · `uvicorn app.main:app --reload` |
| `sanitation-work` | `.env` with `GEMINI_API_KEY`, `GEMINI_MODEL` · `uv sync` (Python 3.14) · `uvicorn main:app --reload` |
| `dispatch-work` | `pip install fastapi uvicorn` · `uvicorn app.main:app --reload` |
| `Field-worker-agent` | Needs PostgreSQL. Follow that branch's README (create `kavach` and `kavach_test` databases, copy `.env.example`, `pip install -r requirements.txt`, `alembic upgrade head`) · `uvicorn app.main:app --reload` |
| `verification-agent` | `pip install -r requirements.txt` · `cp .env.example .env` (`VISION_PROVIDER=mock` works offline) · `uvicorn app.main:app --reload` · `pytest` |

Every service exposes interactive API docs at `/docs` (Swagger UI) when running.

## 9. Team Codyssey

| Role | Members |
|---|---|
| Team lead | Namrata Digarse |
| Members | Shreya Kaushik, Shweta Mishra, Shubhrit Tiwari, Kavyansh Gupta, Om Gupta, Karanveer Singh Malhotra, Ananya Dhagat, Divyansh Kackker, Yash Dadlani |

*Thank you. Together we can enable cleaner and smarter public management.*
