# Duplicate Detection Agent — Local Sentence-Embedding Text Comparator

Implementation notes for the **local sentence-embedding text backend**. This is
implementation documentation, not a change to the Phase 1 matching policy.

## Status

Implemented and wired at the comparator-construction layer:

- [`app/comparators/embedding_text_comparator.py`](../../app/comparators/embedding_text_comparator.py)
  — `EmbeddingTextComparator`.
- [`app/comparators/factory.py`](../../app/comparators/factory.py) —
  `build_text_comparator()` and `build_core_comparators()`.
- [`app/config/settings.py`](../../app/config/settings.py) —
  `ComparatorSettings.text_backend` and `ComparatorSettings.embedding_model`.

The weighted scoring engine, decision policy, response schemas and public
request/response contracts are unchanged. The internal service layer now exists
at [`app/services/detection_service.py`](../../app/services/detection_service.py)
and uses the factory for its default comparator wiring; there is still no HTTP
endpoint. See [`service_orchestration.md`](./service_orchestration.md) for the
service flow and the known embedding-`ERROR` policy limitation.

## Architecture boundary: one `text` signal

`EmbeddingTextComparator` is an **alternative implementation of the existing
`text` signal**, not an additional signal.

- `EmbeddingTextComparator.name == "text"`.
- `build_text_comparator()` returns **exactly one** comparator: the embedding
  backend (default) or `TextComparator` (TF-IDF baseline/fallback).
- TF-IDF and embeddings must never both be passed to the scoring engine. They
  are two measurements of the same evidence, not independent evidence.
- The existing `text` weight (`0.40`) and formula are untouched:

  ```
  score = Σ(w_i × s_i) / Σ(w_i)   for AVAILABLE signals with w_i > 0
  ```

- The comparator never decides `DUPLICATE` / `REVIEW_REQUIRED` / `NEW`.

### Default and fallback

The default is `text_backend="embedding"`. TF-IDF remains fully available:

```python
from app.comparators import build_text_comparator
from app.config.settings import ComparatorSettings, Settings

settings = Settings(comparators=ComparatorSettings(text_backend="tfidf"))
text_comparator = build_text_comparator(settings)
```

This is a **configuration-selected** fallback, not an automatic runtime
failover. If the embedding model cannot load or inference fails, the comparator
returns an `ERROR` signal; it does not silently switch algorithms. Automatic
fallback would change the meaning of the evidence and hide an operational
failure. The engine already excludes `ERROR` signals and renormalises the
remaining weights.

## Behaviour and status mapping

Both descriptions are whitespace-collapsed and trimmed, encoded together in one
`encode()` call, L2-normalised, and compared with a dot product (cosine
similarity). The model may be pre-normalised, but the comparator normalises
again after validating the vectors.

| Input / outcome | `SignalStatus` | `reason` | Score |
| --- | --- | --- | --- |
| Missing, empty or whitespace-only description | `UNAVAILABLE` | `TEXT_UNAVAILABLE` | `None` |
| Non-string description | `INVALID` | `TEXT_INVALID` | `None` |
| Model load failure | `ERROR` | `TEXT_EMBEDDING_MODEL_LOAD_FAILED` | `None` |
| Inference exception | `ERROR` | `TEXT_EMBEDDING_INFERENCE_FAILED` | `None` |
| Malformed, non-finite, wrong-shape or zero-norm output | `ERROR` | `TEXT_EMBEDDING_INVALID_OUTPUT` | `None` |
| Success | `AVAILABLE` | `TEXT_EMBEDDING_SIMILARITY` | `clamp(cosine, 0, 1)` |

Failures are **never converted to a score of `0.0`**. On success, a negative
cosine is floored at `0.0` only because `SignalResult.score` is defined on
`[0, 1]`. The pre-floor cosine value is retained in `details["raw_cosine"]`; the
details also include `basis`, `model`, `embedding_dim`,
`negative_cosine_floored`, `normalised_embeddings` and the normalised texts.
Error details include the model name, exception type and a length-limited error
message, without exposing a full traceback.

