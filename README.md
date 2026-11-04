# KAVACH — Duplicate Detection Agent (standalone prototype)

> **This is a working prototype, not a production duplicate detector.**
> Phase 2 implemented the schema, repository and configuration foundation.
> Phase 3 added the four core **comparators** (category, time, location, text),
> which produce individual, advisory evidence signals only. The `text` signal
> can be produced by a local sentence-embedding comparator (default) or the
> lexical TF-IDF comparator (baseline/fallback); exactly one is used per
> comparison. Phase 4 adds both the **weighted scoring engine** (M3), which
> combines those signals into a ranking score, and the **decision policy** (M4),
> which turns the scored evidence into `DUPLICATE` / `REVIEW_REQUIRED` / `NEW`.
> The Agent 1 input adapter (M2), the orchestration service and the Agent 3 M3
> HTTP endpoint are also implemented.
>
> An optional **consolidation service** now persists complaints in a relational
> database and groups M3-confirmed duplicates under one canonical primary while
> preserving every original complaint. It is enabled only when
> `KAVACH_DATABASE_URL` or `DATABASE_URL` is configured; without either variable
> the original in-memory app is unchanged. PostgreSQL migration and concurrency
> behaviour are not yet verified in this environment.
>
> Image similarity, review/group lifecycle endpoints, authentication and
> deployment hardening remain **not** implemented. The default HTTP app starts
> with an empty in-memory repository, so valid checks return `NEW` until a seeded
> or database-backed service is configured.

This component is owned by one member of a 10-member KAVACH group project. It is
built as a **standalone Python package** so it can be developed independently and
later mounted inside the shared KAVACH backend or deployed as a service.

The Phase 1 design lives in [`docs/duplicate_detection/`](./docs/duplicate_detection)
(architecture, API contract, matching policy, integration contract, implementation
plan). This README describes the Phase 2 foundation, the Phase 3 comparators and
the Phase 4 scoring engine (M3) and decision policy (M4). Their implementation
notes are in
[`scoring_engine.md`](./docs/duplicate_detection/scoring_engine.md),
[`phase4_decision_policy.md`](./docs/duplicate_detection/phase4_decision_policy.md)
and
[`embedding_comparator.md`](./docs/duplicate_detection/embedding_comparator.md).

## Purpose

The Duplicate Detection Agent receives a newly submitted civic complaint and
compares it against existing complaints to propose whether it is a `DUPLICATE`, a
`REVIEW_REQUIRED` case, or `NEW`. It is **advisory only** — it never deletes,
merges, or overwrites complaints.

## Phase 2 scope (what is implemented)

1. Pydantic **request schemas** (`Complaint`, `Location`) with input validation.
2. Pydantic **response schemas** (`DuplicateDetectionResponse`, `SignalResult`) and
   enums (`Decision`, `SignalStatus`).
3. A synchronous **repository abstraction** (`ComplaintRepository`) and an
   **in-memory implementation** (`InMemoryComplaintRepository`).
4. Deterministic **synthetic fixtures**.
5. **Provisional configuration** (weights and thresholds).
6. **Unit tests** for schemas, response, configuration and repository behaviour.

## Phase 3 scope (what is implemented)

Four independent **signal types** under `app/comparators/`, each returning a
shared `SignalResult` for one new complaint versus one candidate complaint:

- `CategoryComparator` — exact / compatible / incompatible / unknown categories.
- `TimeComparator` — exponential decay over the `reported_at` gap.
- `LocationComparator` — identifier precedence plus Haversine/coordinate decay.
- **Text** — one selectable backend: `EmbeddingTextComparator` (local sentence
  embeddings, default) or `TextComparator` (lexical TF-IDF + cosine,
  baseline/fallback).

The text backends are alternatives for the same `text` signal, not independent
signals. `build_core_comparators()` always returns exactly one `text` comparator,
and the existing `text` weight (`0.40`) is unchanged. See
[`embedding_comparator.md`](./docs/duplicate_detection/embedding_comparator.md).

Plus focused unit tests for each and a **cross-comparator contract** test suite
(`tests/test_comparator_contract.py`). See "Phase 3 — comparators" below.

## Phase 4 (M3) scope (what is implemented)

A deterministic, transport-free **weighted scoring engine** under
`app/scoring/engine.py`:

- `WeightedScoringEngine.score(...)` accepts the four core comparator
  `SignalResult`s (`text`, `location`, `category`, `time`) plus the existing
  `MatchingWeights`, and returns a `ScoringResult` with a combined ranking score
  in `[0, 1]` (or `None` when no positive-weight signal is usable).
- `UNAVAILABLE` / `INVALID` / `ERROR` signals are **excluded**, not treated as
  zero; the weighted average is renormalised over the available signals only.
- `ScoringResult.to_candidate_score(incident_id)` is the M3 → M4 adapter: the
  policy consumes its `CandidateScore` output unchanged.
- Signal conflict metadata (`details["conflict"]`, `details["conflict_code"]`) is
  preserved, and unweighted extras (e.g. a future `image`) remain available as
  evidence without affecting the score.

See "Phase 4 (M3) — weighted scoring engine" below and
[`docs/duplicate_detection/scoring_engine.md`](./docs/duplicate_detection/scoring_engine.md).

## Phase 4 (M4) scope (what is implemented)

A single, deterministic **decision policy** under `app/scoring/`:

- `DecisionPolicy.decide(candidates, *, retrieval_status=COMPLETE) -> DecisionOutcome`
  ranks valid candidates and applies the evidence, contradiction, ambiguity and
  threshold gates from the matching policy to emit `DUPLICATE` /
  `REVIEW_REQUIRED` / `NEW` with machine-readable reason codes.
- `CandidateScore` — the **M3 → M4 boundary**: one candidate's already-computed
  `score` plus its per-signal `SignalResult`s. This is a domain contract, not an
  HTTP schema. The M3 engine produces it through
  `ScoringResult.to_candidate_score()`; the policy is also independently testable.
- `RetrievalStatus` (`COMPLETE` / `INCOMPLETE` / `FAILED`) — the caller's statement
  of how complete the candidate search was. `NEW` is only allowed when retrieval
  was `COMPLETE`.
