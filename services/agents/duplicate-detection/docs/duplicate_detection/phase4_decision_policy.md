# Duplicate Detection Agent — Phase 4 (M4) Decision Policy

Implementation notes for the **decision policy** milestone (M4). This document is
*implementation documentation*, not part of the Phase 1 specification. Phase 1
(the [`README.md`](../../README.md) and the other documents in this folder) is
**unchanged** and remains authoritative for the matching policy and contracts.

## Relationship to M3 (weighted scoring)

Phase 4 has two milestones:

- **M3 — weighted scoring engine** (combine the four signals from
  `MatchingWeights` into a single ranking `score`). This is implemented in
  [`app/scoring/engine.py`](../../app/scoring/engine.py) as
  `WeightedScoringEngine`, with implementation notes in
  [`scoring_engine.md`](./scoring_engine.md).
- **M4 — decision policy** (turn already-computed candidate evidence into
  `DUPLICATE` / `REVIEW_REQUIRED` / `NEW`). This document describes M4.

M4 consumes evidence and does **not** recompute or reinterpret scores. The M3
engine produces the `CandidateScore` input contract below through
`ScoringResult.to_candidate_score(incident_id)`; the policy itself is unchanged by
M3 and remains fully testable without a scoring engine.

M4 was originally implemented before M3. Keeping the policy independent of score
computation is why adding M3 required no decision-policy rewrite: only the thin
adapter and the engine were added.

## Module layout

| Path | Contents |
| --- | --- |
| `app/scoring/__init__.py` | Exports the scoring engine, decision policy and domain types. |
| `app/scoring/engine.py` | `WeightedScoringEngine` (M3), `ScoringResult`, `ScoringError`, engine reason codes. |
| `app/scoring/decision_policy.py` | `DecisionPolicy` (M4), `CandidateScore`, `RankedCandidate`, `RetrievalStatus`, `DecisionOutcome`, the reason-code catalog. |
| `app/config/settings.py` | `MatchingWeights` (M3 input) and `DecisionPolicySettings` (as `Settings.decision`). |
| `tests/test_scoring_engine.py` | Unit tests for M3. |
| `tests/test_decision_policy.py` | Unit tests for every behaviour below. |

The policy is deterministic, pure and side-effect free: it never mutates its
inputs, never retrieves candidates, and never touches storage, the network or
HTTP. It deliberately contains **no** similarity computation, **no** score
combination, **no** repository/database access, and **no** complaint
create/edit/delete/merge.

## Input contract — the M3 → M4 boundary

```python
CandidateScore(
    incident_id: str,
    score: float | None,                  # combined ranking score in [0, 1], or None
    signals: Mapping[str, SignalResult],  # per-signal evidence (text/location/category/time)
    contradictions: tuple[str, ...] = (), # optional explicit disqualifiers
    reasons: tuple[str, ...] = (),        # optional pre-attached reason codes
)
```

`score` is the scoring engine's combined **ranking** score — never a calibrated
probability and never recomputed here. M3 supplies it via
`ScoringResult.to_candidate_score(incident_id)`, which also carries every signal,
the conflict codes and the engine reason codes. `signals` reuses the Phase 2
[`SignalResult`](../../app/schemas/duplicate_response.py) (the same object the
comparators emit); there is no parallel result model.

`CandidateScore` is a **domain contract, not an HTTP schema**. The public entry
point is:

```python
DecisionPolicy.decide(candidates, *, retrieval_status=RetrievalStatus.COMPLETE) -> DecisionOutcome
```

`DecisionOutcome.to_response(complaint_id)` adapts the result to the existing
Phase 2 `DuplicateDetectionResponse`. The richer per-candidate data stays on the
domain object (it maps to the deferred `candidates` response block in
`api_contract.md`).

## Retrieval completeness

