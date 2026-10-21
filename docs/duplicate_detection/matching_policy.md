# Duplicate Detection Agent — Matching Policy (V1 draft)

> Phase 1 design document. All numeric values are **starting hypotheses**, not
> validated production values. They must be tuned against a labelled dataset
> (see §10 and `implementation_plan.md`). Examples use the synthetic dataset in
> `README.md`.

## 1. Signal model

Each comparator emits a `SignalResult`:

```
SignalResult {
  name: "text" | "location" | "category" | "time" | "image"
  status: AVAILABLE | UNAVAILABLE | INVALID | ERROR
  score: float | null        # present in [0,1] ONLY when status == AVAILABLE
  weight: float              # effective weight used in normalisation
  details: dict              # supporting facts
  contradiction: str | null  # optional disqualifying code
}
```

**Invariant:** `score is not None` **iff** `status == AVAILABLE`. Missing evidence is
never converted to a zero score; it is excluded from normalisation instead.

Status semantics:

| Status | Meaning |
| --- | --- |
| `AVAILABLE` | Input sufficient; a valid score in [0,1] was computed. |
| `UNAVAILABLE` | Input absent, or comparator disabled, so no score exists. |
| `INVALID` | Input present but unusable (e.g., malformed hash, empty description where one was expected). |
| `ERROR` | Comparator raised unexpectedly; treated like `UNAVAILABLE` for scoring but flagged. |

## 2. Weights

Illustrative V1 weights (from the project specification):

| Signal | Weight |
| --- | --- |
| text | 0.40 |
| location | 0.30 |
| category | 0.15 |
| time | 0.15 |
| image | 0.00 (disabled in V1) |

Weights sum to 1.00. They are configurable in `config/settings.py`. `image` stays
`0.00` until the optional comparator is enabled (§7); when enabled its weight is taken
from a reserved pool, not silently stolen from the others.

## 3. Score normalisation (missing evidence)

```
score_normalised = Σ (w_i × s_i)  for i where status_i == AVAILABLE
                   ────────────────────────────────────────────
                   Σ (w_i)         for i where status_i == AVAILABLE
```

- If **no** signal is `AVAILABLE`, `score = null` (no candidate can be ranked).
- Normalisation means a candidate with only text+category available can still score
  high — which is exactly why **minimum-evidence rules** (§6) exist to prevent a
  single signal from declaring a duplicate.

## 4. Comparators

### 4.1 Text — `TextComparator`
**Baseline: TF-IDF + cosine similarity.**
- Preprocessing: Unicode normalise → lowercase → collapse whitespace → strip simple
  punctuation → (optional) domain stopword removal. No stemming in V1.
- Vectorise the two descriptions together (per-comparison TF-IDF over the two-document
  corpus, or against a cached IDF from the repository corpus — `TEAM-DECISION` on the
  exact variant; either is valid for the prototype).
- `score = cosine_similarity(vec_a, vec_b)`, clamped to [0,1].
- Status:
  - both usable → `AVAILABLE`.
  - either description absent/empty → `UNAVAILABLE` with `SIGNAL_UNAVAILABLE_TEXT`.
  - a present description tokenises to zero tokens → `INVALID`.

**Limitations (must be stated in code comments and docs):**
- TF-IDF is **lexical**, not semantic. Paraphrased complaints ("deep pit in the road"
  vs "crater forming on carriageway") may score low despite describing the same thing.
- Short texts produce unstable vectors; a shared single term can inflate similarity.
- Negation and sarcasm are not modelled.
- **Future upgrade (optional):** sentence embeddings (e.g., a local open-source
  Sentence-Transformers model) for semantic similarity. Explicitly out of the MVP and
  not required for the prototype; noted only as a candidate improvement.

`TEAM-DECISION`: whether an embedding model is acceptable (size/runtime) — not needed now.

### 4.2 Location — `LocationComparator`
Resolution order (first applicable wins):
1. **Identifier match.** If `location_id` is present on both sides and equal → score
   `1.0`, `basis = "identifier"`, reason `LOCATION_IDENTIFIER_MATCH`.
2. **Facility match, different location_id.** Same `facility_id`, different
   `location_id` → partial score (default `0.60`), `basis = "facility"`, reason
   `LOCATION_FACILITY_MATCH`. (Configurable.)
3. **Coordinates.** If both sides have valid coordinates → Haversine distance `d`
   (metres) → score via a configurable mapping (§4.2.1).
4. Otherwise → `UNAVAILABLE` (`SIGNAL_UNAVAILABLE_LOCATION`) if no comparable field
   exists; `INVALID` if a field was present but unusable.

