# Duplicate Detection Agent — Phase 4 (M3) Weighted Scoring Engine

Implementation notes for the **weighted scoring engine** milestone (M3). This
document is *implementation documentation*, not part of the Phase 1 specification.
The matching policy in [`matching_policy.md`](./matching_policy.md) remains
authoritative for the formula and for the downstream decision gates.

## Status

M3 is implemented in [`app/scoring/engine.py`](../../app/scoring/engine.py):

- `WeightedScoringEngine` — combines the four core comparator signals.
- `ScoringResult` — frozen domain result with score, evidence, weights,
  normalisation details, conflict codes and reason codes.
- `ScoringError` — raised for invalid configuration or evidence.
- `REASON_*` constants — deterministic engine reason codes.

Its focused tests are in
[`tests/test_scoring_engine.py`](../../tests/test_scoring_engine.py). The engine is
pure, deterministic, side-effect free and transport-free. It performs no candidate
retrieval, similarity computation, decisioning, persistence, caching or HTTP.

## Formula

The implementation follows [`matching_policy.md`](./matching_policy.md) §3:

```
score = Σ(w_i × s_i) / Σ(w_i)
        for every core signal i with status_i == AVAILABLE and w_i > 0
```

- Default `MatchingWeights`: `text 0.40`, `location 0.30`, `category 0.15`,
  `time 0.15` (sum `1.00`).
- `UNAVAILABLE`, `INVALID` and `ERROR` signals are excluded from **both** the
  numerator and the denominator. They are never coerced to `0`.
- The denominator is the sum of the **available** weights, so partial evidence is
  renormalised. Example: text-only evidence with score `0.8` yields `0.8`, not
  `0.32`.
- If no `AVAILABLE` signal has a positive weight, the score is `None`; the
  candidate cannot be ranked. Signals with weight `0.0` remain evidence but cannot
  create a score.
- A supplied weight vector need not sum to `1.0`; the engine normalises by the
  available weight sum. The configured default does sum to `1.0`.

## Interface

```python
from app.scoring import DecisionPolicy, WeightedScoringEngine

engine = WeightedScoringEngine()           # DEFAULT_SETTINGS.weights
# or: engine = WeightedScoringEngine(settings.weights)

result = engine.score(
    text=text_signal,
    location=location_signal,
    category=category_signal,
    time=time_signal,
    extra_signals={"image": image_signal},  # optional; unweighted
)

# Equivalent mapping form:
result = engine.score(
    {"text": text_signal, "location": location_signal,
     "category": category_signal, "time": time_signal}
)

candidate = result.to_candidate_score("CMP-123")
outcome = DecisionPolicy().decide([candidate])
```

Rules:

- All four core signals are required. Missing core signals raise `ValueError`.
- Mapping and keyword forms are mutually exclusive; mixing them raises `TypeError`.
- `extra_signals` may add future/unweighted signals but may not redefine a core
  signal name (`ValueError`).
- Signal names are case-sensitive strings. The four core names are exactly
  `text`, `location`, `category`, `time`.
- The engine accepts the existing `SignalResult` and `MatchingWeights` models; it
  introduces no parallel signal or weight model.
- The engine does not mutate the supplied signals, weights or mappings.

## Result

`ScoringResult` is a frozen dataclass. Its mappings are read-only views.

| Field | Meaning |
| --- | --- |
| `score` | Combined ranking score in `[0, 1]`, or `None` when unscorable. |
| `signals` | Every input signal: core signals first, then extras sorted by name. |
| `available_scores` | Scores of all `AVAILABLE` signals, including unweighted extras. |
| `configured_weights` | Configured weights for the four core signals (zeros included). |
| `weights_used` | Effective weights (`w_i / Σw`) for signals that contributed; empty when unscorable. |
| `contributions` | Each contributing signal's share of `score` (`weights_used_i × s_i`). |
| `weighted_sum` | Numerator `Σ(w_i × s_i)` before division. |
| `weight_total` | Denominator `Σw_i`; `0.0` when unscorable. |
| `configured_weight_total` | Sum of all four configured core weights. |
| `normalised` | `True` when `weight_total < configured_weight_total` (a configured-weight signal was unavailable or zero-weight); always `False` when unscorable. |
| `contradictions` | Comparator conflict codes in deterministic signal order. |
| `reasons` | Engine reason codes (open, additive set). |

`weights_used` sums to `1.0` and `contributions` sums to `score`, within
floating-point error. `signals` preserves unweighted evidence (for example a
future `image` signal) even though it cannot affect the score.

## Validation and invariants

M3 re-validates data defensively because Pydantic objects can be created with
`model_construct`, bypassing normal validation.

- Weights: each core weight must be a real number, finite and non-negative; the
  sum must be positive. `bool`, strings, `NaN`, `±inf`, negatives and all-zero
  weights raise `ScoringError`.
- `AVAILABLE` signal scores: must be a real number, finite, and in `[0, 1]`.
  `bool`, strings, `None`, `NaN`, `±inf` and out-of-range values raise
  `ScoringError`.