`RetrievalStatus` is `COMPLETE` / `INCOMPLETE` / `FAILED`. The policy performs no
retrieval; the caller states how trustworthy the candidate set is. `NEW` is only
ever allowed when retrieval was `COMPLETE` — an empty or thin candidate set from
an incomplete/failed search is **not** evidence that no duplicate exists. This is
the machine-readable form of `matching_policy.md` §8 ("repository failure … is
never reported as `NEW`").

## Evidence rules (`matching_policy.md` §6.1)

Applied to the **best** candidate after ranking (see below):

| Rule | Configuration | Effect if unmet |
| --- | --- | --- |
| Minimum evidence | `min_available_signals` (default 2) — count of `AVAILABLE` core signals | `REVIEW_REQUIRED` (`INSUFFICIENT_EVIDENCE`) |
| Core anchor | `require_core_anchor` (default true) — text **or** location `AVAILABLE` with score ≥ `core_anchor_floor` (default 0.50) | `REVIEW_REQUIRED` (`MISSING_CORE_ANCHOR`) |
| Corroboration | `require_corroboration` (default true) — ≥ 2 supportive signals (score ≥ `supportive_floor`, default 0.50) | `REVIEW_REQUIRED` (`INSUFFICIENT_EVIDENCE`) |

The document's corroboration exception is implemented: a location
`LOCATION_IDENTIFIER_MATCH` **and** a category `CATEGORY_EXACT_MATCH` corroborate
each other even if neither clears the floor.

`UNAVAILABLE` / `INVALID` signals are **never** treated as `0`; they are excluded
from the counts. "Supportive" is evaluated per signal; a signal that is available
but below the floor still counts toward `min_available_signals` but not toward
corroboration.

## Contradiction rules (`matching_policy.md` §6.2)

Contradictions disqualify `DUPLICATE` (forcing at most `REVIEW_REQUIRED`); they
never delete or auto-reject anything.

| Rule | Condition | Code emitted |
| --- | --- | --- |
| C1 | `text ≥ location_conflict_text_floor` (0.80) **and** `location ≤ location_conflict_location_ceiling` (0.20), both `AVAILABLE` | `CONTRADICTION_LOCATION_MISMATCH` |
| C2 | category signal carries a conflict flag (`details.conflict is True`) | `CONTRADICTION_CATEGORY_INCOMPATIBLE` |
| — | location signal carries a conflict flag (identifier/facility) | `CONTRADICTION_LOCATION_MISMATCH` |
| explicit | `CandidateScore.contradictions` contains a non-empty code | the canonical code for recognised comparator codes; otherwise the upstream code verbatim |

The comparator-specific code (`LOCATION_IDENTIFIER_CONFLICT`,
`LOCATION_FACILITY_CONFLICT`, `CATEGORY_INCOMPATIBLE`) is retained on the
per-candidate summary (`RankedCandidate.contradictions`) so nothing is lost.
Explicit contradictions are honoured even when the corresponding signal details
are absent; the reason-code set is additive, so an unrecognised upstream code is
surfaced rather than dropped.

The asymmetry C1 depends on is preserved: a **computed** low location score can
trigger C1, whereas an **unavailable** location score cannot. Likewise, **absent
optional identifiers are not a conflict** — a coordinate-only location match is
agreement, not disagreement.

> **ASSUMPTION.** The Phase 1 catalog names `CONTRADICTION_LOCATION_MISMATCH` and
> `CONTRADICTION_CATEGORY_INCOMPATIBLE` are used verbatim. The prompt's illustrative
> `LOCATION_CONFLICT` / `CATEGORY_CONFLICT` are the same rules under these names.

## Gate order (`matching_policy.md` §6.4)

Applied to the best candidate, with the document's ordering preserved (evidence
and contradictions are checked **before** the thresholds):

1. any candidate with an invalid / non-finite / out-of-range score, or malformed
   evidence → `REVIEW_REQUIRED` (`INVALID_SCORE`) — never `DUPLICATE`, never `NEW`;
