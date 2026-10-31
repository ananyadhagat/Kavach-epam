# Duplicate Detection Agent — Implementation Plan

> **Historical Phase 1 plan.** This document is retained as the original ordered plan
> and design rationale. The current prototype is implemented under `app/`; see
> [`service_orchestration.md`](./service_orchestration.md) for the actual module map and
> status. Statements below such as "not implemented yet" or "no embeddings" describe the
> Phase 1 starting point and are superseded by the implementation notes.

## 1. Proposed module structure (historical Phase 1 proposal)

The tree below is the **original proposed layout**, not the current repository layout.
It is retained to explain the Phase 1 design. Current code lives under `app/` and is
mapped in [`service_orchestration.md`](./service_orchestration.md).

```
proposed_package/
├── __init__.py                # package marker; exports DuplicateDetectionService
├── api/
│   ├── __init__.py
│   ├── routes.py              # FastAPI router: POST /api/v1/duplicate-detection/check, GET .../health
│   └── dependencies.py        # wires settings + repository + service (fastapi Depends); ONLY place FastAPI objects are built
├── schemas/
│   ├── __init__.py
│   ├── enums.py               # Decision, SignalStatus, SignalName enums (shared, transport-free)
│   ├── request.py             # Pydantic request models + field/coordinate/timestamp validators
│   └── response.py            # Pydantic response models + error envelope
├── service/
│   ├── __init__.py
│   ├── detection_service.py   # DuplicateDetectionService: orchestrates retrieve → compare → score → decide
│   ├── candidate_retriever.py # CandidateRetriever: eligibility + optional coarse blocking
│   └── models.py              # domain objects: DetectionRequest, DetectionResult, IncidentRecord, ScoredCandidate, SignalResult
├── comparators/
│   ├── __init__.py
│   ├── base.py                # Comparator protocol: compare(a, b) -> SignalResult
│   ├── text.py                # TextComparator (TF-IDF + cosine)
│   ├── location.py            # LocationComparator (identifier → facility → Haversine)
│   ├── category.py            # CategoryComparator (exact + compatibility map)
│   ├── time.py                # TimeComparator (decay-with-floor)
│   └── image_hash.py          # ImageHashComparator (optional, disabled by default)
├── policy/
│   ├── __init__.py
│   ├── scoring.py             # ScoringPolicy: weight normalisation over available signals (pure)
│   └── decision.py            # HybridDecisionPolicy: thresholds, evidence gates, contradictions, ties (pure)
├── repository/
│   ├── __init__.py
│   ├── base.py                # IncidentRepository ABC/Protocol + RepositoryError; CandidateFilter
│   ├── in_memory.py           # InMemoryIncidentRepository (Phase 2 prototype)
│   └── seed_data.py           # synthetic records used by tests/demo
├── config/
│   ├── __init__.py
│   ├── settings.py            # weights, thresholds, radii, decay params, policy_version (env-overridable)
│   └── category_map.py        # data-driven category compatibility table (placeholder in V1)
└── tests/
    ├── unit/
    │   ├── test_text_comparator.py
    │   ├── test_location_comparator.py
    │   ├── test_category_comparator.py
    │   ├── test_time_comparator.py
    │   ├── test_scoring_policy.py
    │   ├── test_decision_policy.py
    │   ├── test_candidate_retriever.py
    │   └── test_repository.py
    ├── integration/
    │   └── test_detection_scenarios.py    # the 17 scenarios in §5
    └── api/
        └── test_routes.py                 # FastAPI TestClient: contract, 200/422/500 mapping
```

### Per-file responsibility