## Model lifecycle

- The default loader imports `sentence_transformers` lazily and constructs
  `SentenceTransformer(model_name)` on first use. Importing the application and
  running unit tests therefore does **not** require PyTorch or a model.
- Loaded models are cached **once per process**, keyed by model name, behind a
  lock. The model is not loaded or rebuilt per comparison.
- A failed load is also cached. Repeated comparisons return `ERROR`
  immediately instead of retrying a slow or failing download for every
  candidate. Call `clear_model_cache()` to clear both successful and failed
  entries and allow a retry.
- An injected `model=` or `loader=` (used by tests and controlled deployments)
  bypasses the process cache. An injected model is the caller's responsibility.
- The cache is process-local. Each worker process loads its own copy.

### First use and offline operation

The first real use downloads the model from Hugging Face unless it is already in
the local cache. In this environment the cached
`sentence-transformers/all-MiniLM-L6-v2` model loaded in about 22 seconds
(21.85 s measured) on CPU with no GPU. The output dimension is 384. A cold
start is therefore noticeable; it must not happen on a per-request path.

The illustrative evaluation supports `--local-files-only` and can run with:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
python scripts/evaluate_text_similarity.py --local-files-only
```

The application comparator itself has no `local_files_only` setting; it follows
the standard Hugging Face cache/environment behaviour. Unit tests inject fake
encoders and never download the model or touch the network.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `comparators.text_backend` | `"embedding"` | `"embedding"` or `"tfidf"`; exactly one text backend |
| `comparators.embedding_model` | `"sentence-transformers/all-MiniLM-L6-v2"` | Non-blank model identifier |

Both are provisional. `text_backend` is a `Literal`, so unknown values are
rejected by Pydantic validation. `embedding_model` is trimmed and must be
non-empty; it is not restricted to a single repository or revision.

## Integration example

```python
from app.comparators import build_core_comparators
from app.config.settings import Settings
from app.scoring import WeightedScoringEngine

settings = Settings()  # default: embedding text backend
comparators = build_core_comparators(settings)

signals = {
    name: comparator.compare(new_complaint, candidate)
    for name, comparator in comparators.items()
}
result = WeightedScoringEngine(settings.weights).score(signals)
candidate_score = result.to_candidate_score(candidate.complaint_id)
outcome = DecisionPolicy(settings.decision).decide([candidate_score])
```

`build_core_comparators()` returns the four core names exactly once:
`{"text", "location", "category", "time"}`. The existing scoring engine and
decision policy consume the signals unchanged.

## Unit tests

The focused tests use fake encoders, fixed vectors and injected loaders, so they
are deterministic and offline:

```powershell
python -m pytest -q tests/test_embedding_text_comparator.py tests/test_comparator_factory.py --tb=short
```

Result after this change: **44 passed**. The full suite:

```powershell
python -m pytest -q --tb=short
```

Result: **324 passed**. The baseline before this change was 280 passed;
the 44 new tests are 35 embedding-comparator tests and 9 factory/integration
tests.

## Illustrative evaluation: TF-IDF vs embeddings

> **Synthetic data warning.** The repository has **no labelled duplicate
> dataset**. The evaluation uses 40 hand-written pairs and is useful only for a
> relative comparison and for exposing failure modes. It is **not** an estimate
> of production precision, recall or review rate.

### Dataset

| Kind | Count | Label | Purpose |
| --- | ---: | ---: | --- |
| Paraphrase duplicates | 12 | 1 | Same incident, little lexical overlap |
| Lexical duplicates | 8 | 1 | Same incident, substantial shared wording |
| Hard negatives | 10 | 0 | Similar wording, different location/ward/block/entity |
| Easy negatives | 10 | 0 | Different incident and different wording |
| **Total** | **40** |  | 20 duplicate / 20 non-duplicate |

The hard negatives are deliberately difficult for a **text-only** comparator:
they should score highly on wording because they are textually similar. The
full agent is expected to resolve them with location, category and time
evidence.

### Setup

- Python 3.12.8, CPU only.
- `sentence-transformers 5.5.1`, `torch 2.12.0+cpu`, `numpy 1.26.4`,
  `scikit-learn 1.5.1`.
- Model: `sentence-transformers/all-MiniLM-L6-v2`, cached and loaded offline.
- Primary threshold: `0.50` (pre-declared).
- Review-band proxy: inclusive `[0.40, 0.60]` around the threshold. This is not
  the M4 decision policy and does not represent the full system's review rate.
- Exact command:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
python scripts/evaluate_text_similarity.py --local-files-only
```