2. no candidates → `NEW` (`NO_ELIGIBLE_CANDIDATES`) if retrieval `COMPLETE`, else
   `REVIEW_REQUIRED` (retrieval code);
3. candidates exist but none is scoreable → `REVIEW_REQUIRED`
   (`INSUFFICIENT_EVIDENCE`, plus a retrieval code if applicable);
4. fewer than `min_available_signals` available → `REVIEW_REQUIRED`
   (`INSUFFICIENT_EVIDENCE`);
5. no core anchor → `REVIEW_REQUIRED` (`MISSING_CORE_ANCHOR`);
6. a material contradiction (C1/C2 or an explicit `CandidateScore.contradictions`
   code) → `REVIEW_REQUIRED` (`CONTRADICTION_*`, or the upstream code verbatim);
7. too few supportive signals → `REVIEW_REQUIRED` (`INSUFFICIENT_EVIDENCE`);
8. top two candidates within `tie_margin` → `REVIEW_REQUIRED`
   (`AMBIGUOUS_TIED_CANDIDATES`);
9. `score ≥ thresholds.high` → `DUPLICATE` (`SCORE_ABOVE_HIGH_THRESHOLD`);
10. `score ≥ thresholds.low` → `REVIEW_REQUIRED` (`SCORE_BETWEEN_THRESHOLDS`);
11. otherwise → `NEW` (`SCORE_BELOW_LOW_THRESHOLD`), **blocked to
    `REVIEW_REQUIRED`** if retrieval was not `COMPLETE`.

> **Documented deviations.**
> 1. §6.4 lists evidence (C4), then contradictions (C1/C2), then the tie (C3),
>    then thresholds. This implementation additionally checks corroboration
>    (§6.1) **after** contradictions and before the tie, so the more specific,
>    more actionable conflict code surfaces when a contradiction and missing
>    corroboration both apply. Every evidence gate remains ahead of the
>    thresholds and the ambiguity check.
> 2. Ambiguity (C3) is applied literally **before** the threshold bands, so two
>    near-equal *low*-scoring candidates become `REVIEW_REQUIRED`, not `NEW`.
>    This is the conservative reading.

**Consequence (documented, not a bug).** Because the evidence gates precede the
thresholds, a low score attached to a candidate that could not be adequately
evaluated is sent to review, not declared new. `NEW` therefore requires that the
best candidate passed the evidence gates *and* that the top candidates were not
tied.

## Ranking and ambiguity (`matching_policy.md` §9)

Valid candidates are ordered by a deterministic total order:

1. combined score, descending;
2. location signal score, descending;
3. text signal score, descending;
4. time signal score, descending;
5. `incident_id`, ascending.

The ordering is **presentation-only** and never invents a decision. If the top
two scores differ by less than `tie_margin` (the ambiguity margin, default 0.05),
the outcome is `REVIEW_REQUIRED` (`AMBIGUOUS_TIED_CANDIDATES`) and both candidates
are returned.

> **ASSUMPTION.** §9 names the raw absolute time gap as tie-breaker (c). The policy
> only receives the time *score*, which is a monotonic proxy for the gap under the
> shipped `TimeComparator` (higher score = smaller gap), so the score is used.
> `tie_margin` is reused as the ambiguity margin rather than adding a second knob.

## Invalid input handling (`matching_policy.md` §8)

- An invalid candidate (bad `incident_id`, non-`SignalResult` evidence, an
  `AVAILABLE` signal without a valid score, a non-`AVAILABLE` signal carrying a
  score, or a `score` that is not a finite number in `[0, 1]`) marks the whole
  candidate **unusable**. It can never produce `DUPLICATE` or `NEW`; the outcome is
  `REVIEW_REQUIRED` with `INVALID_SCORE`.
- `score is None` is legitimate **only** when no signal is `AVAILABLE`; a
  scoreable candidate handed over without a score is `INVALID_SCORE`.
- Invalid input is **not** silently treated as an ordinary mismatch, and
  programming errors are not suppressed — an unknown `retrieval_status` raises
  `ValueError`.