- `DecisionOutcome` — the policy result, with `to_response(complaint_id)` adapting
  it to the existing Phase 2 `DuplicateDetectionResponse`.

The policy **never** computes similarities, combines signals into a score,
retrieves candidates, touches storage/network/HTTP, or merges complaints. See
"Phase 4 (M4) — decision policy" below.

## M3 HTTP endpoint and Agent 3 response (what is implemented)

The FastAPI edge is implemented under `app/api/`, with the ASGI entry point at
`app/main.py`.

```text
POST /internal/v1/duplicate-detection/check
```

Processing flow:

```text
Agent 1 handoff JSON
  → to_complaint()                      (Agent 1 input adapter)
  → DuplicateDetectionService.check_detailed()
  → retrieval → comparators → weighted scoring → decision policy
  → app.api.mapper.to_m3_response()
  → Agent 3 eleven-field JSON response
```

The response always contains exactly:

`check_id`, `incident_id`, `decision`, `processing_status`, `policy_version`,
`checked_at`, `matched_incident_id`, `score`, `reason_codes`, `candidates`,
`error`.

Key semantics:

- `decision` is `NEW`, `DUPLICATE`, or `REVIEW_REQUIRED`; `processing_status` is
  `COMPLETED`, `PARTIAL`, or `FAILED`.
- `score` and candidate `similarity_score` are similarity/ranking values in
  `[0, 1]`, **not** confidence or probability.
- Candidates are ordered by descending `similarity_score`; only candidates that
  completed retrieval and scoring are returned.
- `NEW` always has `matched_incident_id=null` and `score=null`. Other decisions
  repeat the leading candidate, including `REVIEW_REQUIRED`.
- Partial or failed retrieval never produces `NEW`. It is reported as
  `REVIEW_REQUIRED` with the matching `processing_status`, a retrieval reason
  code, an `error` object, and any valid candidates that were scored.
- Completed, partial and failed duplicate checks return HTTP `200`. Invalid
  Agent 1 payloads return `422`; a timeout returns `504`; an unexpected failure
  with no trustworthy result returns `500`. A timeout/outage is never converted
  into a fabricated business result.
- The base repository defaults `retrieve_candidates()` to `PARTIAL`, so a new
  adapter cannot accidentally claim exhaustive retrieval.
  `InMemoryComplaintRepository` attests `COMPLETE`.

The full wire contract, invariants, examples and known deviations are in
[`m3_http_contract.md`](./docs/duplicate_detection/m3_http_contract.md). The
internal `check()` method still returns the original six-field
`DuplicateDetectionResponse`; `check_detailed()` is the M3 path.

Run the service locally:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The default app uses an empty in-memory repository, so a valid request returns
`NEW` with `NO_ELIGIBLE_CANDIDATES`. Inject a seeded
`DuplicateDetectionService` into `create_app(service=...)` for real or demo
candidates.

## Consolidation service (what is implemented)

When a database URL is configured, `app.main` builds a persistent runtime and
mounts five additive routes under `/internal/v1/consolidation`:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/complaints` | Store a complaint, run M3, and consolidate or queue a review. Requires `Idempotency-Key`. |
| `GET` | `/complaints/{complaint_id}` | Complaint plus its group or review state. |
| `GET` | `/groups` | Paginated group summaries; optional `status` filter. |
| `GET` | `/groups/{group_id}` | Group summary, canonical primary and duplicate members with link evidence. |
| `GET` | `/review-queue` | Paginated `REVIEW_REQUIRED` complaints; defaults to `OPEN`. |

Decision mapping:

- `NEW` → complaint becomes the primary of a new `OPEN` group (`PRIMARY` link).
- `DUPLICATE` → complaint joins the matched incident's group as a `DUPLICATE`
  link; `active_duplicate_count` and `historical_duplicate_count` increment
  atomically. If M3 matched an existing duplicate, the group's canonical
  primary is still used in responses.
- `REVIEW_REQUIRED` → a pending review is created. No link, no counter change,
  and the complaint is excluded from M3's candidate pool until resolved.

Every complaint remains stored; consolidation never deletes or merges records.
Successful ingestion returns `201`, including idempotent replays, which add
`Idempotent-Replay: true`. Reusing a key with a different payload returns `409
IDEMPOTENCY_KEY_REUSED`; reusing a complaint id with a different key returns
`409 COMPLAINT_ALREADY_EXISTS`.

The in-memory app remains the default: without `KAVACH_DATABASE_URL` or
`DATABASE_URL`, the consolidation routes are not mounted and `/check` keeps its
empty in-memory behaviour. `/check` is read-only in both modes.

Full design, data model, examples and limitations:
[`consolidation_service.md`](./docs/duplicate_detection/consolidation_service.md).

## Explicitly NOT implemented yet

- A shared-KAVACH repository adapter (the database is consolidated locally; it
  is not yet the team's system of record), blocking filters, or a retrieval
  window.
- Review resolution and group close/reopen endpoints. Pending reviews and
  `CLOSED` groups are modelled, but nothing transitions them yet.
- Verified PostgreSQL migration/concurrency behaviour. The migration and tests
  have only run against SQLite here; see the consolidation documentation.
- Image similarity (the `image_hash` signal) — no image hashing or image weight.
- Authentication, authorization, rate limiting, `/health`, timeouts and the
  production deployment topology for the HTTP edge.
- Frontend, PostGIS, external LLM APIs, a vector database/store, and response
  caching.
- Automatic runtime fallback from embeddings to TF-IDF. The backend is selected
  by configuration; model or inference failures return `ERROR` rather than
  silently switching algorithms.
- The Phase 1 six-field internal `candidates` / `search` / `policy` /
  `request_id` blocks. The Agent 3 wire response does expose `candidates` and
  `policy_version` through its own schema; the two contracts are intentionally
  separate.
- Calibration of thresholds, weights, embeddings and category/location maps
  against real labelled data.

## Folder structure

```
app/
  __init__.py
  main.py                   # ASGI entry point (uvicorn app.main:app)
  schemas/
    __init__.py
    complaint.py            # Complaint + Location input schemas and validation
    duplicate_response.py   # Decision/SignalStatus enums, SignalResult, response
    m3_response.py          # Agent 3 eleven-field wire schema and invariants
  repositories/
    __init__.py
    base.py                 # ComplaintRepository, RetrievalOutcome/CandidateRetrieval,
                            # RepositoryError, safe PARTIAL retrieval default
    in_memory.py            # InMemoryComplaintRepository (list/dict-backed, COMPLETE)
    synthetic.py            # deterministic synthetic fixtures
    consolidation.py        # group/link/review/request persistence + atomic counter update
    sql_complaint.py        # SQLAlchemy ComplaintRepository adapters
  db/
    __init__.py
    base.py                 # SQLAlchemy declarative Base
    models.py               # complaints, groups, links, reviews, idempotency requests
    session.py              # engine/session factory, SQLite foreign-key pragma
  config/
    __init__.py
    database.py             # KAVACH_DATABASE_URL / DATABASE_URL selection
    settings.py             # MatchingWeights, DecisionThresholds, ComparatorSettings,
                            # DecisionPolicySettings, Settings
  comparators/
    __init__.py             # exports the comparators, factory and shared helpers
    base.py                 # Comparator ABC + result builders (null-score invariant)
    category_comparator.py  # CategoryComparator
    time_comparator.py      # TimeComparator
    location_comparator.py  # LocationComparator (+ haversine_meters)
    text_comparator.py      # TextComparator (TF-IDF cosine; baseline/fallback)
    embedding_text_comparator.py  # EmbeddingTextComparator (local sentence embeddings)
    factory.py              # selects exactly one text backend; builds core comparators
  scoring/
    __init__.py             # exports the scoring engine, decision policy and types
    engine.py               # WeightedScoringEngine (M3), ScoringResult, ScoringError
    decision_policy.py      # DecisionPolicy (M4), CandidateScore, RetrievalStatus,
                            # DecisionOutcome, reason-code catalog
  adapters/
    __init__.py
    incident_payload.py     # Agent 1 handoff envelope -> existing Complaint model
  services/
    __init__.py             # exports DuplicateDetectionService, DetectionResult
    detection_service.py    # check() orchestration + check_detailed() M3 edge
    consolidation_errors.py # domain error codes and HTTP status hints
    consolidation_service.py # ingestion, idempotency, decision mapping, reads
  api/
    __init__.py
    app.py                  # create_app(service=..., consolidation_service=...),
                            # exception handlers, optional router mounting
    dependencies.py         # service dependency + DetailedDetectionService protocol
    consolidation_dependencies.py
    consolidation_router.py # /internal/v1/consolidation/*
    mapper.py               # DecisionOutcome -> Agent 3 wire response
    router.py               # POST /internal/v1/duplicate-detection/check
