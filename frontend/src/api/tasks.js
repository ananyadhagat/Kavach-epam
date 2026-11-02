import { apiRequest } from "./client.js";
import { ApiError } from "./errors.js";
import {
  EVIDENCE_MIME_TYPES,
  getEvidenceFileValidationError,
  MAX_EVIDENCE_SIZE_BYTES,
} from "../evidence/evidence-policy.js";
import { toLocationEventPayload } from "../location/geolocation.js";

const LIFECYCLE_ACTIONS = new Set([
  "accept",
  "reject",
  "start",
  "pause",
  "resume",
]);
const EVIDENCE_TYPES = new Set(["BEFORE", "AFTER"]);
const EVIDENCE_STATUSES = new Set(["STORED"]);
const LOCATION_EVENT_TYPES = new Set(["ARRIVAL", "COMPLETION"]);
const LOCATION_CAPTURE_STATUSES = new Set([
  "CAPTURED",
  "UNAVAILABLE",
  "INACCURATE",
]);
const BLOCKER_STATUSES = new Set(["OPEN", "RESOLVED"]);
const TASK_STATUSES = new Set([
  "ASSIGNED",
  "ACCEPTED",
  "REJECTED",
  "IN_PROGRESS",
  "PAUSED",
  "BLOCKED",
  "COMPLETION_SUBMITTED",
]);
export { EVIDENCE_MIME_TYPES, MAX_EVIDENCE_SIZE_BYTES };

function isTaskResponse(response) {
  const isLocationSummary = (summary, eventType) =>
    summary === null ||
    summary === undefined ||
    (typeof summary === "object" &&
      summary.event_type === eventType &&
      typeof summary.location_event_id === "string" &&
      LOCATION_CAPTURE_STATUSES.has(summary.capture_status) &&
      typeof summary.accepted_for_progress === "boolean" &&
      (summary.latitude === null ||
        (Number.isFinite(summary.latitude) &&
          summary.latitude >= -90 &&
          summary.latitude <= 90)) &&
      (summary.longitude === null ||
        (Number.isFinite(summary.longitude) &&
          summary.longitude >= -180 &&
          summary.longitude <= 180)) &&
      (summary.accuracy_meters === null ||
        (Number.isFinite(summary.accuracy_meters) &&
          summary.accuracy_meters > 0 &&
          summary.accuracy_meters <= 100_000)) &&
      (summary.capture_status !== "CAPTURED" ||
        (Number.isFinite(summary.latitude) &&
          Number.isFinite(summary.longitude) &&
          Number.isFinite(summary.accuracy_meters))) &&
      typeof summary.received_at_server === "string" &&
      (summary.rejection_reason === null ||
        typeof summary.rejection_reason === "string"));

  return (
    response &&
    typeof response === "object" &&
    typeof response.task_id === "string" &&
    typeof response.title === "string" &&
    typeof response.description === "string" &&
    TASK_STATUSES.has(response.status) &&
    typeof response.priority === "string" &&
    response.location &&
    typeof response.location.address === "string" &&
    (response.gps_accuracy_threshold_meters === null ||
      response.gps_accuracy_threshold_meters === undefined ||
      (Number.isFinite(response.gps_accuracy_threshold_meters) &&
        response.gps_accuracy_threshold_meters > 0)) &&
    (response.arrival_location_accepted === undefined ||
      typeof response.arrival_location_accepted === "boolean") &&
    (response.completion_location_accepted === undefined ||
      typeof response.completion_location_accepted === "boolean") &&
    isLocationSummary(response.latest_arrival_location, "ARRIVAL") &&
    (response.accepted_arrival_location === undefined ||
      isLocationSummary(response.accepted_arrival_location, "ARRIVAL")) &&
    isLocationSummary(response.latest_completion_location, "COMPLETION")
  );
}

export async function getAssignedTasks({ signal } = {}) {
  const response = await apiRequest("worker/tasks", {
    method: "GET",
    signal,
  });

  if (
    !response ||
    typeof response !== "object" ||
    !Array.isArray(response.tasks)
  ) {
    throw new ApiError("The task service returned an unexpected response.");
  }

  return response.tasks;
}

