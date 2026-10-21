# KAVACH — Duplicate Detection Agent (standalone prototype)

> **This is a prototype in progress, not yet a functioning duplicate detector.**
> Phase 2 implemented the schema, repository and configuration foundation.
> Phase 3 added the four core **comparators** (category, time, location, text),
> which produce individual, advisory evidence signals only. Phase 4 adds both the
> **weighted scoring engine** (M3), which combines those signals into a ranking
> score, and the **decision policy** (M4), which turns the scored evidence into
> `DUPLICATE` / `REVIEW_REQUIRED` / `NEW`.
>
> The scoring engine and decision policy are implemented. The FastAPI endpoint,
> candidate retrieval and image similarity remain **not** implemented.

This component is owned by one member of a 10-member KAVACH group project. It is
built as a **standalone Python package** so it can be developed independently and
later mounted inside the shared KAVACH backend or deployed as a service.

The Phase 1 design lives in [`docs/duplicate_detection/`](./docs/duplicate_detection)
(architecture, API contract, matching policy, integration contract, implementation
plan). This README describes the Phase 2 foundation, the Phase 3 comparators and
the Phase 4 scoring engine (M3) and decision policy (M4). Their implementation
notes are in
[`scoring_engine.md`](./docs/duplicate_detection/scoring_engine.md) and
[`phase4_decision_policy.md`](./docs/duplicate_detection/phase4_decision_policy.md).

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

Four independent **comparators** under `app/comparators/`, each returning a shared
`SignalResult` for one new complaint versus one candidate complaint:

- `CategoryComparator` — exact / compatible / incompatible / unknown categories.
- `TimeComparator` — exponential decay over the `reported_at` gap.
- `LocationComparator` — identifier precedence plus Haversine/coordinate decay.
- `TextComparator` — lexical TF-IDF + cosine similarity.

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

## Explicitly NOT implemented yet

- Candidate retrieval/search, candidate ranking across real records, and the
  service that wires retrieval → comparison → scoring → decision.
- Image similarity (the `image_hash` signal) — no image hashing or image weight.
- FastAPI routes, `main.py`, or any HTTP layer.
- Frontend, database, PostGIS, external APIs, sentence-transformer embeddings or
  vector store, and response caching.
- `candidates` / `search` / `policy` / `request_id` response blocks from Phase 1
  (deferred), and the decision-engine cross-field invariants (documented, not
  enforced).

## Folder structure

```
app/
  __init__.py
  schemas/
    __init__.py
    complaint.py            # Complaint + Location input schemas and validation
    duplicate_response.py   # Decision/SignalStatus enums, SignalResult, response
  repositories/
    __init__.py
    base.py                 # ComplaintRepository interface + RepositoryError
    in_memory.py            # InMemoryComplaintRepository (list/dict-backed)
    synthetic.py            # deterministic synthetic fixtures
  config/
    __init__.py
    settings.py             # MatchingWeights, DecisionThresholds, ComparatorSettings,
                            # DecisionPolicySettings, Settings
  comparators/
    __init__.py             # exports the four comparators and the shared helpers
    base.py                 # Comparator ABC + result builders (null-score invariant)
    category_comparator.py  # CategoryComparator
    time_comparator.py      # TimeComparator
    location_comparator.py  # LocationComparator (+ haversine_meters)
    text_comparator.py      # TextComparator (TF-IDF cosine)
  scoring/
    __init__.py             # exports the scoring engine, decision policy and types
    engine.py               # WeightedScoringEngine (M3), ScoringResult, ScoringError
    decision_policy.py      # DecisionPolicy (M4), CandidateScore, RetrievalStatus,
                            # DecisionOutcome, reason-code catalog
tests/
  test_schemas.py           # schema, response and configuration tests
  test_repository.py        # repository behaviour tests
  test_category_comparator.py
  test_time_comparator.py
  test_location_comparator.py
  test_text_comparator.py
  test_comparator_contract.py  # cross-comparator contract tests
  test_scoring_engine.py     # M3 weighted-scoring tests
  test_decision_policy.py    # M4 decision-policy tests
conftest.py                 # adds project root to sys.path for pytest
requirements.txt
README.md
docs/duplicate_detection/   # Phase 1 design docs + Phase 4 implementation notes
```

## Schema responsibilities

- **`app/schemas/complaint.py`** — `Location` (optional identifiers + coordinates;
  coordinates must be finite, in range, and supplied as a pair) and `Complaint`
  (required non-empty `complaint_id`; optional `description`, `category`,
  `location`, timezone-aware `reported_at`, `image_hash`). Blank optional strings
  normalise to `None`; missing values stay missing. Unknown extra fields are
  rejected, so an integration mapping layer should translate KAVACH field names
  first.
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
values are described in the Phase 4 (M4) section. No environment-variable
configuration is used (Phase 1 did not require it).

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
- **TextComparator** (`text_comparator.py`) — lexical TF-IDF + cosine similarity.

### How the text comparator works (high level)

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
efficient candidate search. No external API, model download or vector store is used.

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

All are **provisional**. The distance scale does **not** mean "within the radius ⇒
duplicate"; that judgement belongs to Phase 4. Comparators read configuration at
construction time and hold no mutable global state.

### Running the comparator tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_category_comparator.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_time_comparator.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_location_comparator.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_text_comparator.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_comparator_contract.py -q
# or everything:
.\.venv\Scripts\python.exe -m pytest -q
```

### Known limitations

- **Lexical only.** TF-IDF cannot recognise paraphrases or synonyms
  ("broken streetlight" vs "lamp not working" score `0.0`). Semantic similarity
  would need embeddings, which are out of scope.
- **Pair-local fitting.** IDF weights are not comparable across candidate
  comparisons; a shared corpus/retrieval index is a production concern.
- **Shared stopwords.** Common words ("the") are not removed by default, so two
  unrelated sentences can share a small nonzero score. An optional `stop_words`
  argument is available (e.g. `"english"`), but it is language-specific.
- **Category map is fictional.** The sample groups/pairs are placeholders.
- **Scales are unvalidated.** Time and distance decay scales are guesses.

### What remains after Phase 4

The M3 scoring engine and M4 decision policy are implemented. Remaining work is
candidate retrieval/service wiring, the optional image signal and its weight, and
the FastAPI endpoint. None of these changes the scoring formula or the policy gates.

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
.\.venv\Scripts\python.exe -m pytest tests\test_scoring_engine.py -q
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
.\.venv\Scripts\python.exe -m pytest tests\test_decision_policy.py -q
```

## Install and run tests (Windows PowerShell)

```powershell
cd "C:\Users\dadla\OneDrive\Documents\Default Project"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest -q
```

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