| Path | Responsibility |
| --- | --- |
| `api/routes.py` | Transport only: parse/validate to domain objects, call the service, map results to HTTP + response models. No business logic. |
| `api/dependencies.py` | Single wiring point: build `Settings`, `InMemoryIncidentRepository`, comparators, policies, service. Keeps FastAPI imports out of the core. |
| `schemas/enums.py` | Enumerations shared by edge and core; no framework dependency. |
| `schemas/request.py` | Request models + validators (coordinate pairing/ranges, timestamp offset, string lengths). |
| `schemas/response.py` | Response models + `ErrorEnvelope`. Mirrors `api_contract.md` exactly. |
| `service/models.py` | Plain domain dataclasses consumed by the core; keeps the core independent of Pydantic transport models. |
| `service/detection_service.py` | Orchestration: retrieve candidates, run comparators per candidate, call scoring and decision policies, assemble `DetectionResult`. |
| `service/candidate_retriever.py` | Eligibility (self-exclusion) and optional coarse blocking; distinguishes empty result from `RepositoryError`. |
| `comparators/base.py` | The `Comparator` protocol so comparators are interchangeable and independently testable. |
| `comparators/*.py` | One pure function/class per signal; no repository or HTTP access. |
| `policy/scoring.py` | Weight normalisation over available signals; pure function; rejects non-finite scores. |
| `policy/decision.py` | Evidence gates, thresholds, contradiction checks, tie handling; pure function returning `Decision` + reason codes. |
| `repository/base.py` | `IncidentRepository` interface, `CandidateFilter`, `RepositoryError`. The only storage contract. |
| `repository/in_memory.py` | Prototype list/dict-backed implementation (Phase 2). |
| `repository/seed_data.py` | The canonical synthetic records (mirrors `README.md`). |
| `config/settings.py` | All tunables in one place, env-overridable, includes `policy_version`. |
| `config/category_map.py` | Category compatibility relations (placeholder until `TEAM-DECISION D3`). |
| `tests/*` | Unit tests per comparator/policy, integration tests for end-to-end scenarios, API tests for the contract. |

**Testability goal:** every comparator and both policies are unit-testable with **no**
FastAPI import, **no** repository, and **no** network — just two values or a small list.

## 2. Milestones (ordered)

| Milestone | Deliverable | Depends on |
| --- | --- | --- |
| **M0 — Contracts frozen (internal)** | Enums, domain models, `SignalResult`, reason-code constants. | This spec. |
| **M1 — Repository + retriever** | `IncidentRepository` interface, `InMemoryIncidentRepository`, `CandidateRetriever` with self-exclusion and empty-vs-error distinction. | M0 |
| **M2 — Comparators** | `TextComparator`, `LocationComparator`, `CategoryComparator`, `TimeComparator` — each with unit tests. | M0 |
| **M3 — Policies** | `ScoringPolicy` (normalisation, non-finite rejection) and `HybridDecisionPolicy` (gates, thresholds, contradictions, ties) with unit tests. | M1, M2 |
| **M4 — Service** | `DuplicateDetectionService` wiring retrieval → comparison → scoring → decision. | M1–M3 |
| **M5 — API edge** | FastAPI routes, request/response schemas, error mapping, `/health`. | M4 |
| **M6 — Scenario + API tests** | The 17 scenarios (§5) plus contract/error tests. | M5 |
| **M7 — Optional image signal** | `ImageHashComparator` behind a config flag; enable-only if the team opts in. | M2 (parallelisable) |

**Suggested first vertical slice (M1–M4 minimum):** make `DUPLICATE`, `NEW`, and
`REVIEW_REQUIRED` reachable end-to-end with the four core comparators and repository-only
retrieval, *before* adding the FastAPI edge (M5). This keeps the core demonstrable
without transport.

## 3. Recommended dependencies (Phase 2 only — not installed now)
- Runtime: `fastapi`, `uvicorn`, `pydantic` (already implied by the target stack).
- Similarity: `scikit-learn` (TF-IDF) **or** a small hand-rolled TF-IDF + `math` to avoid
  the dependency. Prefer the lightweight in-house version for the prototype if the team
  wants zero ML deps.
- Testing: `pytest`, `pytest-cov`, `httpx` (for FastAPI `TestClient`).
- Optional later: `imagehash` + `Pillow` (image signal), a local embedding model
  (semantic text) — **not** required and not part of the MVP.

No paid API, no external LLM, no cloud service, no production database is required.

## 4. Testing strategy — 17 required scenarios

Naming: A = incoming complaint (canonical `CMP-2026-0001` unless stated). Expected
behaviour references the gate order in `matching_policy.md` §6.4.

