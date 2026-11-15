# KAVACH Verification Agent integration guide

This document describes the local prototype boundary. The upstream PDFs define example payloads and workflow concepts; several policy and deployment decisions are still pending. The app does not run the upstream agents.

## Pipeline and inputs

Expected workflow order:

`Incident Intelligence -> Duplicate Detection -> Supervisor -> Sanitation -> Dispatch -> Field Worker -> Verification`

The verifier consumes:

- **Field Worker:** task and submission IDs, completion note, completed checklist step IDs, references to stored before/after evidence, and a completion location-event ID. Image bytes are read only from server-side evidence storage; client URLs are not accepted.
- **Sanitation:** task checklist, labels, requirement IDs, mandatory flags, and optional target observations. Sanitation site/zone labels are not considered authoritative coordinates. An authoritative site policy (coordinates and tolerance) must be supplied by its owner separately.
- **Shared location service:** task-owned target coordinates/tolerance and the completion location's coordinates, accuracy and server-received timestamp. It validates bounds, accuracy and timestamp before calculating distance. Missing inputs are not substituted with defaults.
- **Deterministic image quality service:** before/after bytes loaded through the same trusted evidence repository path checks used by Gemini. OpenCV computes sharpness, mean grayscale brightness, dimensions and dHash similarity. Quality findings only append limitations and reason codes; they do not make an outcome or score.

The verifier returns a result. Downstream routing/queue transitions are not implemented because E1/E2 remain pending team decisions.

## Field Worker adapter mapping

| Source field/value | Internal field/value | If missing or invalid |
|---|---|---|
| `task_id` | Submission `task_id` | Required by schema; invalid contract is HTTP 422. |
| `submission_id` | Idempotency key and response `submission_id` | Optional in nested completion only if top-level request supplies it; otherwise request validation fails. |
| `completion_note` | Submission note | Remains null; it is not used as proof. |
| `checklist_completed: ["STEP-01", ...]` | `checklist: {"STEP-01": true, ...}` | An omitted step remains UNKNOWN; the adapter never turns absence into false/completed. |
| `before_evidence_ids` / `after_evidence_ids` | Evidence records of internal type `BEFORE_IMAGE` / `AFTER_IMAGE` | Unknown IDs, wrong task, duplicate reference or wrong type are rejected; they are not fetched from caller paths. |
| Evidence `evidence_type: BEFORE|AFTER` | Internal evidence `type: BEFORE_IMAGE|AFTER_IMAGE` | Enum validated; invalid values are rejected. |
| Evidence `upload_status: STORED|PENDING|FAILED` | Internal `status: READY|PENDING|FAILED` | Missing status/reference is invalid; `STORED` requires a server `storage_key`. |
| Evidence `storage_key` | Trusted repository storage path | No caller-supplied URL/path; missing path means the image cannot be analyzed. |
| `completion_location_event_id` | Resolved completion `location` object | Missing ID means no GPS event; unknown event, wrong task, or ARRIVAL event is rejected. |
| Event `event_type: COMPLETION` | Completion GPS input | Only a COMPLETION event is accepted for this reference. |
| `latitude`, `longitude` | Internal coordinates | Nullable for non-captured events; captured events require both. Invalid bounds fail contract validation. |
| `accuracy_meters` | Internal `accuracy_m` | Preserved as nullable; missing/invalid accuracy makes GPS INCONCLUSIVE, not substituted. |
| `received_at_server` | Internal `timestamp_valid` boolean | Absent timestamp becomes false, making the location check INCONCLUSIVE. |
| `capture_status: CAPTURED|UNAVAILABLE|INACCURATE` | Coordinates / unavailable / inconclusive GPS path | Status is preserved; no fabricated coordinates. |

## Sanitation adapter mapping