export async function getTaskDetails(taskId, { signal } = {}) {
  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}`,
    {
      cache: "no-store",
      method: "GET",
      signal,
    },
  );

  if (!isTaskResponse(response) || response.task_id !== taskId) {
    throw new ApiError("The task service returned an unexpected response.");
  }

  return response;
}

export async function transitionTask(
  taskId,
  action,
  { body, signal } = {},
) {
  if (!LIFECYCLE_ACTIONS.has(action)) {
    throw new ApiError("This task action is not supported.");
  }

  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}/${action}`,
    {
      method: "POST",
      body,
      signal,
    },
  );

  if (
    !response ||
    typeof response !== "object" ||
    !isTaskResponse(response.task) ||
    typeof response.message !== "string"
  ) {
    throw new ApiError("The task service returned an unexpected response.");
  }

  return response;
}

function isBlockerRecord(blocker, taskId) {
  return (
    blocker &&
    typeof blocker === "object" &&
    typeof blocker.blocker_id === "string" &&
    blocker.task_id === taskId &&
    typeof blocker.worker_id === "string" &&
    (blocker.step_id === null || typeof blocker.step_id === "string") &&
    typeof blocker.reason_code === "string" &&
    typeof blocker.description === "string" &&
    BLOCKER_STATUSES.has(blocker.status) &&
    TASK_STATUSES.has(blocker.previous_status) &&
    typeof blocker.reported_at === "string" &&
    (blocker.resolved_at === null || typeof blocker.resolved_at === "string") &&
    (blocker.resolved_by === null || typeof blocker.resolved_by === "string") &&
    (blocker.resolution_note === null ||
      typeof blocker.resolution_note === "string")
  );
}

function safeBlockerRecord(blocker) {
  return {
    reason_code: blocker.reason_code,
    description: blocker.description,
    status: blocker.status,
    previous_status: blocker.previous_status,
    reported_at: blocker.reported_at,
    resolved_at: blocker.resolved_at,
    resolved_by: blocker.resolved_by,
    resolution_note: blocker.resolution_note,
  };
}

export async function getBlockerReasonCodes({ signal } = {}) {
  const response = await apiRequest("worker/blockers/reason-codes", {
    method: "GET",
    signal,
  });

  if (
    !response ||
    typeof response !== "object" ||
    !Array.isArray(response.reason_codes) ||
    !response.reason_codes.every(
      (item) =>
        item &&
        typeof item === "object" &&
        typeof item.code === "string" &&
        /^[A-Z][A-Z0-9_]{0,49}$/.test(item.code),
    )
  ) {
    throw new ApiError(
      "The blocker reason-code service returned an unexpected response.",
    );
  }

  return [...new Set(response.reason_codes.map((item) => item.code))];
}

export async function getTaskBlockers(taskId, { signal } = {}) {
  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}/blockers`,
    {
      method: "GET",
      signal,
    },
  );

  if (
    !response ||
    typeof response !== "object" ||
    response.task_id !== taskId ||
    !Array.isArray(response.blockers) ||
    !response.blockers.every((blocker) => isBlockerRecord(blocker, taskId))
  ) {
    throw new ApiError("The blocker service returned an unexpected response.");
  }

  return response.blockers.map(safeBlockerRecord);
}

export async function reportTaskBlocker(
  taskId,
  reasonCode,
  description,
  { signal } = {},
) {
  if (
    typeof reasonCode !== "string" ||
    !/^[A-Z][A-Z0-9_]{0,49}$/.test(reasonCode) ||
    typeof description !== "string" ||
    description.trim().length < 1 ||
    description.trim().length > 500
  ) {
    throw new ApiError("Enter a valid reason code and description.");
  }

  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}/blockers`,
    {
      method: "POST",
      body: {
        reason_code: reasonCode,
        description: description.trim(),
      },
      signal,
    },
  );

  if (
    !response ||
    typeof response !== "object" ||
    !isBlockerRecord(response.blocker, taskId) ||
    !isTaskResponse(response.task) ||
    response.task.status !== "BLOCKED" ||
    typeof response.message !== "string"
  ) {
    throw new ApiError("The blocker service returned an unexpected response.");
  }

  return {
    blocker: safeBlockerRecord(response.blocker),
    task: response.task,
    message: response.message,
  };
}