- The policy re-validates the configuration it depends on. Pydantic validates
  `Settings`, but a caller can bypass it with `model_construct`; in that case the
  policy raises `ValueError` rather than silently mis-deciding.

## Reason-code catalog (as implemented)

| Code | Emitted when |
| --- | --- |
| `SCORE_ABOVE_HIGH_THRESHOLD` | `DUPLICATE` — best score ≥ `high`. |
| `SCORE_BETWEEN_THRESHOLDS` | `REVIEW_REQUIRED` — review band. |
| `SCORE_BELOW_LOW_THRESHOLD` | best score < `low`. |
| `INSUFFICIENT_EVIDENCE` | evidence/corroboration shortage, or no scoreable candidate. |
| `MISSING_CORE_ANCHOR` | no supportive text/location anchor. |
| `CONTRADICTION_LOCATION_MISMATCH` | C1, a location conflict flag, or an explicit location conflict code. |
| `CONTRADICTION_CATEGORY_INCOMPATIBLE` | C2, a category conflict flag, or an explicit category conflict code. |
| `AMBIGUOUS_TIED_CANDIDATES` | top-two score gap < `tie_margin`. |
| `NO_ELIGIBLE_CANDIDATES` | retrieval returned no candidates (and was complete). |
| `INVALID_SCORE` | unusable/non-finite/out-of-range/missing score, or malformed evidence. |
| `CANDIDATE_RETRIEVAL_INCOMPLETE` | retrieval not complete. |
| `CANDIDATE_RETRIEVAL_FAILED` | retrieval failed. |

Treat this as an open, additive set. An unrecognised explicit contradiction code
appears verbatim in `reasons` (and still disqualifies `DUPLICATE`). The combined
score is never described as a probability.

## Configuration (`Settings.decision` → `DecisionPolicySettings`)

All values are **provisional hypotheses**, not validated values. Defaults:

| Setting | Default | Constraint |
| --- | --- | --- |
| `min_available_signals` | 2 | integer, `1..4` |
| `require_core_anchor` | `True` | bool |
| `core_anchor_floor` | 0.50 | finite, `[0, 1]` |
| `supportive_floor` | 0.50 | finite, `[0, 1]` |
| `require_corroboration` | `True` | bool |
| `location_conflict_text_floor` | 0.80 | finite, `[0, 1]` |
| `location_conflict_location_ceiling` | 0.20 | finite, `[0, 1]`, `< text floor` |

Existing knobs are reused rather than duplicated: `thresholds.high` / `thresholds.low`
(bands) and `tie_margin` (ambiguity margin) from Phase 2. There are no scattered
magic numbers.

## Provisional assumptions (not validated)

- Thresholds (`high 0.85`, `low 0.55`), `tie_margin` (`0.05`) and every
  `decision.*` value are **hypotheses**; see `matching_policy.md` §10 for the
  intended tuning plan. No evaluation numbers are claimed.
- **M3 scoring weights and M4 thresholds are provisional.** `CandidateScore.score`
  is produced by `WeightedScoringEngine` using `MatchingWeights`; both the weights
  and every `decision.*` value are untuned hypotheses. See
  [`scoring_engine.md`](./scoring_engine.md).
- `REVIEW_REQUIRED` never asserts a match: `matched_incident_id` stays `None`, and
  the leading candidate is exposed only as a suggestion (`leading_candidate_id`).
- Integration remains **Option B (standalone service)** with Option A (importable
  module) as a drop-in; the core logic is transport-free.

## Running the tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_policy.py -q
```

Coverage includes the threshold bands, empty/thin/incomplete/failed retrieval,
each evidence gate, each contradiction rule (including explicit
`CandidateScore.contradictions`), absent-identifier non-conflicts, near-equal and
exactly-equal tops, every invalid-score form, malformed evidence, invalid
configuration (including `model_construct` bypass), the V1 response adapter,
determinism, and input immutability.