| Source field/value | Internal field/value | If missing or invalid |
|---|---|---|
| External task association + `incident_id` | Internal task ID + `incident_id` | The adapter accepts task ID from the caller's task association; `incident_id` is required by contract. |
| `task_checklist[].description` | Requirement `label` | Required text; invalid entries fail schema validation. |
| `requirement_id` | Requirement `requirement_id` | No ID is synthesized; item is omitted with a contract warning and verification becomes INCONCLUSIVE. |
| `mandatory` | Requirement mandatory flag | No boolean default; missing flag is warned and omitted, producing INCONCLUSIVE. |
| `target_observation` | Requirement target observation | Optional; remains unknown if not supplied. |
| `depends_on`, resources, criteria, status | Preserved by input contract; not converted into a completion claim | Optional arrays remain empty; status is not interpreted as evidence. |
| `resources_required` counts / `estimated_time` | Kept as source context where modeled | Null counts/time remain null; no quantity is invented. |
| Sanitation location site/zone | Not used as GPS target | A separately supplied authoritative site policy is required. Missing coordinates/tolerance adds warning and yields INCONCLUSIVE. |

## Shared location service mapping

| Shared input | Use | Missing/invalid behavior |
|---|---|---|
| Target latitude/longitude | Haversine reference | Must be finite and within latitude -90..90 / longitude -180..180; otherwise INCONCLUSIVE before Haversine. |
| Target tolerance | Allowed distance | Must be finite and positive; otherwise INCONCLUSIVE. A configured override is used only when set. |
| Evidence latitude/longitude | Completion location | Bounds and schema validation apply; invalid values are INCONCLUSIVE. |
| `accuracy_m` / `accuracy_meters` | Compare to configured maximum accuracy | Missing/nonpositive or above-limit accuracy is INCONCLUSIVE; no fallback. |
| Server timestamp validity | GPS evidence freshness/provenance check | Missing server-received timestamp is INCONCLUSIVE. |
| `requested=false` or no target | Shared status `NOT_CHECKED` | No location assertion is made. |
| Requested evidence absent | Shared status `INCONCLUSIVE` | Never substituted by a site pin or other device event. |
| Distance within/outside tolerance | `CONSISTENT` / `MISMATCH` | GPS match supports location only; it is not proof of cleaning. Conflicting location checks can combine to `REVIEW_REQUIRED`. |

## Deterministic image-quality step

`app/services/image_quality_service.py::ImageQualityService` runs on each `READY` before/after evidence record with a server-side `storage_path`, for both mock and Gemini vision modes. It uses `EvidenceRepository.load_image`, which resolves paths beneath the configured trusted evidence root and reuses the existing image decoder/MIME validation. OpenCV then decodes the bytes and calculates Laplacian variance, grayscale mean brightness, width/height, and a 64-bit dHash. It makes no network calls. The audit stores typed results, flags, hashes, and the thresholds used; it contains neither image bytes nor storage paths.

All thresholds can be set in `.env`; the `.env.example` values are illustrative, not approved policy, and must be tuned against representative field photos:

| Environment variable | Default | Meaning |
|---|---:|---|
| `QUALITY_BLUR_THRESHOLD` | 100 | Below this Laplacian variance is flagged blurry. |
| `QUALITY_MIN_BRIGHTNESS` | 35 | Below this grayscale mean is flagged too dark. |
| `QUALITY_MAX_BRIGHTNESS` | 225 | Above this grayscale mean is flagged too bright. |
| `QUALITY_MIN_WIDTH` | 640 | Lower image width is flagged low resolution. |
| `QUALITY_MIN_HEIGHT` | 480 | Lower image height is flagged low resolution. |
| `QUALITY_DUPLICATE_HASH_DISTANCE` | 5 | dHash Hamming distance at or below this means near-identical before/after. |