function isLocationEvent(event, taskId, eventType) {
  const validLatitude =
    event?.latitude === null ||
    (Number.isFinite(event?.latitude) &&
      event.latitude >= -90 &&
      event.latitude <= 90);
  const validLongitude =
    event?.longitude === null ||
    (Number.isFinite(event?.longitude) &&
      event.longitude >= -180 &&
      event.longitude <= 180);
  const validAccuracy =
    event?.accuracy_meters === null ||
    (Number.isFinite(event?.accuracy_meters) &&
      event.accuracy_meters > 0 &&
      event.accuracy_meters <= 100_000);

  return (
    event &&
    typeof event === "object" &&
    typeof event.location_event_id === "string" &&
    event.location_event_id.length > 0 &&
    event.task_id === taskId &&
    typeof event.worker_id === "string" &&
    event.event_type === eventType &&
    LOCATION_CAPTURE_STATUSES.has(event.capture_status) &&
    validLatitude &&
    validLongitude &&
    validAccuracy &&
    (event.capture_status !== "CAPTURED" ||
      (typeof event.latitude === "number" &&
        typeof event.longitude === "number" &&
        typeof event.accuracy_meters === "number")) &&
    (event.capture_status === "CAPTURED" ||
      (event.latitude === null && event.longitude === null)) &&
    (event.captured_at_device === null ||
      typeof event.captured_at_device === "string") &&
    typeof event.received_at_server === "string"
  );
}

function safeLocationEvent(event) {
  return {
    location_event_id: event.location_event_id,
    task_id: event.task_id,
    event_type: event.event_type,
    capture_status: event.capture_status,
    latitude: event.latitude,
    longitude: event.longitude,
    accuracy_meters: event.accuracy_meters,
    captured_at_device: event.captured_at_device,
    received_at_server: event.received_at_server,
  };
}

export async function submitTaskLocation(
  taskId,
  eventType,
  location,
  { signal } = {},
) {
  if (!LOCATION_EVENT_TYPES.has(eventType)) {
    throw new ApiError("This location event type is not supported.");
  }

  if (
    !location ||
    location.capture_status !== "CAPTURED" ||
    !Number.isFinite(location.latitude) ||
    location.latitude < -90 ||
    location.latitude > 90 ||
    !Number.isFinite(location.longitude) ||
    location.longitude < -180 ||
    location.longitude > 180 ||
    !Number.isFinite(location.accuracy_meters) ||
    location.accuracy_meters <= 0 ||
    location.accuracy_meters > 100_000 ||
    typeof location.captured_at_device !== "string"
  ) {
    throw new ApiError("Capture a valid location before submitting.");
  }

  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}/${
      eventType === "ARRIVAL" ? "arrival" : "completion-location"
    }`,
    {
      method: "POST",
      body: toLocationEventPayload(eventType, location),
      signal,
    },
  );

  if (
    !response ||
    typeof response !== "object" ||
    !isLocationEvent(response.location_event, taskId, eventType)
  ) {
    throw new ApiError("The location service returned an unexpected response.");
  }

  return safeLocationEvent(response.location_event);
}

function isEvidenceItem(evidence, taskId) {
  return (
    evidence &&
    typeof evidence === "object" &&
    typeof evidence.evidence_id === "string" &&
    evidence.task_id === taskId &&
    typeof evidence.worker_id === "string" &&
    EVIDENCE_TYPES.has(evidence.evidence_type) &&
    typeof evidence.original_filename === "string" &&
    typeof evidence.mime_type === "string" &&
    Number.isInteger(evidence.size_bytes) &&
    evidence.size_bytes > 0 &&
    EVIDENCE_STATUSES.has(evidence.status) &&
    typeof evidence.uploaded_at === "string"
  );
}

function safeEvidenceItem(evidence) {
  return {
    evidence_id: evidence.evidence_id,
    worker_id: evidence.worker_id,
    evidence_type: evidence.evidence_type,
    original_filename: evidence.original_filename,
    mime_type: evidence.mime_type,
    size_bytes: evidence.size_bytes,
    status: evidence.status,
    uploaded_at: evidence.uploaded_at,
  };
}

export async function getTaskEvidence(taskId, { signal } = {}) {
  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}/evidence`,
    {
      cache: "no-store",
      method: "GET",
      signal,
    },
  );

  if (
    !response ||
    typeof response !== "object" ||
    response.task_id !== taskId ||
    !Array.isArray(response.evidence) ||
    !response.evidence.every((item) => isEvidenceItem(item, taskId))
  ) {
    throw new ApiError("The evidence service returned an unexpected response.");
  }

  return response.evidence.map(safeEvidenceItem);
}

