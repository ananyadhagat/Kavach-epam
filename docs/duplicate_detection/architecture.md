# Duplicate Detection Agent — Architecture

> Phase 1 design document. The prototype core now exists under `app/`; see
> [`service_orchestration.md`](./service_orchestration.md) for the current module
> map, orchestration flow and implementation status. The conceptual design below
> is retained as the original architecture.
>
> **Current implementation status.** The schema, repository, four core
> comparators (including the optional embedding text backend), weighted scoring
> engine, decision policy, internal `DuplicateDetectionService`, Agent 1 input
> adapter and Agent 3 M3 HTTP edge are implemented. An optional **consolidation
> service** (see the addendum in §8) now persists complaints and records the M3
> outcome as group/link/review state without changing the advisory contract of
> the DDA itself. The optional image signal (M7) remains deferred. Names and
> paths in the Phase 1 tables below are conceptual; the current code lives in
> `app/services/`, `app/api/`, `app/adapters/`, `app/comparators/`,
> `app/scoring/`, `app/repositories/`, `app/db/`, `app/schemas/` and
> `app/config/`.

## 1. Purpose and scope

The **Duplicate Detection Agent (DDA)** receives a newly submitted civic complaint and
compares it against already-known complaint records to propose whether it is:

- `DUPLICATE` — a sufficiently strong existing candidate represents the same real-world incident,
- `REVIEW_REQUIRED` — evidence is borderline, incomplete, contradictory, or ambiguous,
- `NEW` — no credible duplicate candidate was found *within the searched repository and policy scope*.

The DDA is **advisory only**. It detects and proposes. It never deletes, merges,
overwrites, or otherwise mutates any complaint. Recording, merging, and workflow
decisions belong to other KAVACH components (`TEAM-DECISION` on which ones).

### Out of scope for the DDA
- Persisting complaint lifecycle or merge state.
- Deciding *what to do* about a duplicate.
- Notifying users, dashboards, or supervisors.
- Owning the master complaint store.

## 2. Design principle: business logic independent of transport

The matching logic must be usable in **two** integration models without change:

- **Option A — importable Python module** inside the final KAVACH backend.
- **Option B — independently deployable FastAPI service** called over HTTP.

To make both possible, the core is a plain-Python `DuplicateDetectionService` that
takes a *domain request object* and returns a *domain result object*. FastAPI, JSON,
HTTP status codes, and serialisation live in a thin edge layer and are the **only**
transport-specific code.

```
                 ┌──────────────────────────────────────────┐
                 │            EDGE (transport)               │
                 │  FastAPI routes · request/response schemas│
                 └───────────────┬──────────────────────────┘
                                 │ domain request object
                                 ▼
                 ┌──────────────────────────────────────────┐
                 │         DuplicateDetectionService         │
                 │  (pure Python, no FastAPI imports)        │
                 └───┬───────────┬───────────┬───────────────┘
                     │           │           │
        ┌────────────▼──┐  ┌─────▼──────┐  ┌─▼────────────────┐
        │CandidateRetriever│ │ Comparators│  │ Decision pipeline │
        │ + Repository    │  │ text/loc/  │  │ ScoringPolicy →   │
        │                 │  │ cat/time/  │  │ ContradictionRules│
        │                 │  │ image      │  │ → HybridDecision  │
        └─────────────────┘  └────────────┘  └──────────────────┘
                     │
              ┌──────▼───────────────┐
              │ IncidentRepository    │  ← interface
              │ InMemory (prototype)  │  ← later: Postgres / HTTP / shared store
              └───────────────────────┘
```

**Rule:** nothing in `service/`, `comparators/`, `policy/`, or `repository/base.py`
may import FastAPI, Pydantic-as-transport, or any HTTP library. Schemas may be Pydantic
models, but the service consumes plain domain objects so it can be reused elsewhere.

## 3. Integration options

### Option A — Importable module within the KAVACH backend
The DDA ships as a Python package (`duplicate_detection`) that the KAVACH backend
imports and calls in-process.

| Pros | Cons |
| --- | --- |
| No network hop; simplest to integrate; single deployment. | Couples release cycles; a DDA bug can affect the whole backend process. |
| Direct access to a shared repository object / DB session. | Changes to shared runtime can break the DDA; harder to isolate. |
| Trivial unit testing and local running. | Scales with the host process only. |