alembic/
  env.py                    # env-first URL resolution + metadata registration
  script.py.mako
  versions/0001_consolidation.py
alembic.ini
tests/
  conftest.py               # exact Agent 1 contract payload fixtures
  test_schemas.py           # schema, response and configuration tests
  test_repository.py        # repository + retrieval-completeness tests
  test_category_comparator.py
  test_time_comparator.py
  test_location_comparator.py
  test_text_comparator.py
  test_embedding_text_comparator.py  # offline fake-encoder tests
  test_comparator_factory.py         # factory + embedding-to-scoring integration
  test_comparator_contract.py  # cross-comparator contract tests
  test_incident_payload_adapter.py   # Agent 1 adapter contract tests
  test_detection_service.py          # in-process check() orchestration tests
  test_detection_service_detailed.py # check_detailed() + retrieval-completeness tests
  test_scoring_engine.py     # M3 weighted-scoring tests
  test_decision_policy.py    # M4 decision-policy tests
  test_m3_http.py            # Agent 3 HTTP contract tests
  test_consolidation.py      # consolidation service semantics/idempotency
  test_consolidation_api.py  # consolidation HTTP contract
  test_consolidation_migration.py # Alembic upgrade/downgrade/schema tests
scripts/
  evaluate_text_similarity.py  # illustrative TF-IDF vs embedding evaluation
