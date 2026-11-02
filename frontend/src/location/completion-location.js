function isValidCoordinates(location) {
  return (
    Number.isFinite(location?.latitude) &&
    location.latitude >= -90 &&
    location.latitude <= 90 &&
    Number.isFinite(location?.longitude) &&
    location.longitude >= -180 &&
    location.longitude <= 180
  );
}

function isAcceptedEvent(
  task,
  event,
  requireProgressConfirmation,
  taskDetailsSummary = false,
) {
  const threshold = task?.gps_accuracy_threshold_meters;

  return (
    typeof task?.task_id === "string" &&
    task?.completion_location_accepted === true &&
    typeof task.completion_location_event_id === "string" &&
    event?.location_event_id === task.completion_location_event_id &&
    (event?.task_id === task.task_id ||
      (taskDetailsSummary && event?.task_id === undefined)) &&
    event?.event_type === "COMPLETION" &&
    event?.capture_status === "CAPTURED" &&
    (!requireProgressConfirmation || event.accepted_for_progress === true) &&
    isValidCoordinates(event) &&
    Number.isFinite(event.accuracy_meters) &&
    event.accuracy_meters > 0 &&
    Number.isFinite(threshold) &&
    threshold > 0 &&
    event.accuracy_meters <= threshold
  );
}

export function getAcceptedCompletionLocation(
  task,
  submittedEvent = null,
) {
  const referenceId = task?.completion_location_event_id;
  if (
    task?.completion_location_accepted !== true ||
    typeof referenceId !== "string" ||
    referenceId.length === 0
  ) {
    return null;
  }

  if (
    task.latest_completion_location?.location_event_id === referenceId
  ) {
    const event = task.latest_completion_location;
    if (!isAcceptedEvent(task, event, true, true)) return null;
    return toCompletionLocation(task.task_id, event);
  }

  if (submittedEvent?.location_event_id === referenceId) {
    if (!isAcceptedEvent(task, submittedEvent, false)) return null;
    return toCompletionLocation(task.task_id, submittedEvent);
  }

  return null;
}

function toCompletionLocation(taskId, event) {
  return {
    locationEventId: event.location_event_id,
    taskId,
    latitude: event.latitude,
    longitude: event.longitude,
    eventType: "COMPLETION",
    accuracyMeters: event.accuracy_meters,
    capturedAt: event.captured_at_device,
    receivedAt: event.received_at_server,
    isAccepted: true,
  };
}

export function getAcceptedCompletionLocationId(
  task,
  submittedEvent = null,
) {
  return getAcceptedCompletionLocation(task, submittedEvent)?.locationEventId ??
    null;
}

export function isCompletionLocationCaptureNeeded(task) {
  return getAcceptedCompletionLocationId(task) === null;
}

export function isCompletionWorkflowReady({
  isRefreshing,
  readinessError,
  attemptStorageError,
  actionsDisabled,
  task,
  evidence,
  submittedCompletionEvent,
}) {
  if (
    isRefreshing ||
    readinessError ||
    attemptStorageError ||
    actionsDisabled ||
    task?.status !== "IN_PROGRESS"
  ) {
    return false;
  }

  const hasStoredEvidence = (type) =>
    evidence?.some(
      (item) =>
        item.evidence_type === type &&
        item.status === "STORED" &&
        item.worker_id === task.assigned_worker_id,
    ) === true;

  return (
    task.arrival_location_accepted === true &&
    Boolean(task.arrival_location_event_id) &&
    hasStoredEvidence("BEFORE") &&
    hasStoredEvidence("AFTER") &&
    getAcceptedCompletionLocationId(task, submittedCompletionEvent) !== null
  );
}