### Option B — Independently deployable FastAPI service
The DDA runs as its own service exposing the HTTP contract in `api_contract.md`.

| Pros | Cons |
| --- | --- |
| Clean ownership boundary across 10 independent developers. | Needs a network contract, versioning, and error mapping. |
| Can evolve/deploy without redeploying KAVACH. | Extra latency, an HTTP surface to secure, and shared-data-access questions. |
| Matches the "each member owns an agent" project structure. | Requires the team to agree *how it reaches the complaint data* (see `integration.md`). |

### Recommendation
**Default for the first prototype: Option B (standalone FastAPI service), built so that
Option A remains a drop-in.** Rationale:

1. The team is 10 independent members with no shared codebase yet. A standalone
   service gives the DDA a clean, ownable boundary and removes the need to coordinate
   a shared runtime on day one.
2. Because all business logic is transport-free, the same package can later be imported
   in-process (Option A). Choosing B first costs nothing structurally and buys isolation.
3. A service is trivially demoable and testable on its own, which matches the Phase 1
   goal of an independently implementable component.

`TEAM-DECISION`: whether KAVACH's final architecture prefers in-process import (A) or
sidecar service (B). This specification supports both with no algorithm change.

## 4. Logical responsibilities

Each responsibility is a small, independently testable unit. Names below match the
project brief; where a different name is clearer, it is noted.

> **Current mapping.** The service is
> [`app/services/detection_service.py`](../../app/services/detection_service.py);
> comparators are in `app/comparators/`; scoring and decision rules are in
> `app/scoring/engine.py` and `app/scoring/decision_policy.py`; the repository
> contract is `app/repositories/base.py`. The `CandidateRetriever`, image
> comparator and separate `policy/` package shown below are Phase 1 concepts and
> are not present in the current prototype. See
> [`service_orchestration.md`](./service_orchestration.md).

| Responsibility | Input | Output | Boundary / notes |
| --- | --- | --- | --- |
| **DuplicateDetectionService** (`service/detection_service.py`) | `DetectionRequest` (domain) | `DetectionResult` (domain) | Orchestrates retrieval → comparison → scoring → decision. Contains **no** comparator maths and **no** policy thresholds itself; it delegates. Never performs I/O beyond calling the repository interface. |
| **CandidateRetriever** (`service/candidate_retriever.py`) | `DetectionRequest`, `IncidentRepository` | `list[IncidentRecord]` | Fetches eligible candidates, always excludes the current `complaint_id` (self-comparison), applies optional coarse filters (see §6). Converts repository errors into a typed failure, never swallows them. |
| **IncidentRepository** (interface, `repository/base.py`) | query params | records / errors | Storage abstraction. Only contract the service depends on. |
| **InMemoryIncidentRepository** (later phase, `repository/in_memory.py`) | seeded records | records | Prototype implementation backed by a list/dict. Not built in Phase 1. |
| **TextComparator** (`comparators/text.py`) | two descriptions | `SignalResult` | TF-IDF + cosine baseline. Owns preprocessing; no repo access. |
| **LocationComparator** (`comparators/location.py`) | two `Location` values | `SignalResult` | Identifier match first, Haversine fallback. Owns distance→score mapping. |
| **CategoryComparator** (`comparators/category.py`) | two categories | `SignalResult` | Exact match + compatibility map lookup. Emits a contradiction flag when incompatible. |
| **TimeComparator** (`comparators/time.py`) | two timestamps | `SignalResult` | Absolute difference + configurable decay. Never returns "different incident" from time alone. |
| **ImageHashComparator** (`comparators/image_hash.py`) | two optional hashes | `SignalResult` | **Optional / Phase-later.** Off by default (weight 0). Hamming distance on perceptual hashes. |
| **ScoringPolicy** (`policy/scoring.py`) | `list[SignalResult]`, weights | normalised `score` + per-signal contributions | Weight normalisation over available signals only. Pure function; no decision. |
| **HybridDecisionPolicy** (`policy/decision.py`) | score, evidence summary, contradictions, candidate ranking | `Decision` + `reason_codes` | Applies thresholds, minimum-evidence rules, contradiction rules, tie handling. Pure function. |
| **Config** (`config/settings.py`, `config/category_map.py`) | env / defaults | typed settings | Weights, thresholds, radii, windows, category compatibility. Single source of tunables. |