conftest.py                 # adds project root to sys.path for pytest
requirements.txt
README.md
docs/duplicate_detection/   # Phase 1 design docs + later implementation notes
```

## Schema responsibilities

- **`app/schemas/complaint.py`** — `Location` (optional identifiers + coordinates;
  coordinates must be finite, in range, and supplied as a pair) and `Complaint`
  (required non-empty `complaint_id`; optional `description`, `category`,
  `location`, timezone-aware `reported_at`, `image_hash`). Blank optional strings
  normalise to `None`; missing values stay missing. Unknown extra fields are
  rejected, so an integration mapping layer should translate KAVACH field names
  first.
- **`app/adapters/incident_payload.py`** — translates the draft Agent 1
  duplicate-detection handoff envelope into `Complaint`. It consumes the
  canonical handoff keys, drops the documented `kavach_agent1` context, and
  rejects raw upstream names such as `incident_id`, `complaint_text`,
  `incident_summary` and `created_at`. See
  [`docs/duplicate_detection/m2_input_adapter.md`](docs/duplicate_detection/m2_input_adapter.md).
- **`app/schemas/duplicate_response.py`** — `Decision` (`DUPLICATE`,
  `REVIEW_REQUIRED`, `NEW`), `SignalStatus` (`AVAILABLE`, `UNAVAILABLE`, `INVALID`,
  `ERROR`), reusable `SignalResult`, and `DuplicateDetectionResponse`. A score, when
  present, must be finite and in `[0, 1]`. A non-`AVAILABLE` signal must have a
  `null` score — **missing evidence is never represented as `0`**.

### Field-name assumptions

Field names (`complaint_id`, `category`, `location_id`, `reported_at`, `image_hash`)
are the proposed **V1** placeholders from the Phase 1 contract. They may need mapping
to KAVACH's canonical names at integration time. See
`docs/duplicate_detection/integration.md`.

## Repository abstraction and future integration

`ComplaintRepository` (`app/repositories/base.py`) is a small synchronous interface:

```python
add(complaint)                      # raises RepositoryError on duplicate id
add_many(complaints)
get_by_id(complaint_id) -> Complaint | None
list_candidates(exclude_complaint_id=None) -> list[Complaint]
retrieve_candidates(exclude_complaint_id=None) -> CandidateRetrieval
count() -> int
```

- It **stores and returns** records only. It never scores similarity, never decides
  duplicates, and never mutates/deletes/merges.
- A **legitimate empty result** is an empty list; a **failure** raises
  `RepositoryError`. These are never conflated.
- Methods are **synchronous** because the prototype is in-memory with no I/O; a
  network adapter can introduce an async variant behind the same conceptual
  contract (Phase 1, `architecture.md` §3, Integration Option B).
- The implementation is **replaceable**: a future adapter (PostgreSQL, or an HTTP
  client to a shared KAVACH data source) can implement the same interface without
  changing the (later) comparison algorithms, because nothing in the interface
  exposes storage details.

`InMemoryComplaintRepository` stores records in a dict keyed by `complaint_id`,
returns **deep copies** so callers cannot mutate internal state, excludes the
incoming complaint id from `list_candidates`, and returns records sorted by
`complaint_id` for deterministic tests.

`retrieve_candidates()` is the completeness-aware path used by the M3 edge. It
returns a `CandidateRetrieval` carrying a `RetrievalOutcome`:

- `COMPLETE` — the repository guarantees the candidate set is exhaustive.
- `PARTIAL` — candidates were returned but completeness is not guaranteed.
- `FAILED` — retrieval failed; the result carries a `RetrievalFailure`.

The base implementation defaults to `PARTIAL` with
`RETRIEVAL_COMPLETENESS_UNKNOWN`, so a new adapter cannot accidentally claim
exhaustive retrieval. `InMemoryComplaintRepository` overrides it to `COMPLETE`.
`check()` still uses `list_candidates()`; `check_detailed()` uses
`retrieve_candidates()` for the Agent 3 path.

## Synthetic data

`app/repositories/synthetic.py` provides `synthetic_incidents()` — a small,
deterministic, **fictional** set including a waste overflow at a main entrance, a
differently worded report of the same overflow, a blocked drainage complaint, a
broken streetlight elsewhere, two road-damage reports at the same location with
different timestamps, and a record with all optional fields missing. It is for
tests only and **must not** be used to claim model accuracy.

## Configuration

`app/config/settings.py` holds provisional policy values:

| Setting | Value | Status |
| --- | --- | --- |
| weights.text | 0.40 | provisional |
| weights.location | 0.30 | provisional |
| weights.category | 0.15 | provisional |
| weights.time | 0.15 | provisional |
| thresholds.high | 0.85 | provisional |
| thresholds.low | 0.55 | provisional |
| tie_margin | 0.05 | provisional |
| comparators.text_backend | embedding | provisional default; `tfidf` is the baseline/fallback |
| comparators.embedding_model | sentence-transformers/all-MiniLM-L6-v2 | initial candidate |
| comparators.time_decay_scale_seconds | 172800 (48 h) | provisional |
| comparators.location_distance_scale_m | 500 | provisional |
| comparators.category_compatible_score | 0.60 | provisional |
| comparators.category_map | sample groups/pairs | placeholder |
| decision.min_available_signals | 2 | provisional |
| decision.require_core_anchor | True | provisional |
| decision.core_anchor_floor | 0.50 | provisional |
| decision.supportive_floor | 0.50 | provisional |
| decision.require_corroboration | True | provisional |
| decision.location_conflict_text_floor | 0.80 | provisional |
| decision.location_conflict_location_ceiling | 0.20 | provisional |

These are **initial hypotheses from the project specification and have not been
validated against labelled data.** Weights must be non-negative with a positive sum;
`high` must exceed `low`. `tie_margin` must be finite and `≥ 0`; the decision
floors/ceilings must be finite and in `[0, 1]`, and
`location_conflict_location_ceiling` must be below `location_conflict_text_floor`.
The comparator values are described in the Phase 3 section below; the `decision.*`
values are described in the Phase 4 (M4) section. `text_backend` selects exactly
one `text` signal and `embedding_model` is loaded lazily (and downloaded on first
use unless cached). No KAVACH-specific environment-variable configuration is used
(Phase 1 did not require it).

## Phase 3 — comparators

Each comparator compares a **new complaint** against one **candidate complaint**
and returns a single `SignalResult`. Comparators are *pure*, *deterministic* and
*advisory*: they never mutate complaints and never decide `DUPLICATE` / `NEW` /
`REVIEW_REQUIRED`. The weighted combination and the decision policy are
implemented in Phase 4 (`app/scoring/`).

### Common output format

Every comparator exposes:

```python
comparator.compare(complaint, candidate) -> SignalResult
```

and each also has a field-level entry point (`compare_categories`,
`compare_timestamps`, `compare_locations`, `compare_texts`) for direct and
malformed-input testing. `SignalResult` is reused from Phase 2:

| Field | Meaning |
| --- | --- |
| `status` | `AVAILABLE` \| `UNAVAILABLE` \| `INVALID` \| `ERROR` |
| `score` | finite `[0, 1]` **only** when `AVAILABLE`; otherwise `None` |
| `reason` | short machine-readable reason code |
| `details` | structured evidence (basis, distance, conflict flag, …) |

Evidence taxonomy (uniform across all four):

- **`UNAVAILABLE`** — the input was absent, so there is nothing to compare.
  Missing evidence is **never** coerced to a score of `0`.
- **`INVALID`** — the input was present but unusable (malformed), which is kept
  distinct from an ordinary low-similarity `AVAILABLE` score.
- **Conflicts** — when authoritative identifiers contradict, the signal stays
  `AVAILABLE` with score `0.0` and `details["conflict"] is True` plus a
  `details["conflict_code"]`; any contradictory coordinate distance is preserved
  alongside it for Phase 4.

### Per-comparator summary

- **CategoryComparator** (`category_comparator.py`) — normalises (trim + case-fold)
  then classifies: exact match → `1.0`; known-compatible pair → configured partial
  score (`0.60`); known-incompatible pair → `0.0` with a conflict flag; unknown
  relationship or missing category → `UNAVAILABLE`; non-string input → `INVALID`.
  The mapping lives in configuration (`CategoryCompatibilityMap`), so KAVACH's real
  taxonomy can replace the fictional sample without editing the comparator. Unknown
  pairs are `UNAVAILABLE` on purpose: the real vocabulary is not yet agreed, so we
  neither reward nor penalise a pair we cannot classify.
- **TimeComparator** (`time_comparator.py`) — `score = exp(-gap_seconds /
  decay_scale_seconds)`. Requires timezone-aware timestamps; different offsets
  representing the same instant score `1.0`; the score never increases with the
  gap. Missing → `UNAVAILABLE`; naive/malformed → `INVALID`.
- **LocationComparator** (`location_comparator.py`) — documented precedence:
  matching `location_id` (checking `facility_id` context) → matching `facility_id`
  → coordinate proximity. Missing identifiers are **not** a mismatch; differing
  *present* identifiers are surfaced as conflicts.
- **Text signal** — one selectable backend, never both:
  - **`TextComparator`** (`text_comparator.py`) — lexical TF-IDF + cosine
    similarity; retained as the baseline/fallback.
  - **`EmbeddingTextComparator`** (`embedding_text_comparator.py`) — local
    sentence-embedding cosine similarity; the default.

### How the text backends work (high level)

#### TF-IDF backend

For each pair, a fresh `TfidfVectorizer` is fitted to the **two** descriptions.
Each description becomes an L2-normalised TF-IDF vector; the cosine of the two
vectors is the score. TF-IDF weights a word by how often it appears in a document
(*term frequency*) and how rare it is across the fitted documents (*inverse
document frequency*), so ordinary filler words contribute less than distinctive
ones. The score is **lexical**: it rewards shared exact tokens, not meaning.

Because the vectorizer is fitted **pair-locally**, IDF weights are not comparable
across different candidate comparisons and each pair is a separate vectorisation.
This is acceptable for the first prototype; a production implementation should fit
a **shared corpus** (or use a retrieval index) for consistent weighting and
efficient candidate search. The TF-IDF backend uses no external API, model
download or vector store.

#### Embedding backend

The embedding backend encodes both descriptions with a local
`sentence-transformers` model (default `all-MiniLM-L6-v2`), L2-normalises the
vectors and computes their dot product (cosine similarity). It can recognise
paraphrases that share no tokens. The model is loaded lazily **once per process**
and cached; it is never rebuilt per comparison. The first use downloads it unless
it is already cached. No external inference API or vector database is used.

A successful comparison returns `AVAILABLE` with `TEXT_EMBEDDING_SIMILARITY`.
Missing text stays `UNAVAILABLE`, non-string text is `INVALID`, and model load,
inference or malformed-output failures return `ERROR`; none of these become a
score of `0.0`. Negative cosine values are floored to `0.0` only for the public
`[0, 1]` score and the raw value is retained in evidence. TF-IDF and embedding
scores have different distributions, so the provisional thresholds must not be
assumed to transfer between backends. See
[`embedding_comparator.md`](./docs/duplicate_detection/embedding_comparator.md)
for the full status table, cache lifecycle and illustrative evaluation.

### How the Haversine calculation is used

`haversine_meters(lat1, lon1, lat2, lon2)` returns the great-circle distance in
metres using Earth's mean radius of 6,371,000 m. Coordinates are re-validated
inside the comparator (finite, in range, supplied as a pair) so malformed values
are caught even if they bypassed the schema. The distance maps to a score with a
**configurable linear decay**: `clamp(1 - distance_m / distance_scale_m, 0, 1)`, so
identical points score `1.0` and the score decreases monotonically with distance.

### Missing and invalid evidence

- Missing optional fields never raise and never become `0` — they become
  `UNAVAILABLE` with `score = None`.
- Present-but-unusable input (naive timestamp, non-string category/description,
  out-of-range/NaN coordinates, lone coordinate) becomes `INVALID` with
  `score = None`.
- Only genuine programming errors (e.g. a non-finite computed score) raise.

### Provisional configuration

| Setting | Default | Notes |
| --- | --- | --- |
| `time_decay_scale_seconds` | `172800` | 48 h exponential scale |
| `location_distance_scale_m` | `500` | linear distance scale (metres) |
| `category_compatible_score` | `0.60` | score for a known-compatible pair |
| `category_map` | sample data | **placeholder** — replace with the real taxonomy |
| `text_backend` | `embedding` | `embedding` (default) or `tfidf` (baseline/fallback) |
| `embedding_model` | `all-MiniLM-L6-v2` | local sentence-transformer model identifier |

All are **provisional**. The distance scale does **not** mean "within the radius ⇒
duplicate"; that judgement belongs to Phase 4. Comparators read configuration at
construction time; the embedding backend also keeps a process-local model cache
that does not alter evidence semantics.

### Running the comparator tests

```powershell
python -m pytest tests\test_category_comparator.py -q
python -m pytest tests\test_time_comparator.py -q
python -m pytest tests\test_location_comparator.py -q
python -m pytest tests\test_text_comparator.py -q
python -m pytest tests\test_embedding_text_comparator.py -q
python -m pytest tests\test_comparator_factory.py -q
python -m pytest tests\test_comparator_contract.py -q
# or everything:
python -m pytest -q
```

The embedding-comparator and factory tests inject fake encoders, so they do not
download the model or require network access.

### Known limitations

- **Text backends have different limits.** The TF-IDF backend is lexical only and
  cannot recognise paraphrases or synonyms ("broken streetlight" vs "lamp not
  working" scores `0.0`). The default embedding backend handles many paraphrases,
  but its scores are not calibrated to the provisional thresholds. In the
  illustrative 40-pair evaluation, all 10 hard negatives were false positives at
  `0.50` for both backends because they differ by location/entity, which text
  alone cannot resolve. The full agent must also use location, category and time.
  See
  [`embedding_comparator.md`](./docs/duplicate_detection/embedding_comparator.md).
- **Embedding cold start and truncation.** First use downloads the model (about
  90 MB) unless cached, and a cold process load took about 22 s in this
  environment. The default model truncates at 256 word pieces, and the cache is
  process-local. A production deployment should pre-provision the model, pin its
  revision and batch/co-locate inference.
- **Pair-local fitting (TF-IDF).** IDF weights are not comparable across
  candidate comparisons; a shared corpus/retrieval index is a production concern.
- **Shared stopwords (TF-IDF).** Common words ("the") are not removed by default,
  so two unrelated sentences can share a small nonzero score. An optional
  `stop_words` argument is available (e.g. `"english"`), but it is
  language-specific.
- **Single backend, no automatic fallback.** Switching to TF-IDF is a
  configuration change, not a runtime failover. Model or inference failures stay
  `ERROR` so they are visible and are not mistaken for low lexical similarity.
- **Category map is fictional.** The sample groups/pairs are placeholders.
- **Scales are unvalidated.** Time and distance decay scales are guesses, and the
  embedding backend's score distribution differs from TF-IDF's.

### What remains after Phase 4

The M3 scoring engine, M4 decision policy, Agent 1 input adapter, orchestration
service and Agent 3 M3 HTTP endpoint are implemented, and the text signal now has
selectable embedding and TF-IDF backends. Remaining work is the production
candidate repository (and its completeness attestation), the optional image
signal and its weight, HTTP hardening (auth, rate limits, `/health`, timeouts,
deployment), and calibration/validation of the embedding backend and thresholds
on real labelled data. The repository/image work does not change the scoring
formula or the policy gates; threshold calibration is a separate, explicit task.

## Phase 4 (M3) — weighted scoring engine

`app/scoring/engine.py` implements `WeightedScoringEngine`. It is pure,
deterministic, side-effect free and transport-free. It never retrieves candidates,
computes similarities, decides an outcome, or touches storage/network/HTTP.

### Formula and missing evidence

```
score = Σ(w_i × s_i) / Σ(w_i)   for every signal with status == AVAILABLE and w_i > 0
```

- The default weights are the existing `MatchingWeights`: `text 0.40`,
  `location 0.30`, `category 0.15`, `time 0.15`.
- `UNAVAILABLE`, `INVALID` and `ERROR` signals are excluded from **both** the
  numerator and the denominator. They are never treated as a score of `0`.
- The denominator is therefore the sum of the **available** weights, which
  renormalises partial evidence (for example text-only evidence is divided by
  `0.40`, not `1.0`).
- If no `AVAILABLE` signal has a positive configured weight, `score` is `None`;
  the candidate is not rankable. A signal with weight `0.0` is retained as
  evidence but cannot create a score.
- Unweighted extras (for example a future `image` signal) are retained in the
  result and passed to M4 but never affect the score.

### Interface

```python
from app.scoring import DecisionPolicy, WeightedScoringEngine