No stored bytes means `NOT_CHECKED` with `QUALITY_NOT_CHECKED`; this is not treated as good quality and does not alone force review. This preserves current mock demo outcomes. A stored path that cannot be read or decoded is `NOT_CHECKED` and adds a limitation. Unavailable measurements remain null. A checked quality issue adds a short limitation to visual findings and uses the existing decision engine behavior (limitations lead to MANUAL_REVIEW). Identical/near-identical before/after images add `BEFORE_AFTER_IDENTICAL` as a review signal, never as an accusation or direct FAIL. Other additive reason codes are `IMAGE_BLURRY`, `IMAGE_TOO_DARK`, `IMAGE_TOO_BRIGHT`, and `IMAGE_LOW_RESOLUTION`. The vision model is not trusted to notice quality issues, and its outputs do not replace these deterministic checks.

## API request and response contract

Endpoint: `POST /api/v1/tasks/{task_id}/verification`, protected by `X-KAVACH-API-Key` when configured. In Swagger, select **Authorize** and enter the configured key. For demo fixtures, the request body can be `{"submission_id":"SUB-PASS"}`. A Field Worker request can instead include `field_worker_completion` as defined in `app/contracts/v1.py`.

Contract history is additive:

- **1.0:** initial response carried verification IDs/status, score, findings, remarks and evidence/version metadata.
- **1.1:** retained those fields and added `reason_codes` and `failed_requirement_ids`. No 1.0 response fields were intentionally removed or renamed. Consumers should ignore unknown fields; future compatible changes must be additive. A breaking change requires a new contract version.
- **1.1 additive extension:** adds optional `verification_confidence` and `alignment_finding` response fields, optional `cleanup_score` and `confidence` in `image_findings`, and the reason codes `LOW_VERIFICATION_CONFIDENCE`, `VERIFICATION_CONFIDENCE_UNAVAILABLE`, and `IMAGE_ALIGNMENT_LOW_CONFIDENCE`. Existing fields remain unchanged. Consumers should tolerate these additional fields and reason-code values.
- Old cached SQLite 1.0 rows are refreshed under the same task/submission/rule idempotency key so they do not produce an invalid 1.1 response.

Every response includes these fields:

| Field | Meaning |
|---|---|
| `contract_version` | Additive API contract version (`1.1`). |
| `verification_id`, `task_id`, `submission_id` | Result and input identifiers. |
| `verification_status` | `PASS`, `FAIL`, `INCONCLUSIVE`, or `MANUAL_REVIEW`. |
| `verification_score` | Weighted score, or null when unavailable/withheld for GPS mismatch. |
| `score_status` | `AVAILABLE`, `PARTIAL`, or `UNAVAILABLE`. |
| `score_breakdown` | Component scores (`image_evidence`, `gps_consistency`, `plan_compliance`) or null. |
| `image_findings` | Validated observations/change/limitations, or `{status: UNAVAILABLE, reason: ...}`. |
| `image_findings.cleanup_score` | Vision model's bounded (0-100) semantic estimate of visible cleanup; it informs the image score component but does not decide the final status. |
| `image_findings.confidence` | Vision model's bounded (0-100) self-assessment for its observations/cleanup estimate; this is not a calibrated probability. |
| `verification_confidence` | Conservative minimum of semantic confidence and available landmark alignment confidence; null when semantic confidence is unavailable. |
| `alignment_finding` | OpenCV ORB/RANSAC registration status and match/inlier/reprojection diagnostics; never includes image bytes. |
| `location_finding` | Status, optional score/distance, and reasons; raw coordinates are not returned. |
| `plan_compliance_findings` | Requirement IDs, labels, mandatory flags, worker claims, evidence finding, reason, evidence IDs. |
| `remarks` | Deterministic, evidence-linked explanations; vision model prose is not used. |
| `requires_manual_review` | Boolean review indicator; INCONCLUSIVE is also surfaced for human follow-up in this prototype. |
| `rule_version` | Configured policy/rule version. |
| `vision_provider`, `vision_model_version`, `vision_prompt_version` | Analysis provenance; no API key is recorded. |
| `evidence_refs` | Evidence IDs referenced by this result. |
| `created_at` | UTC result timestamp. |
| `reason_codes` | Stable enum codes, including `LOW_VERIFICATION_CONFIDENCE`, `VERIFICATION_CONFIDENCE_UNAVAILABLE`, and `IMAGE_ALIGNMENT_LOW_CONFIDENCE` for the new verification stage. |
| `failed_requirement_ids` | Requirement IDs causing a mandatory FAIL; otherwise empty. |