### Fixed-threshold metrics at `0.50`

| Comparator | Precision | Recall | F1 | TP | FP | TN | FN | FPR | Review-band rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TF-IDF | 0.500 | 0.500 | 0.500 | 10 | 10 | 10 | 10 | 0.500 | 0.175 |
| Embeddings | 0.667 | 1.000 | 0.800 | 20 | 10 | 10 | 0 | 0.500 | 0.025 |

Embeddings detected all 20 duplicates; TF-IDF detected 10 (2 of 12 paraphrases
and all 8 lexical duplicates). Both produced 10 false positives, all of them
hard negatives. Because all 20 negatives are equally weighted, detecting all
duplicates while keeping every easy negative correct still caps precision at
`20 / 30 = 0.667` on this set.

### Threshold-independent ranking

| Comparator | ROC-AUC | Average precision |
| --- | ---: | ---: |
| TF-IDF | 0.601 | 0.543 |
| Embeddings | 0.682 | 0.633 |

The embedding backend ranks the pairs better overall, but the margin is modest.
The overlap caused by the hard negatives is visible in both metrics.

### Threshold sweep

| Threshold | Comparator | Precision | Recall | F1 | False positives |
| ---: | --- | ---: | ---: | ---: | ---: |
| 0.30 | TF-IDF | 0.630 | 0.850 | 0.723 | 10 |
| 0.30 | Embeddings | 0.625 | 1.000 | 0.769 | 12 |
| 0.40 | TF-IDF | 0.565 | 0.650 | 0.605 | 10 |
| 0.40 | Embeddings | 0.667 | 1.000 | 0.800 | 10 |
| 0.50 | TF-IDF | 0.500 | 0.500 | 0.500 | 10 |
| 0.50 | Embeddings | 0.667 | 1.000 | 0.800 | 10 |
| 0.60 | TF-IDF | 0.375 | 0.300 | 0.333 | 10 |
| 0.60 | Embeddings | 0.655 | 0.950 | 0.776 | 10 |
| 0.70 | TF-IDF | 0.462 | 0.300 | 0.364 | 7 |
| 0.70 | Embeddings | 0.640 | 0.800 | 0.711 | 9 |

A best-F1 search **on the same 40 pairs** selects `0.2638` for TF-IDF and
`0.5238` for embeddings; both reach F1 `0.800` with 10 false positives. That
search is an optimistic upper bound, not a validated operating point, and it
does not remove the hard-negative errors.

### Score distribution

| Comparator | Duplicate mean | Duplicate median | Non-duplicate mean | Non-duplicate median |
| --- | ---: | ---: | ---: | ---: |
| TF-IDF | 0.522 | 0.486 | 0.414 | 0.428 |
| Embeddings | 0.833 | 0.856 | 0.544 | 0.510 |

The embedding distribution is shifted upward for both classes. This is exactly
why a threshold calibrated for TF-IDF cannot be assumed to transfer to
embeddings.

### Findings

- Embeddings substantially improve paraphrase recall: all 12 paraphrase
  duplicates score at or above `0.50` (range `0.5238`–`0.8926`), while TF-IDF
  catches only 2 of 12 at `0.50`.