engine = WeightedScoringEngine()          # or WeightedScoringEngine(settings.weights)
result = engine.score(                    # mapping form also accepted
    text=text_signal,
    location=location_signal,
    category=category_signal,
    time=time_signal,
    extra_signals={"image": image_signal},  # optional, unweighted
)
candidate = result.to_candidate_score("CMP-123")
outcome = DecisionPolicy().decide([candidate])
```

All four core signals are required. They may be passed either as a mapping or as
the four keyword arguments, not both. Extra signal names must not collide with a
core name.

`ScoringResult` is a frozen domain dataclass:

| Field | Meaning |
| --- | --- |
| `score` | Weighted ranking score in `[0, 1]`, or `None` when unscorable. |
| `signals` | Every input signal, core names first, then extras sorted by name. |
| `available_scores` | Scores of all `AVAILABLE` signals, including unweighted extras. |
| `configured_weights` | Configured weights for the four core signals. |
| `weights_used` | Effective weights (`configured weight / available weight sum`) for contributing signals. |
| `contributions` | Each contributing signal's share of the final score. |
| `weighted_sum`, `weight_total` | Numerator and denominator before division. |
| `configured_weight_total` | Sum of all configured core weights, including zeros. |
| `normalised` | Whether the denominator is smaller than the configured total. |
| `contradictions` | Comparator conflict codes in deterministic signal order. |
| `reasons` | Engine reason codes (below). |

`to_candidate_score(incident_id)` is a thin adapter to the existing
`CandidateScore`; it does not change or reinterpret the score.

### Validation, immutability and conflicts

- `AVAILABLE` scores must be real, finite numbers in `[0, 1]`; booleans,
  strings, `NaN`, `±inf`, out-of-range values and `model_construct` bypasses are
  rejected with `ScoringError`.
- Weights are re-validated: finite, non-negative, numeric, with a positive sum.
- Non-`AVAILABLE` signals must carry a `None` score.
- Inputs are never mutated, and result mappings are read-only.
- `details["conflict"]` and `details["conflict_code"]` are preserved on the
  per-signal evidence, and their codes are copied into `ScoringResult.contradictions`
  for M4. Material contradiction rules remain M4's responsibility.

### Engine reason codes

`WEIGHTED_SCORE_COMPUTED`, `WEIGHTED_SCORE_UNAVAILABLE`,
`NO_AVAILABLE_SIGNAL`, `NO_POSITIVE_WEIGHT_SIGNAL`,
`SCORE_RENORMALISED_FOR_AVAILABLE_WEIGHTS`, `ZERO_WEIGHT_SIGNAL_IGNORED`,
`UNWEIGHTED_SIGNAL_PRESENT`, `CONFLICT_METADATA_PRESENT`.
Treat this as an open, additive set.

### Running the scoring-engine tests

```powershell
python -m pytest tests\test_scoring_engine.py -q
```

## Phase 4 (M4) — decision policy

`app/scoring/decision_policy.py` implements **only** the decision policy: mapping
already-computed candidate evidence to an outcome. It is deterministic, pure, and
side-effect free — it never mutates its inputs and never retrieves data.

### Ranking vs deciding

- The **score** is a *ranking* score in `[0, 1]`. It is **not** a calibrated
  probability, and the policy never describes it as one.
- A candidate's score is computed by the **scoring engine (M3)** and handed to the
  policy inside `CandidateScore`.
- The **decision** is a separate, explicit judgement made here from the score,
  the per-signal evidence and the retrieval completeness. A high score alone does
  **not** establish `DUPLICATE`.

### Input contract (the M3 → M4 boundary)

```python
CandidateScore(
    incident_id: str,
    score: float | None,                 # combined ranking score, or None
    signals: Mapping[str, SignalResult], # per-signal evidence
    contradictions: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
)
```

This is a **domain contract, not an HTTP schema**. The M3 engine produces it via
`ScoringResult.to_candidate_score()` (a thin mapping layer); the policy stays
unchanged.

### Decision meanings

| Outcome | Meaning |
| --- | --- |
| `DUPLICATE` | Best candidate clears the high threshold **and** the evidence, contradiction, corroboration and ambiguity gates. Sets `matched_incident_id`. |
| `REVIEW_REQUIRED` | Borderline, contradictory, ambiguous, under-evidenced, invalid-scored, or the candidate search was not complete. `matched_incident_id` stays `None`; the top candidate is surfaced via `DecisionOutcome.leading_candidate_id` / `candidates` for a human. |
| `NEW` | No candidate cleared the low threshold, with sufficient evidence and a complete search. `matched_incident_id` and `score` are `None`. |

### Gate order (from `matching_policy.md` §6.4)

Applied to the best candidate (valid candidates ordered by score descending):

1. any candidate with an invalid/non-finite/out-of-range test score → `REVIEW_REQUIRED`
   (`INVALID_SCORE`) — never `DUPLICATE`, never `NEW`;
2. no candidates → `NEW` if retrieval `COMPLETE`, else `REVIEW_REQUIRED`;
3. candidates exist but none is scoreable → `REVIEW_REQUIRED` (`INSUFFICIENT_EVIDENCE`);
4. fewer than `min_available_signals` available → `REVIEW_REQUIRED` (`INSUFFICIENT_EVIDENCE`);
5. no core anchor (text or location) → `REVIEW_REQUIRED` (`MISSING_CORE_ANCHOR`);
6. a material contradiction → `REVIEW_REQUIRED` (`CONTRADICTION_*`);
7. too few supportive signals → `REVIEW_REQUIRED` (`INSUFFICIENT_EVIDENCE`);
8. top two candidates within `tie_margin` → `REVIEW_REQUIRED` (`AMBIGUOUS_TIED_CANDIDATES`);
9. `score ≥ thresholds.high` → `DUPLICATE` (`SCORE_ABOVE_HIGH_THRESHOLD`);
10. `score ≥ thresholds.low` → `REVIEW_REQUIRED` (`SCORE_BETWEEN_THRESHOLDS`);
11. otherwise → `NEW` (`SCORE_BELOW_LOW_THRESHOLD`), **blocked to `REVIEW_REQUIRED`**
    if retrieval was not `COMPLETE`.

### Missing, invalid and conflicting evidence

- `UNAVAILABLE` / `INVALID` signals are never `0`; they are excluded from the
  evidence counts. A `None` combined score is legitimate when the M3 engine could
  not form a positive-weight average — normally because no signal is `AVAILABLE`.
  A candidate with available evidence but no positive-weight usable signal also
  yields `None`; if such a candidate reaches the policy, it is reported as
  `INVALID_SCORE` rather than silently treated as `NEW`.
- Non-finite (`NaN`, `±inf`) or out-of-`[0, 1]` scores, and malformed signal
  objects, can never yield `DUPLICATE`; they yield `REVIEW_REQUIRED` with
  `INVALID_SCORE`.
- Material contradictions are **not** averaged away:
  - `text ≥ location_conflict_text_floor` **and** `location ≤
    location_conflict_location_ceiling` (both `AVAILABLE`) → `CONTRADICTION_LOCATION_MISMATCH`;
  - a category conflict flag → `CONTRADICTION_CATEGORY_INCOMPATIBLE`;
  - a location identifier/facility conflict flag → `CONTRADICTION_LOCATION_MISMATCH`.
  The comparator-specific code (`LOCATION_IDENTIFIER_CONFLICT`, `LOCATION_FACILITY_CONFLICT`,
  `CATEGORY_INCOMPATIBLE`) is retained on the per-candidate summary.
- **Absent optional identifiers are not a conflict** — a coordinate-only location
  match is treated as agreement, not disagreement.

### Ambiguity (ties)

Valid candidates are ranked by score descending with documented, reproducible
tie-breakers (higher location, then text, then time signal; then ascending
`incident_id`). The sort itself is **presentation-only** and never invents a
decision. If the top two are closer than `tie_margin` (default `0.05`), the
outcome is `REVIEW_REQUIRED` (`AMBIGUOUS_TIED_CANDIDATES`).

### Reason codes

`SCORE_ABOVE_HIGH_THRESHOLD`, `SCORE_BETWEEN_THRESHOLDS`, `SCORE_BELOW_LOW_THRESHOLD`,
`INSUFFICIENT_EVIDENCE`, `MISSING_CORE_ANCHOR`, `CONTRADICTION_LOCATION_MISMATCH`,
`CONTRADICTION_CATEGORY_INCOMPATIBLE`, `AMBIGUOUS_TIED_CANDIDATES`,
`NO_ELIGIBLE_CANDIDATES`, `INVALID_SCORE`, `CANDIDATE_RETRIEVAL_INCOMPLETE`,
`CANDIDATE_RETRIEVAL_FAILED`. Treat this as an open, additive set.

### Provisional assumptions (documented, not validated)

- Thresholds (`high 0.85`, `low 0.55`), `tie_margin` (`0.05`) and the `decision.*`
  floors are **hypotheses**, not tuned values.
- **M3 weights and M4 thresholds are provisional.** `CandidateScore.score` is
  produced by the scoring engine using the configured weights; both the weights
  and the decision values are untuned hypotheses.
- The M4 policy reuses the Phase 2 response schema; a `REVIEW_REQUIRED` outcome
  never asserts a match (`matched_incident_id` is `None`), and the leading
  candidate is exposed only as a suggestion for a human.
- Ambiguity is checked before the threshold bands, so two near-equal low-scoring
  candidates go to review rather than `NEW`. `NEW` also requires adequate evidence
  for the best candidate (`matching_policy.md` §6.4 applied literally).

### Running the decision-policy tests

```powershell
python -m pytest tests\test_decision_policy.py -q
```

## Install and run tests (Windows PowerShell)

```powershell
cd "C:\Users\dadla\OneDrive\Documents\Default Project\Kavach-epam"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# Optional: pre-download the default embedding model (~90 MB) so the first
# real comparison does not pay the download/cold-start cost.
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