### Why these boundaries
- Comparators are **pure** (input → `SignalResult`); they can be unit-tested with no
  repository, no HTTP, and no fixtures beyond two values.
- The **repository** is the only place that knows about storage. Swapping in-memory
  for Postgres touches one file, not the algorithms.
- **ScoringPolicy** and **HybridDecisionPolicy** are separate so thresholds can be
  tuned (and later validated) without touching similarity maths.

## 5. Data flow

```
1. Edge receives POST /api/v1/duplicate-detection/check
2. Edge validates transport-level request → domain DetectionRequest (or 422)
3. DuplicateDetectionService.check(request)
   a. CandidateRetriever.retrieve(request)
        → repository.list_candidates(exclude=request.complaint_id, filters=...)
        → [] means "no eligible candidates" (genuine, not an error)
        → RepositoryError means "could not retrieve" (distinct outcome)
   b. For each candidate:
        signals = [Text, Location, Category, Time, (Image)]
        score   = ScoringPolicy.score(signals, weights)
        record a ScoredCandidate {id, score, signals, contradictions}
   c. Rank ScoredCandidates by score (stable tie-break, see matching_policy.md)
   d. HybridDecisionPolicy.decide(ranked, evidence summary)
        → decision, matched_incident_id?, reason_codes, best candidates
4. Service returns domain DetectionResult
5. Edge maps it to the response contract (HTTP 200 for every business outcome)
```

> **Current implementation.** `check()` returns the existing internal six-field
> `DuplicateDetectionResponse` directly. `check_detailed()` returns a
> `DetectionResult` with retrieval status, and the HTTP edge maps it to the Agent
> 3 eleven-field response (`app/api/mapper.py`). There is no `CandidateRetriever`
> object: the service calls `repository.retrieve_candidates(...)` (M3 path) or
> `repository.list_candidates(...)` (internal path) directly and defensively
> skips self/duplicate ids. See
> [`service_orchestration.md`](./service_orchestration.md) and
> [`m3_http_contract.md`](./m3_http_contract.md).

### Failure paths (distinct, never conflated)
- **Invalid request** → transport layer returns `422`; business logic not invoked.
- **No eligible candidates** → `200` with `decision = NEW`, reason `NO_ELIGIBLE_CANDIDATES`,
  provided retrieval attests `COMPLETE`.
- **Repository failure** → `check()` propagates `RepositoryError`; `check_detailed()`
  reports `200` with `processing_status=FAILED`, `decision=REVIEW_REQUIRED`, a
  retrieval reason code and an error object. A raw timeout/outage at the HTTP edge
  becomes `504`/`500`; *not* `NEW` and never a fabricated match.
- **Partial retrieval** → `200` with `processing_status=PARTIAL`,
  `decision=REVIEW_REQUIRED`; never `NEW`.
- **Single comparator failure** → that signal is `ERROR`, excluded from scoring and the
  remaining weights are renormalised. The outcome depends on the evidence gates: it may
  still be `NEW`, `REVIEW_REQUIRED` or `DUPLICATE` (see
  [`service_orchestration.md`](./service_orchestration.md) and
  `matching_policy.md`).

## 6. Candidate retrieval behaviour

`CandidateRetriever` is responsible for *eligibility*, not similarity:

> **Current implementation.** No separate `CandidateRetriever` exists yet. The
> service calls `repository.retrieve_candidates(exclude_complaint_id=...)` for
> the M3 path (which reports `COMPLETE`, `PARTIAL` or `FAILED`) and
> `repository.list_candidates(...)` for the internal `check()` path, then
> defensively skips the incoming id and duplicate candidate ids. No coarse
> blocking filters or retrieval window are applied in the current prototype.

- Always excludes records whose `complaint_id` equals the request `complaint_id`.
- Retrieves from the repository via the interface only.
- May apply **coarse blocking filters** to bound cost before pairwise comparison
  (all configurable, all optional for the first prototype):
  - same `facility_id` when both sides have it, and/or
  - reported within a `retrieval_window` (default wider than the scoring window), and/or
  - same or compatible-category set.