### Status meaning downstream

| Status | Meaning in this prototype | Downstream policy |
|---|---|---|
| `PASS` | Required evidence and configured checks support completion; score threshold passes when applicable. | No automated downstream transition is implemented. |
| `FAIL` | A definite mandatory contradiction/non-completion or a score-only below-threshold outcome. Mandatory findings take precedence over score. | Correction, supervisor review, and reassignment policy is pending E2. |
| `INCONCLUSIVE` | Required evidence, analysis, GPS, or upstream policy metadata is missing/invalid. | Retry/hold/escalation policy is pending E2. |
| `MANUAL_REVIEW` | Evidence is uncertain, blurry/obstructed, visual change is uncertain, GPS conflicts with otherwise clean evidence, or combined verification confidence is below the configured threshold. | Response flag is `requires_manual_review=true`; a real inspector assignment/notification queue remains an orchestrator/Supervisor integration and is not implemented in this repository. |

## Two-tier visual verification and human review

The deterministic OpenCV quality audit remains a quality gate (sharpness, brightness, image dimensions and near-duplicate detection). `ImageAlignmentService` is a separate step: it matches ORB keypoints, estimates an AFTER-to-BEFORE homography using RANSAC, reports match/inlier/reprojection diagnostics, and supplies a registered image pair to Gemini when registration confidence reaches the configured threshold. If registration is weak, Gemini can describe the original pair, but the alignment limitation forces `MANUAL_REVIEW`.

Gemini returns fixed-shape `before_observations`, `after_observations`, `visual_change`, `limitations`, `cleanup_score` and `confidence`. The model must not choose the final status or write remarks. The image evidence score uses the semantic cleanup score when available; older/mock findings without one retain the deterministic compatibility fallback. Combined verification confidence is the lower of semantic confidence and the available alignment score. Set `KAVACH_REVIEW_CONFIDENCE_THRESHOLD` to control the cutoff (default 80). A confidence below 80 produces `MANUAL_REVIEW`, `requires_manual_review=true` and `LOW_VERIFICATION_CONFIDENCE`; exactly 80 does not trigger this threshold alone. Missing confidence with usable visual findings also produces MANUAL_REVIEW with `VERIFICATION_CONFIDENCE_UNAVAILABLE`. Mock confidence is synthetic fixture data only. Gemini self-confidence and ORB registration scores are uncalibrated estimates and require labelled-photo evaluation before operational use.

### Real API examples

The following full response objects are historical baseline examples captured from the prototype with `VISION_PROVIDER=mock`; they predate the additive alignment/confidence fields described above and do not show those fields. `SUB-REVIEW` is a temporary copy of the PASS fixture with a blur limitation added for the status example. Request examples omit the configured API key header for readability. Use the current response schema and `/docs` output when integrating the new fields.

#### PASS

Request: `{"submission_id":"SUB-PASS"}`