| # | Scenario | Setup | Expected behaviour |
| --- | --- | --- | --- |
| 1 | Exact duplicate | A vs `CMP-2026-0000` (same text/loc/cat, ~35 min apart) | `DUPLICATE`; `matched_incident_id = CMP-2026-0000`; score ≥ 0.85; reasons include `SCORE_ABOVE_HIGH_THRESHOLD`. |
| 2 | Paraphrased duplicate | Worded differently, same loc/cat/time | Either `DUPLICATE` (if text still high) or `REVIEW_REQUIRED` (TF-IDF limitation); **never** a false `NEW` when location+category+time are strong. Assert decision ∈ {DUPLICATE, REVIEW_REQUIRED} and location signal AVAILABLE. |
| 3 | Similar text, different location | A vs `CMP-2026-0055` (~8 km) | `REVIEW_REQUIRED`; reason `CONTRADICTION_LOCATION_MISMATCH`; **not** DUPLICATE even though text high. |
| 4 | Same location, incompatible categories | A vs `CMP-2026-0042` | Category relation `incompatible`; `REVIEW_REQUIRED`; reason `CONTRADICTION_CATEGORY_INCOMPATIBLE`; **not** DUPLICATE. |
| 5 | Missing location | A has `location = null` | Location signal `UNAVAILABLE` (score `null`); score normalised over remaining weights; if core anchor still present via text, decision may be DUPLICATE/REVIEW, else `INSUFFICIENT_EVIDENCE`→`REVIEW_REQUIRED`. Never a zero added for location. |
| 6 | Missing description | A has `description = null` | Text `UNAVAILABLE`; other signals scored; if fewer than `MIN_AVAILABLE_SIGNALS`→`REVIEW_REQUIRED`; decision never `NEW` purely because text is missing. |
| 7 | Missing timestamp | A has `reported_at = null` | Time `UNAVAILABLE`; no exclusion of the candidate on time grounds; decision from remaining signals. |
| 8 | No eligible candidates | Repository non-empty but all filtered out / none retrieved | `200`, `NEW`, reason `NO_ELIGIBLE_CANDIDATES`, `score = null`, `candidates = []`, `search.eligible_count = 0`. |
| 9 | Empty repository | Repository contains nothing | Same as #8; distinguishes genuine empty from failure (no exception). |
| 10 | Two equally strong candidates | Two near-identical records within `tie_margin` | `REVIEW_REQUIRED`, `AMBIGUOUS_TIED_CANDIDATES`; **both** candidates returned ranked with reasons. |
| 11 | Invalid coordinates | lat 200 / lon -500 / lone coordinate / NaN | `422 VALIDATION_ERROR`; business logic not invoked; field-level issues listed. |
| 12 | Malformed timestamp | `"14-10-2026 9am"` or no offset | `422 VALIDATION_ERROR` (missing/unsupported offset). |
| 13 | Missing or corrupt image | `image_hash = null`; then `"phash:ZZZZ"` | Null → image `UNAVAILABLE`; corrupt → image `INVALID`; `IMAGE_SIGNAL_DISABLED` in V1; decision unaffected. |
| 14 | Only one available signal | Only category present, everything else null | `REVIEW_REQUIRED` (or `NEW` if no candidate ranks) via `INSUFFICIENT_EVIDENCE`/`MISSING_CORE_ANCHOR`; **never** `DUPLICATE`. |
| 15 | Comparator failure | Inject a comparator that raises for one signal | That signal `ERROR` + `SIGNAL_ERROR_<NAME>`; excluded from scoring; if it drops below minimum, `REVIEW_REQUIRED`; if catastrophic, `500 INTERNAL_ERROR` — never a silent wrong decision. |
| 16 | Invalid / non-finite score | Force a `NaN`/`Infinity` from a policy input | `ScoringPolicy` raises `ScoringError`; API returns `500 INTERNAL_ERROR`; **no** decision emitted with a non-finite score. |
| 17 | Self-comparison using the same id | Repository contains a record with the same `complaint_id` as A | That record is excluded; reason `SELF_COMPARISON_EXCLUDED`; DDA does not compare A against itself. |