python -m pytest -q
```

The unit tests (including the embedding-comparator suite) inject fake encoders
and do **not** download the model or require network access. The optional model
download is only needed for real comparisons and the evaluation script.

Run the M3 HTTP service:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
$body = @'
{
  "complaint_id": "INC-2026-001",
  "description": "Garbage is overflowing near the public park entrance.",
  "category": "WASTE_OVERFLOW",
  "location": {
    "facility_id": null,
    "location_id": null,
    "latitude": 23.2599,
    "longitude": 77.4126
  },
  "reported_at": "2026-10-31T18:30:00+05:30",
  "image_hash": "a1b2c3d4e5f6"
}
'@
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/internal/v1/duplicate-detection/check" `
  -ContentType "application/json" `
  -Body $body
```

The default app has an empty in-memory repository, so a valid request returns
`NEW` with `NO_ELIGIBLE_CANDIDATES`. Build `create_app(service=...)` with a
seeded `DuplicateDetectionService` for demo candidates.

### Database-backed consolidation runtime

Configure a database and apply the migration before starting the service:

```powershell
$env:KAVACH_DATABASE_URL = "postgresql+psycopg2://kavach:secret@localhost:5432/kavach"
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For a throwaway local demo, SQLite works too:

```powershell
$env:KAVACH_DATABASE_URL = "sqlite:///./kavach_local.db"
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Ingest a complaint (the body is the same Agent 1 handoff envelope used by
`/check`):