```json
{"contract_version":"1.1","verification_id":"VER-722DE14593C5","task_id":"TASK-100","submission_id":"SUB-PASS","verification_status":"PASS","verification_score":100.0,"score_status":"AVAILABLE","score_breakdown":{"image_evidence":100.0,"gps_consistency":100.0,"plan_compliance":100.0},"image_findings":{"before_observations":{"scattered_waste":"PRESENT","path_obstructed":"PRESENT","overflow":"PRESENT"},"after_observations":{"scattered_waste":"ABSENT","path_obstructed":"ABSENT","overflow":"ABSENT"},"visual_change":"IMPROVED","limitations":[]},"location_finding":{"status":"CONSISTENT","score":100.0,"reasons":["Reported location is 38.7 m from the task site (within 150 m)."]},"plan_compliance_findings":[{"requirement_id":"STEP-01","label":"Remove visible scattered waste","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-1"]},{"requirement_id":"STEP-02","label":"Clear the walking path","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-1"]},{"requirement_id":"STEP-03","label":"Remove visible overflow","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-1"]}],"remarks":["Reported location is 38.7 m from the task site (within 150 m).","Weighted score is 100.0; configured threshold is 75.0."],"requires_manual_review":false,"rule_version":"demo-0.2","vision_provider":"mock","vision_model_version":"mock-vision-1","vision_prompt_version":"mock-prompt-1","evidence_refs":["IMG-BEFORE-1","IMG-AFTER-1"],"created_at":"2026-10-17T18:38:18.827171+00:00","reason_codes":["QUALITY_NOT_CHECKED"],"failed_requirement_ids":[]}
```

#### FAIL

Request: `{"submission_id":"SUB-FAIL"}`

```json
{"contract_version":"1.1","verification_id":"VER-C885E8B85EF3","task_id":"TASK-100","submission_id":"SUB-FAIL","verification_status":"FAIL","verification_score":67.5,"score_status":"AVAILABLE","score_breakdown":{"image_evidence":50.0,"gps_consistency":100.0,"plan_compliance":66.66666666666667},"image_findings":{"before_observations":{"scattered_waste":"PRESENT","path_obstructed":"PRESENT","overflow":"PRESENT"},"after_observations":{"scattered_waste":"PRESENT","path_obstructed":"ABSENT","overflow":"ABSENT"},"visual_change":"IMPROVED","limitations":[]},"location_finding":{"status":"CONSISTENT","score":100.0,"reasons":["Reported location is 22.2 m from the task site (within 150 m)."]},"plan_compliance_findings":[{"requirement_id":"STEP-01","label":"Remove visible scattered waste","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"CONTRADICTED","reason":"After-image finding shows scattered waste remains visible.","evidence_ids":["IMG-AFTER-2"]},{"requirement_id":"STEP-02","label":"Clear the walking path","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-2"]},{"requirement_id":"STEP-03","label":"Remove visible overflow","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-2"]}],"remarks":["Mandatory requirement(s) not met: Remove visible scattered waste (STEP-01).","Reported location is 22.2 m from the task site (within 150 m).","Remove visible scattered waste (STEP-01; evidence: IMG-AFTER-2): After-image finding shows scattered waste remains visible.","Weighted score was informational and did not determine the outcome: 67.5 (configured threshold: 75.0)."],"requires_manual_review":false,"rule_version":"demo-0.2","vision_provider":"mock","vision_model_version":"mock-vision-1","vision_prompt_version":"mock-prompt-1","evidence_refs":["IMG-BEFORE-2","IMG-AFTER-2"],"created_at":"2026-10-17T18:38:18.832744+00:00","reason_codes":["MANDATORY_REQUIREMENT_CONTRADICTED","QUALITY_NOT_CHECKED"],"failed_requirement_ids":["STEP-01"]}
```

#### INCONCLUSIVE

Request: `{"submission_id":"SUB-INCOMPLETE"}`