function isCompletionSubmission(submission, taskId, claim) {
  return (
    submission &&
    typeof submission === "object" &&
    typeof submission.submission_id === "string" &&
    submission.submission_id.length > 0 &&
    submission.task_id === taskId &&
    typeof submission.worker_id === "string" &&
    submission.worker_id.length > 0 &&
    Array.isArray(submission.evidence_ids) &&
    submission.evidence_ids.length === claim.evidence_ids.length &&
    submission.evidence_ids.every(
      (evidenceId, index) => evidenceId === claim.evidence_ids[index],
    ) &&
    submission.completion_location_event_id ===
      claim.completion_location_event_id &&
    submission.notes === (claim.notes ?? null) &&
    typeof submission.submitted_at === "string" &&
    !Number.isNaN(Date.parse(submission.submitted_at)) &&
    submission.status === "COMPLETION_SUBMITTED"
  );
}

export async function submitTaskCompletion(
  taskId,
  claim,
  idempotencyKey,
  { signal } = {},
) {
  if (
    typeof idempotencyKey !== "string" ||
    idempotencyKey.trim().length === 0 ||
    idempotencyKey.length > 200 ||
    !claim ||
    !Array.isArray(claim.evidence_ids) ||
    claim.evidence_ids.length < 2 ||
    !claim.evidence_ids.every(
      (evidenceId) =>
        typeof evidenceId === "string" && evidenceId.trim().length > 0,
    ) ||
    new Set(claim.evidence_ids).size !== claim.evidence_ids.length ||
    typeof claim.completion_location_event_id !== "string" ||
    claim.completion_location_event_id.trim().length === 0 ||
    (claim.notes !== undefined &&
      (typeof claim.notes !== "string" || claim.notes.length > 2000)) ||
    Object.keys(claim).some(
      (key) =>
        !["evidence_ids", "completion_location_event_id", "notes"].includes(
          key,
        ),
    )
  ) {
    throw new ApiError("The completion request is missing required information.");
  }

  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}/completion`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: claim,
      signal,
    },
  );

  if (
    !response ||
    typeof response !== "object" ||
    !isCompletionSubmission(response.submission, taskId, claim) ||
    typeof response.message !== "string"
  ) {
    throw new ApiError(
      "The completion service returned an unexpected response.",
    );
  }

  return {
    submission: {
      submission_id: response.submission.submission_id,
      task_id: response.submission.task_id,
      evidence_ids: [...response.submission.evidence_ids],
      completion_location_event_id:
        response.submission.completion_location_event_id,
      submitted_at: response.submission.submitted_at,
      status: response.submission.status,
    },
    message: response.message,
  };
}

export async function uploadTaskEvidence(
  taskId,
  evidenceType,
  file,
  { signal } = {},
) {
  if (!EVIDENCE_TYPES.has(evidenceType)) {
    throw new ApiError("The selected evidence type is not supported.");
  }

  if (!(file instanceof File)) {
    throw new ApiError("Select an image file to upload.");
  }

  const validationError = getEvidenceFileValidationError(file);
  if (validationError) {
    throw new ApiError(validationError);
  }

  const body = new FormData();
  body.append("evidence_type", evidenceType);
  body.append("file", file);

  const response = await apiRequest(
    `worker/tasks/${encodeURIComponent(taskId)}/evidence`,
    {
      method: "POST",
      body,
      signal,
    },
  );

  const evidence = response?.evidence;
  if (
    !response ||
    typeof response !== "object" ||
    !isEvidenceItem(evidence, taskId) ||
    typeof response.duplicate !== "boolean" ||
    typeof response.message !== "string"
  ) {
    throw new ApiError("The evidence service returned an unexpected response.");
  }

  return {
    evidence: safeEvidenceItem(evidence),
    duplicate: response.duplicate,
    message: response.message,
  };
}