```powershell
$headers = @{ "Idempotency-Key" = "req-2026-001" }
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/internal/v1/consolidation/complaints" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Inspect the resulting group and review queue:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/internal/v1/consolidation/groups"
Invoke-RestMethod "http://127.0.0.1:8000/internal/v1/consolidation/review-queue"
```

The same `Idempotency-Key` with the same payload replays the stored response
and sets `Idempotent-Replay: true`. Reusing it with different content returns
`409 IDEMPOTENCY_KEY_REUSED`. See
[`consolidation_service.md`](./docs/duplicate_detection/consolidation_service.md)
for the full API and known limitations.

After the model is cached, compare the two text backends on the synthetic
evaluation set:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
python scripts/evaluate_text_similarity.py --local-files-only
```

The results are **illustrative only**; the pairs are hand-written and the
repository has no production labelled dataset. See
[`embedding_comparator.md`](./docs/duplicate_detection/embedding_comparator.md).

If PowerShell blocks activation, run `.\.venv\Scripts\python.exe -m pytest -q`
instead of activating.

## How the repository will be replaced later

1. Implement the same `ComplaintRepository` interface in a new module
   (e.g. `app/repositories/postgres.py` or `app/repositories/kavach_client.py`).
2. Inject it wherever the (future) `DuplicateDetectionService` is constructed — no
   comparator or policy code changes.
3. If the data source is remote and latency-bound, either keep the sync interface
   over a sync HTTP client, or introduce an async interface as a parallel variant.

## Assumptions and open items

- **M3 is implemented** in `app/scoring/engine.py`, with a documented naming
  reconciliation: `matching_policy.md` §5 calls the component `ScoringPolicy`,
  while the implementation (and this README) call it `WeightedScoringEngine`; the
  exception name `ScoringError` is shared. `matching_policy.md` §1 also sketches
  `SignalResult.name` / `weight` / `contradiction` fields, whereas the code uses
  mapping keys and `details` for conflicts. See
  [`scoring_engine.md`](./docs/duplicate_detection/scoring_engine.md).
- **The embedding text backend is implemented** in
  `app/comparators/embedding_text_comparator.py` and selected by default through
  `build_core_comparators()`; TF-IDF remains selectable as the baseline/fallback.
  It is integrated through the comparator factory and the M3 HTTP service; model,
  thresholds and evaluation are not production-validated. See
  [`embedding_comparator.md`](./docs/duplicate_detection/embedding_comparator.md).
- **Known time-decay discrepancy:** `matching_policy.md` §4.4 specifies a
  `0.10` decay floor, but `app/comparators/time_comparator.py` uses a plain
  exponential decay without a floor. This is unchanged by M3 and remains a
  specification question for the team.
- No shared KAVACH repository or other members' modules were available; this was
  built from the Phase 1 specification in this workspace.
- `image_hash` receives provisional validation only (non-empty, ≤ 128 chars); its
  exact format remains a team decision.
- The category compatibility mapping is implemented as a **placeholder** sample
  (`CategoryCompatibilityMap`); the canonical category and location vocabularies
  remain team decisions to be substituted into configuration.
- Field names are V1 placeholders pending team agreement.
- **Consolidation defaults are approved but unvalidated at scale:** pending
  `REVIEW_REQUIRED` complaints are excluded from M3's candidate pool until a
  human resolves them; no review-resolution or group close/reopen endpoints
  exist yet, so ownership of that lifecycle is unresolved.
- **PostgreSQL behaviour is unverified.** The consolidation migration and
  concurrency tests ran against SQLite only; the atomic counter SQL is portable
  but row-locking/isolation must be verified on the target PostgreSQL version.
- **ID formats differ.** Group, link, review and idempotency ids are generated
  UUID4 strings while complaint ids stay the opaque 1–64 character string from
  the Agent 1 contract. Agent 3's UUID preference is still a team decision.
- **Idempotency records grow without bound.** `consolidation_requests` has no
  retention or cleanup policy yet.
- Agent 1's receiver-side policy remains provisional under `[A1-SIGNOFF]`.