**Haversine** is used for spherical great-circle distance — adequate for city-scale
distances and dependency-light (standard library `math`). It ignores elevation and
road network, which is acceptable for a proximity heuristic.

#### 4.2.1 Distance → similarity
```
d = haversine_m(a, b)
score = clamp(1 - (d / R), 0, 1)     where R = radius_m (default 500 m)
```
- `d = 0` → `1.0`; `d ≥ R` → `0.0`.
- A `score == 0.0` here is a **valid, computed** zero (genuinely far), which is
  different from `UNAVAILABLE` (no coordinates at all). This distinction is essential
  and must be preserved.
- Configurable `R`. A larger `R` softens the penalty; a smaller `R` tightens it.

**Missing coordinates are never treated as zero distance.** If coordinates are absent
but identifiers are present, the identifier path is used; if neither is available, the
signal is `UNAVAILABLE` and simply drops out of normalisation — it does **not** add a
zero to the numerator.

### 4.3 Category — `CategoryComparator`
Relation determined by a data-driven compatibility map (`config/category_map.py`),
which is a table the team can populate (`TEAM-DECISION D3`). The DDA does **not**
hard-code a closed category vocabulary.

| Relation | Score | Reason code | Contradiction? |
| --- | --- | --- | --- |
| exact (same code, case-insensitive) | 1.00 | `CATEGORY_EXACT_MATCH` | no |
| compatible (map says same family) | 0.60 | `CATEGORY_COMPATIBLE` | no |
| incompatible (map says mutually exclusive) | 0.00 | `CATEGORY_INCOMPATIBLE` | **yes** |
| unknown (one/both codes absent from map) | — | `CATEGORY_UNKNOWN` | no |

- Unknown relations → `UNAVAILABLE` (the DDA cannot judge, so it must not penalise).
- Absent category → `UNAVAILABLE`.
- An **incompatible** relation produces `score = 0.0` **and** sets
  `contradiction = "CONTRADICTION_CATEGORY_INCOMPATIBLE"` (§6.2).

### 4.4 Time — `TimeComparator`
- Parse both timestamps to aware UTC datetimes; `delta_hours = |t_a - t_b|` in hours.
- Configurable **decay with floor** (default), so that reports far apart in time are
  *weak evidence of difference*, never proof of difference:

```
score = FLOOR + (1 - FLOOR) × exp(-delta_hours / TAU)
defaults: FLOOR = 0.10, TAU = 48 h
```
- Behaviour: `delta = 0 h → 1.00`; `48 h → ~0.43`; `168 h (7 d) → ~0.13`; asymptote → `0.10`.
- The floor encodes the design statement: **two reports far apart in time must not be
  automatically declared different incidents** (a pothole can persist for weeks).
- Missing timestamp → `UNAVAILABLE` (`SIGNAL_UNAVAILABLE_TIME`); malformed/unparseable →
  `INVALID` (validated earlier, so this should be rare).
- An alternative simple form is a hard window (`score = 1` inside window, else 0);
  the exponential+floor form is preferred because a bare zero at the window edge would
  behave like a contradiction. The chosen function is configurable.

`TEAM-DECISION`: pick `TAU`/`FLOOR`/window based on expected complaint persistence.

### 4.5 Image — `ImageHashComparator` (optional, off by default)
- Input: two perceptual hashes (e.g., `phash:<hex>` / `dhash:<hex>`), same algorithm.
- If a 64-bit hash: `score = clamp(1 - hamming_distance / MAX_BITS, 0, 1)` with a
  configurable acceptance threshold; a very small Hamming distance (default ≤ 10) sets a
  reason `IMAGE_HASH_NEAR_IDENTICAL`.
- **Disabled in V1**: status `UNAVAILABLE`, reason `IMAGE_SIGNAL_DISABLED`, weight 0.
  Enabling it is a policy decision, not a prerequisite for a working prototype.
- Absent hash → `UNAVAILABLE`; malformed hash → `INVALID`.
- **Epistemic limit (must be documented):** a matching perceptual hash supports the
  *evidence* that two images are near-identical, but **cannot independently prove** that
  two complaints describe the same real-world incident (e.g., stock/re-shared images,
  screenshots, edited photos). It is corroborating evidence at most.

## 5. Scoring

See §3 for the normalisation formula. `ScoringPolicy.score()` is a **pure function**:
given the list of `SignalResult` and the weight config, it returns
`(score, contributions[])`. It performs no decisioning and no I/O. It must reject
non-finite results (see §8) by raising a `ScoringError`.

## 6. Evidence requirements, contradictions, and thresholds