- If no filter is configured, retrieves all records (fine for small synthetic datasets).
- An empty retrieval result is returned as an empty list, **distinguished from** a
  repository exception, which propagates as `RepositoryError`.

Blocking is a performance optimisation only; it must never be the *reason* a true
duplicate is missed silently. When blocking is active, the production adapter
must report `RetrievalOutcome.PARTIAL` unless it can guarantee completeness, and
the Agent 3 wire response records the matching `processing_status` plus a
retrieval reason code. The current six-field internal
`DuplicateDetectionResponse` has no field for retrieval metadata; the Agent 3
M3 response carries `processing_status`, `reason_codes` and `error`.

## 7. Assumptions and open items

| ID | Type | Statement |
| --- | --- | --- |
| A1 | `ASSUMPTION` | Field names in the V1 contract (`complaint_id`, `description`, `category`, `location.*`, `reported_at`, `image_hash`) may be renamed once the team fixes shared identifiers. A mapping layer absorbs this. |
| A2 | `ASSUMPTION` | The DDA can read complaint records through a repository interface; it is not the system of record. |
| A3 | `ASSUMPTION` | Categories are opaque strings to the DDA; compatibility is data-driven, not hard-coded to a fixed vocabulary. |
| A4 | `ASSUMPTION` | Timestamps are ISO-8601 with an explicit UTC offset. |
| D1 | `TEAM-DECISION` | Integration model A vs B (§3). |
| D2 | `TEAM-DECISION` | Where operative complaint data physically lives, and how the DDA reads it (shared DB, API, batch export). |
| D3 | `TEAM-DECISION` | Canonical category identifier vocabulary and location identifier scheme. |
| D4 | `TEAM-DECISION` | Whether DDA is invoked synchronously on submission or asynchronously. |

## 8. Addendum — consolidation layer (implemented)

The Phase 1 statement that the DDA "never mutates any complaint" still holds:
the scoring engine and decision policy remain read-only. Consolidation is a
**separate, additive service** wrapping the M3 check; it owns persistence and
records the DDA's advisory outcome. It does not change M3 scoring, thresholds,
the decision policy, or the `POST /internal/v1/duplicate-detection/check` wire
contract.

```
Agent 1 complaint
      │
      ▼
ConsolidationService.ingest()
      │  store complaint
      │  DuplicateDetectionService.check_detailed()   (unchanged M3)
      │  persist decision:
      │     NEW             -> group + PRIMARY link
      │     DUPLICATE       -> DUPLICATE link to canonical primary
      │     REVIEW_REQUIRED -> pending review (no link)
      ▼
201 ConsolidationResult
```

Boundaries that preserve the original design:

- **Business logic is still transport-independent.** The consolidation service
  is a plain-Python service; the FastAPI router only validates and translates
  errors.
- **The repository abstraction is reused.** `SessionComplaintRepository`
  implements the existing `ComplaintRepository` interface, so M3 needs no
  knowledge of the database.
- **Every complaint is preserved.** Consolidation stores links and a primary
  pointer; it never merges, overwrites or deletes complaint records.
- **The DDA remains advisory.** `DUPLICATE` and `NEW` are recorded as
  consolidation state; human resolution of `REVIEW_REQUIRED` is still out of
  scope and has no endpoint.
- **`/check` stays read-only.** When a database is configured it reads
  persisted, consolidated complaints; it never writes.

Runtime shape: `app.main` mounts the consolidation router only when
`KAVACH_DATABASE_URL` or `DATABASE_URL` is set. Without either variable the
original in-memory application is unchanged. Schema, API examples and the
migration are documented in
[`consolidation_service.md`](./consolidation_service.md).

Open items introduced by this layer (also in the README):

- PostgreSQL migration and concurrent-ingestion behaviour are unverified; only
  SQLite has been exercised.
- Review resolution and group close/reopen lifecycles are unimplemented, so
  pending-review complaints stay invisible to M3 indefinitely.
- Idempotency records have no retention policy.
- Generated group/link/review ids are UUID4 strings; complaint ids remain the
  opaque contract ids pending a team decision (Agent 3 prefers UUIDs).