- Non-`AVAILABLE` signals must carry `score = None`; otherwise `ScoringError`.
- Unknown statuses raise `ScoringError`.
- A non-`SignalResult` value raises `ScoringError`.
- Inputs are never mutated; result mappings are read-only; `ScoringResult` is
  frozen.
- Repeated calls with the same inputs return equal results, independent of input
  mapping order.

## Conflict metadata

Comparators represent conflicts on the existing `SignalResult`:

```python
details["conflict"] is True
details["conflict_code"] == "LOCATION_IDENTIFIER_CONFLICT"  # or similar
```

M3 does **not** rewrite or remove these details. It preserves every signal object
on `ScoringResult.signals` and copies each distinct `conflict_code` into
`ScoringResult.contradictions` in deterministic core-then-extra order. Material
contradiction rules (for example text-high/location-low) remain M4's job; M3 only
carries the metadata forward.

## M3 → M4 boundary

`ScoringResult.to_candidate_score(incident_id)` adapts the result to the existing
`CandidateScore` domain contract:

```python
CandidateScore(
    incident_id=...,
    score=result.score,
    signals=dict(result.signals),
    contradictions=result.contradictions,
    reasons=result.reasons,
)
```

The adapter is intentionally thin. The decision policy does not import the scoring
engine at runtime, does not recompute the score, and requires no changes when M3
is present. See
[`phase4_decision_policy.md`](./phase4_decision_policy.md) for M4.

An unscorable result (`score is None`) adapts to a `CandidateScore` with
`score=None`. If no signal is `AVAILABLE`, M4 reports
`REVIEW_REQUIRED` / `INSUFFICIENT_EVIDENCE`, never `NEW`. If available evidence
exists but every available signal is unweighted or has weight zero, M4 reports
`INVALID_SCORE` rather than treating absence of a score as a low score.

## Reason codes

| Code | Meaning |
| --- | --- |
| `WEIGHTED_SCORE_COMPUTED` | A positive-weight average was computed. |
| `WEIGHTED_SCORE_UNAVAILABLE` | No positive-weight average could be computed; `score is None`. |
| `NO_AVAILABLE_SIGNAL` | No input signal was `AVAILABLE`. |
| `NO_POSITIVE_WEIGHT_SIGNAL` | Some evidence was available, but no usable signal had a positive weight. |
| `SCORE_RENORMALISED_FOR_AVAILABLE_WEIGHTS` | The denominator was reduced because at least one configured-weight core signal did not contribute (unavailable or zero-weight). |
| `ZERO_WEIGHT_SIGNAL_IGNORED` | At least one `AVAILABLE` core signal had weight `0.0`. |
| `UNWEIGHTED_SIGNAL_PRESENT` | An extra/unweighted signal was retained as evidence only. |
| `CONFLICT_METADATA_PRESENT` | At least one conflict code was carried into `contradictions`. |

Treat this as an open, additive set; M4 reason codes are separate.

## Specification reconciliation

The authoritative policy is [`matching_policy.md`](./matching_policy.md). Its §3
formula is implemented directly. Three other details conflict with the current
public code contracts or were under-specified; they are recorded here rather than
silently changed:

1. **`SignalResult` shape (§1).** The document sketches fields
   `name`, `weight` and `contradiction`, but the implemented public
   `SignalResult` has `status`, `score`, `reason`, `details`. M3 therefore takes
   signal names from mapping keys / keyword arguments, weights from
   `MatchingWeights`, and conflicts from `details["conflict"]` /
   `details["conflict_code"]`. Changing the public schema was explicitly out of
   scope.
2. **Component and return shape (§5).** The document names a pure
   `ScoringPolicy.score()` returning `(score, contributions[])` and raising
   `ScoringError`. The requested implementation is `WeightedScoringEngine.score()`
   returning the richer `ScoringResult` (which includes `score`, `contributions`
   and more). The exception name `ScoringError` is preserved. This is a naming and
   result-shape reconciliation, not a second scoring policy.
3. **Time decay floor (§4.4).** The document specifies
   `score = FLOOR + (1 - FLOOR) × exp(...)` with `FLOOR = 0.10`, while
   `app/comparators/time_comparator.py` currently uses a plain exponential decay.
   M3 consumes whatever comparator score it is given; this pre-existing comparator
   discrepancy is unchanged and remains an open team decision.

There is no conflict with §3's exclusion rule: M3 excludes non-`AVAILABLE`
signals exactly as specified and never substitutes zero. M3 also does not change
M4's documented gate interpretation in §6.4.

## Out of scope

- Candidate retrieval/search, ranking across real records and service wiring.
- PostGIS, databases, repositories, caching and FastAPI.
- Image hashing, the optional image comparator and its weight.
- Embeddings/vector stores.
- Decision thresholds, gate logic, merges or auto-resolution.

## Running the tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_scoring_engine.py -q
# full suite
.\.venv\Scripts\python.exe -m pytest -q
```