### 6.1 Minimum evidence requirements
A single signal must never be able to declare a `DUPLICATE`.

Levers (all configurable):
- `MIN_AVAILABLE_SIGNALS` (default **2**): number of `AVAILABLE` signals among
  {text, location, category, time}. Fewer → cannot be `DUPLICATE`.
- `REQUIRE_CORE_ANCHOR` (default **true**): at least one of **text** or **location**
  must be `AVAILABLE` **and** supportive (score above a small floor, e.g. ≥ 0.50).
  Category + time alone are not strong enough.
- Even when 2+ signals are available, a **corroboration** requirement applies for
  `DUPLICATE`: at least two signals must be *supportive* (text ≥ 0.50, or location
  ≥ 0.50, or category relation exact/compatible, or time ≥ 0.50), unless location is a
  hard identifier match plus category exact (`TEAM-DECISION` to refine).

Failure to meet these → downgrade to `REVIEW_REQUIRED`, with `INSUFFICIENT_EVIDENCE`
or `MISSING_CORE_ANCHOR` reason.

### 6.2 Contradiction rules
Contradictions **disqualify** `DUPLICATE` (they force at most `REVIEW_REQUIRED`); they
do not by themselves delete or auto-reject anything.

| ID | Condition | Reason code | Effect |
| --- | --- | --- | --- |
| C1 | Text very similar (`text ≥ 0.80`) **and** location clearly different (`location ≤ 0.20`, computed) | `CONTRADICTION_LOCATION_MISMATCH` | Cannot be `DUPLICATE`. |
| C2 | Categories inferred **incompatible** | `CONTRADICTION_CATEGORY_INCOMPATIBLE` | Cannot be `DUPLICATE`. |
| C3 | Two or more candidates within `tie_margin` of each other at the top | `AMBIGUOUS_TIED_CANDIDATES` | `REVIEW_REQUIRED`, multiple candidates returned. |
| C4 | Fewer than `MIN_AVAILABLE_SIGNALS`, or no core anchor | `INSUFFICIENT_EVIDENCE` / `MISSING_CORE_ANCHOR` | Cannot be `DUPLICATE`. |
| C5 | A signal present but unusable | `SIGNAL_INVALID_*` | Signal excluded from scoring; counts toward evidence shortage. |

Note the asymmetry that makes C1 meaningful: a **computed** low location score
(both coordinate sets present but far apart) is strong negative evidence, whereas an
**unavailable** location score is merely absent evidence. Only the former can trigger C1.

### 6.3 Thresholds (starting hypotheses)
```
HIGH = 0.85   # ≥ → DUPLICATE candidate (subject to §6.4 gates)
LOW  = 0.55   # < → NEW candidate
review band: LOW ≤ score < HIGH
TIE_MARGIN = 0.05
```
These are **not validated**. They exist to make the prototype runnable and must be
tuned against labelled examples (§10).

### 6.4 Gate order (how a score becomes a decision)
```
if no eligible candidates:               → NEW   (NO_ELIGIBLE_CANDIDATES)
else take best candidate by score:

  if evidence insufficient (C4):          → REVIEW_REQUIRED (INSUFFICIENT_EVIDENCE / MISSING_CORE_ANCHOR)
  elif contradiction C1 or C2:            → REVIEW_REQUIRED (contradiction code)
  elif tie at top (C3):                   → REVIEW_REQUIRED (AMBIGUOUS_TIED_CANDIDATES)
  elif score >= HIGH:                     → DUPLICATE
  elif score >= LOW:                      → REVIEW_REQUIRED (SCORE_BETWEEN_THRESHOLDS)
  else:                                   → NEW (SCORE_BELOW_LOW_THRESHOLD)
```

**Ordering matters:** evidence gates and contradictions are checked **before** the
threshold comparison, so a high score cannot override a contradiction or a
missing-core-anchor condition.

## 7. Decision outcomes — precise meaning

- **`DUPLICATE`** — best candidate clears `HIGH`, meets evidence requirements
  (§6.1), and carries **no** disqualifying contradiction. `matched_incident_id` is set.
  The DDA is still only *proposing*: acting on it is another component's job.
- **`REVIEW_REQUIRED`** — evidence is borderline (review band), incomplete (insufficient
  signals), contradictory (C1/C2), or ambiguous (C3). Return the best candidate(s) with
  per-candidate `score`, `signals`, `reasons`, and `contradictions`, but do **not**
  assert certainty: `matched_incident_id` stays `null` unless a *leading candidate for
  review* is explicitly labelled as such.