```json
{"contract_version":"1.1","verification_id":"VER-72F65E4D612F","task_id":"TASK-100","submission_id":"SUB-INCOMPLETE","verification_status":"INCONCLUSIVE","verification_score":null,"score_status":"UNAVAILABLE","score_breakdown":null,"image_findings":{"status":"UNAVAILABLE","reason":"No usable image analysis."},"location_finding":{"status":"UNAVAILABLE","score":null,"reasons":["No usable GPS event was submitted."]},"plan_compliance_findings":[{"requirement_id":"STEP-01","label":"Remove visible scattered waste","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"UNKNOWN","reason":"Available checklist or visual evidence cannot determine this requirement.","evidence_ids":[]},{"requirement_id":"STEP-02","label":"Clear the walking path","mandatory":true,"worker_claim":"UNKNOWN","evidence_finding":"UNKNOWN","reason":"Available checklist or visual evidence cannot determine this requirement.","evidence_ids":[]},{"requirement_id":"STEP-03","label":"Remove visible overflow","mandatory":true,"worker_claim":"UNKNOWN","evidence_finding":"UNKNOWN","reason":"Available checklist or visual evidence cannot determine this requirement.","evidence_ids":[]}],"remarks":["No usable GPS event was submitted.","Remove visible scattered waste (STEP-01; evidence: none available): Available checklist or visual evidence cannot determine this requirement.","Clear the walking path (STEP-02; evidence: none available): Available checklist or visual evidence cannot determine this requirement.","Remove visible overflow (STEP-03; evidence: none available): Available checklist or visual evidence cannot determine this requirement.","Required evidence unavailable: AFTER_IMAGE."],"requires_manual_review":true,"rule_version":"demo-0.2","vision_provider":"mock","vision_model_version":"mock-vision-1","vision_prompt_version":"mock-prompt-1","evidence_refs":["IMG-BEFORE-3","IMG-AFTER-3"],"created_at":"2026-10-17T18:38:18.836462+00:00","reason_codes":["MANDATORY_REQUIREMENT_NOT_CLAIMED","EVIDENCE_MISSING","ANALYSIS_UNAVAILABLE","QUALITY_NOT_CHECKED"],"failed_requirement_ids":[]}
```

#### MANUAL_REVIEW

Request: `{"submission_id":"SUB-REVIEW"}` (temporary mock fixture with a blur limitation)

```json
{"contract_version":"1.1","verification_id":"VER-E344CEE38CCA","task_id":"TASK-100","submission_id":"SUB-REVIEW","verification_status":"MANUAL_REVIEW","verification_score":100.0,"score_status":"AVAILABLE","score_breakdown":{"image_evidence":100.0,"gps_consistency":100.0,"plan_compliance":100.0},"image_findings":{"before_observations":{"scattered_waste":"PRESENT","path_obstructed":"PRESENT","overflow":"PRESENT"},"after_observations":{"scattered_waste":"ABSENT","path_obstructed":"ABSENT","overflow":"ABSENT"},"visual_change":"IMPROVED","limitations":["after image is blurry"]},"location_finding":{"status":"CONSISTENT","score":100.0,"reasons":["Reported location is 38.7 m from the task site (within 150 m)."]},"plan_compliance_findings":[{"requirement_id":"STEP-01","label":"Remove visible scattered waste","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-1"]},{"requirement_id":"STEP-02","label":"Clear the walking path","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-1"]},{"requirement_id":"STEP-03","label":"Remove visible overflow","mandatory":true,"worker_claim":"COMPLETED","evidence_finding":"SUPPORTED","reason":"Checklist claim agrees with the structured after-image finding.","evidence_ids":["IMG-AFTER-1"]}],"remarks":["Reported location is 38.7 m from the task site (within 150 m).","Weighted score is 100.0; configured threshold is 75.0.","Image limitation: after image is blurry","Conflicting or limited evidence requires a human reviewer."],"requires_manual_review":true,"rule_version":"demo-0.2","vision_provider":"mock","vision_model_version":"mock-vision-1","vision_prompt_version":"mock-prompt-1","evidence_refs":["IMG-BEFORE-1","IMG-AFTER-1"],"created_at":"2026-10-17T18:38:18.840451+00:00","reason_codes":["IMAGE_UNCERTAIN","QUALITY_NOT_CHECKED"],"failed_requirement_ids":[]}
```