- Lexical duplicates are easy for both backends. Embeddings score them
  `0.9055`–`0.9882`; TF-IDF scores them `0.5101`–`0.8831`.
- All 10 hard negatives are false positives for **both** backends at `0.50`
  (TF-IDF `0.6030`–`1.0000`; embeddings `0.6781`–`0.9903`). At `0.70`, 7
  TF-IDF and 9 embedding hard negatives remain false positives.
- No single text threshold separates this set cleanly. The highest embedding
  hard-negative score (`0.9903`) exceeds the highest embedding duplicate score
  (`0.9882`); the highest TF-IDF hard negative is `1.0000` versus a maximum
  duplicate score of `0.8831`. Text alone cannot resolve location/entity
  differences, and it should not be expected to.
- The review-band rate is low for embeddings (`0.025`) because hard negatives
  sit above `0.60` and easy negatives below `0.40`; the band catches only one
  borderline duplicate. This is a property of this synthetic set and a narrow
  band proxy, not evidence that the full M4 policy would review less often.

## Limitations and calibration risks

- **Small synthetic set.** 40 hand-written pairs, no confidence intervals, no
  production distribution. Treat every metric as illustrative.
- **Hard negatives are model-independent.** They test the limits of text as
  evidence, not just embedding quality. A text-only evaluation cannot establish
  duplicate-detection accuracy; location, category, time and the M4 gates are
  required.
- **Thresholds are not calibrated.** The tentative M4 thresholds (`high 0.85`,
  `low 0.55`), `core_anchor_floor` / `supportive_floor` (`0.50`) and weights were
  designed before this backend existed. Embedding scores have a different
  distribution from TF-IDF; a `text` score of `0.52` is not a probability and is
  not directly comparable to a combined score threshold. No thresholds were
  retuned in this change.
- **Short-text sensitivity.** Paraphrase scores vary with context and wording;
  the lowest duplicate in the evaluation is only `0.5238`, just above `0.50`.
  Short phrases can score substantially lower.
- **Truncation.** `all-MiniLM-L6-v2` has a maximum sequence length of 256 word
  pieces. Long descriptions are truncated, so late details (including a
  location or entity) may be ignored.
- **Negation, entities and numbers.** Sentence embeddings are not a natural
  language inference model. They can miss negation, swapped entities, units or
  numeric differences. The hard-negative results demonstrate this class of
  failure.
- **Dependency and cold start.** `sentence-transformers` pulls in PyTorch.
  First use downloads roughly 90 MB (the exact size depends on the model and
  cache), and a cold process load took about 22 s here. Use a warm process,
  pre-provision the cache, and consider batching if this is deployed.
- **Process-local memory.** Each worker process holds its own model copy. There
  is no shared model server or vector database; none was added in this task.
- **Model supply chain.** The model is loaded by name. Production deployment
  should pin a revision/hash and verify the download source. No generative LLM,
  external LLM API or hosted inference service is used.
- **Failure semantics.** A cached load failure makes subsequent comparisons
  return `ERROR` until `clear_model_cache()` is called. This is deliberate
  (avoid retrying a slow download per candidate) but needs an operational
  recovery path.
- **No end-to-end evaluation.** The script evaluates text signals only. It does
  not run candidate retrieval, location/category/time comparison, the weighted
  engine, the M4 decision policy, or a review workflow. Review-band rate is a
  proxy, not the M4 review outcome.

## Next step

Calibrate and validate on a real labelled complaint dataset **end to end**:
compare `text_backend="embedding"` and `"tfidf"` through the full signal set and
M4 policy, with location/category/time included, and report decision-level
precision, recall, false positives and review rate rather than text scores
alone. If embeddings are adopted, pin the model revision, pre-provision it in
the deployment image/cache, and revisit `core_anchor_floor`, `supportive_floor`
and the decision thresholds using cross-validation. Do not tune them on this
synthetic set.