- **`NEW`** — no credible duplicate candidate was found **within the searched repository
  and policy scope**. This is scoped, not absolute: it does **not** prove that no
  duplicate exists elsewhere in KAVACH (e.g., in another jurisdiction, outside the
  retrieval window, or beyond an active blocking filter). The `search` block records the
  scope so the claim stays honest.

## 8. Failure and non-finite handling
- Any comparator raising → signal `ERROR`, reason `SIGNAL_ERROR_<NAME>`, excluded from
  scoring. If errors reduce available signals below the minimum → `REVIEW_REQUIRED`.
- `ScoringPolicy` must **reject** `NaN`/`Infinity` scores by raising `ScoringError`
  rather than emitting them. A non-finite final score is an `INTERNAL_ERROR` (HTTP 500),
  never a decision.
- Repository failure is **not** a decision; it maps to `REPOSITORY_ERROR` (5xx). It is
  never reported as `NEW`.

## 9. Candidate ranking and ties
- Candidates are ranked by descending normalised score.
- **Stable tie-break:** equal scores are ordered by (a) higher location score, then
  (b) higher text score, then (c) earlier absolute time difference, then (d) lexical
  `complaint_id` — deterministic so results are reproducible.
- If rank-1 and rank-2 scores differ by less than `TIE_MARGIN`, decision is
  `REVIEW_REQUIRED` (C3) and **both** are returned with their reasons.

## 10. Threshold validation plan (no results yet)
- **No evaluation numbers are claimed.** Thresholds above are hypotheses.
- When a small labelled set exists (human-annotated "same incident" / "different
  incident" pairs), sweep `HIGH`, `LOW`, and `TIE_MARGIN` and measure precision, recall,
  false-positive rate, and review rate (definitions in `implementation_plan.md` §6).
- Selection should favour a **low false-positive rate** (never auto-marking distinct
  incidents as duplicates) even at the cost of a higher review rate, because the DDA is
  advisory and human review is cheaper than a wrong merge.

## 11. Reason-code catalog (trigger conditions)

| Code | Trigger |
| --- | --- |
| `TEXT_SIMILARITY_HIGH` | text score ≥ 0.70 |
| `TEXT_SIMILARITY_MODERATE` | 0.40 ≤ text score < 0.70 |
| `TEXT_SIMILARITY_LOW` | text score < 0.40 |
| `SIGNAL_UNAVAILABLE_TEXT` | no usable description |
| `LOCATION_IDENTIFIER_MATCH` | identical `location_id` |
| `LOCATION_FACILITY_MATCH` | identical `facility_id`, different `location_id` |
| `LOCATION_PROXIMITY_WITHIN_RADIUS` | Haversine score ≥ 0.50 |
| `LOCATION_PROXIMITY_BEYOND_RADIUS` | Haversine score < 0.50 |
| `SIGNAL_UNAVAILABLE_LOCATION` | no identifiers and no coordinates |
| `CATEGORY_EXACT_MATCH` | identical category |
| `CATEGORY_COMPATIBLE` | map relation = compatible |
| `CATEGORY_INCOMPATIBLE` | map relation = incompatible |
| `CATEGORY_UNKNOWN` | relation not in map |
| `TIME_WITHIN_WINDOW` | time score ≥ 0.50 |
| `TIME_OUTSIDE_WINDOW` | time score < 0.50 |
| `SIGNAL_UNAVAILABLE_TIME` | missing timestamp |
| `IMAGE_HASH_NEAR_IDENTICAL` | Hamming distance ≤ threshold (only when enabled) |
| `IMAGE_SIGNAL_DISABLED` | image comparator off (V1 default) |
| `SCORE_ABOVE_HIGH_THRESHOLD` / `SCORE_BETWEEN_THRESHOLDS` / `SCORE_BELOW_LOW_THRESHOLD` | band placement |
| `INSUFFICIENT_EVIDENCE` | available signals < `MIN_AVAILABLE_SIGNALS` |
| `MISSING_CORE_ANCHOR` | neither text nor location supportive |
| `CONTRADICTION_LOCATION_MISMATCH` | C1 |
| `CONTRADICTION_CATEGORY_INCOMPATIBLE` | C2 |
| `AMBIGUOUS_TIED_CANDIDATES` | C3 |
| `NO_ELIGIBLE_CANDIDATES` | repository returned none |
| `SELF_COMPARISON_EXCLUDED` | a same-id record was skipped |
| `SIGNAL_INVALID_<NAME>` / `SIGNAL_ERROR_<NAME>` | per-signal failure |
| `REPOSITORY_ERROR` | retrieval failed |