Additional edge assertions to include with the above:
- `signals.<name>.score` is `null` for every non-`AVAILABLE` status (invariant test).
- `matched_incident_id` is `null` for every `REVIEW_REQUIRED` unless explicitly labelled.
- Response echoes `policy` and `search` on every `200`.

## 5. Test tooling and layout
- **One pytest suite.** Unit tests per comparator/policy; a parametrised integration
  suite for the 17 scenarios; API contract tests using `fastapi.testclient.TestClient`.
- Unit tests must not import FastAPI.
- Integration tests build the service directly (no HTTP) to isolate business behaviour;
  API tests cover transport mapping only.
- Deterministic fixtures from `repository/seed_data.py`; no randomness in assertions.

## 6. Evaluation plan (metrics — no results claimed yet)
Once a small **labelled** dataset of complaint pairs exists (human-annotated "same
incident" / "different incident"):

| Metric | Definition | Why it matters |
| --- | --- | --- |
| **Precision** | Among proposed `DUPLICATE`, fraction actually the same incident. | Wrong merges are costly; precision protects against them. |
| **Recall** | Among true duplicates, fraction proposed as `DUPLICATE` (or flagged `REVIEW_REQUIRED`). | Missing duplicates defeats the purpose. |
| **False-positive rate** | Fraction of *different*-incident pairs classified `DUPLICATE`. | The primary safety metric; must stay low. |
| **Review rate** | Fraction of requests landing in `REVIEW_REQUIRED`. | Operational load; tune thresholds against it. |

Threshold sweep: grid over `HIGH`, `LOW`, `TIE_MARGIN`, `radius_m`, `TAU`, `FLOOR`;
choose the operating point that keeps false positives low while keeping review rate
tolerable. **No numeric results are reported in Phase 1** — they require labelled data.

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| TF-IDF misses paraphrases → low recall | Location+category+time carry weight; review band catches borderline; embeddings are a future option. |
| Thresholds are guesses | Make them config; validate with the §6 sweep; bias toward low false positives. |
| Field/category/location names differ in KAVACH | Mapping layer + `TEAM-DECISION` items in `integration.md`; keep the core name-agnostic. |
| Over-fitting to synthetic data | Treat synthetic set as smoke tests only; evaluate on labelled real pairs. |
| Coupling to FastAPI | Strict rule: core never imports transport; enforced by the unit tests not importing FastAPI. |

## 8. Explicitly out of scope for Phase 1 (historical)
- Phase 1 deliberately contained no Python business logic, FastAPI app, DB or
  installed packages.
- No image processing prerequisite.
- Embeddings were not part of Phase 1; the optional local embedding text backend
  was added later. No generative LLM is used.
- No production database design.
- No automatic progression to Phase 2 without the user's go-ahead.

The current prototype now includes the core Python pipeline and the internal
service; the FastAPI edge, production database and image signal remain deferred.
See [`service_orchestration.md`](./service_orchestration.md).

## 9. Original first coding task for Phase 2 (historical)

**M0 + M1, first slice:**

> Create the package skeleton under the agreed package root with empty `__init__.py`
> files, then implement the domain objects (`SignalResult`, `IncidentRecord`,
> `DetectionRequest`, `ScoredCandidate`, `DetectionResult`), the shared enums
> (`Decision`, `SignalStatus`, `SignalName`), and `repository/base.py`
> (`IncidentRepository` protocol, `CandidateFilter`, `RepositoryError`).
> Write `repository/in_memory.py` (`InMemoryIncidentRepository` with `add`, `seed`,
> `list_candidates`, `get`, `count`) and a candidate-retriever boundary
> (self-exclusion + empty-vs-error distinction), then a pytest file proving:
> add/seed work, self-exclusion excludes the request id, an empty repository returns
> `[]` (not an error), and a forced repository failure raises `RepositoryError`.

The implemented prototype uses `app/` as its package root and a smaller layout than
this original proposal; the repository tests live in `tests/test_repository.py`. See
[`service_orchestration.md`](./service_orchestration.md) for the current map.

This is the smallest slice that establishes the data contracts, the storage
abstraction, and the candidate-retrieval boundary — with **no** similarity maths, **no**
FastAPI, and **no** repository assumptions beyond the interface. It directly enables
M2 (comparators) next.
