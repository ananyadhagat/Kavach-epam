import assert from "node:assert/strict";
import test from "node:test";
import {
  getAcceptedCompletionLocation,
  getAcceptedCompletionLocationId,
  isCompletionLocationCaptureNeeded,
  isCompletionWorkflowReady,
} from "../src/location/completion-location.js";
import { getAcceptedArrivalLocation } from "../src/location/worker-location.js";

const task = {
  task_id: "TASK-100",
  assigned_worker_id: "worker-001",
  status: "IN_PROGRESS",
  gps_accuracy_threshold_meters: 100,
  arrival_location_event_id: "arrival-event",
  arrival_location_accepted: true,
};

const completionLocation = {
  location_event_id: "completion-event",
  task_id: "TASK-100",
  event_type: "COMPLETION",
  capture_status: "CAPTURED",
  latitude: 23.25,
  longitude: 77.47,
  accuracy_meters: 42,
  captured_at_device: "2026-11-02T03:00:00Z",
  received_at_server: "2026-11-02T03:00:01Z",
};

const completionSummary = {
  location_event_id: completionLocation.location_event_id,
  event_type: completionLocation.event_type,
  capture_status: completionLocation.capture_status,
  latitude: completionLocation.latitude,
  longitude: completionLocation.longitude,
  accuracy_meters: completionLocation.accuracy_meters,
  captured_at_device: completionLocation.captured_at_device,
  received_at_server: completionLocation.received_at_server,
  accepted_for_progress: true,
  rejection_reason: null,
};

const persistedTask = {
  ...task,
  completion_location_event_id: completionLocation.location_event_id,
  completion_location_accepted: true,
  latest_completion_location: completionSummary,
};

const evidence = [
  {
    evidence_type: "BEFORE",
    status: "STORED",
    worker_id: task.assigned_worker_id,
  },
  {
    evidence_type: "AFTER",
    status: "STORED",
    worker_id: task.assigned_worker_id,
  },
];

function isReady(overrides = {}) {
  return isCompletionWorkflowReady({
    isRefreshing: false,
    readinessError: null,
    attemptStorageError: null,
    actionsDisabled: false,
    task: persistedTask,
    evidence,
    submittedCompletionEvent: null,
    ...overrides,
  });
}

test("no completion location is required initially", () => {
  assert.equal(getAcceptedCompletionLocationId(task), null);
  assert.equal(isCompletionLocationCaptureNeeded(task), true);
  assert.equal(isReady({ task, evidence }), false);
});

test("a successfully captured completion event satisfies location readiness", () => {
  const taskAfterCapture = {
    ...task,
    completion_location_event_id: completionLocation.location_event_id,
    completion_location_accepted: true,
  };

  assert.equal(
    getAcceptedCompletionLocationId(taskAfterCapture, completionLocation),
    completionLocation.location_event_id,
  );
  assert.equal(
    isReady({
      task: taskAfterCapture,
      submittedCompletionEvent: completionLocation,
    }),
    true,
  );
});

test("a persisted completion event restores readiness after page refresh", () => {
  assert.equal(
    getAcceptedCompletionLocationId(persistedTask),
    completionLocation.location_event_id,
  );
  assert.equal(isCompletionLocationCaptureNeeded(persistedTask), false);
  assert.equal(isReady(), true);
});

test("the completion checklist stays completed after task-details refresh", () => {
  const refreshedTask = {
    ...persistedTask,
    latest_completion_location: { ...completionSummary },
  };

  assert.equal(isReady({ task: refreshedTask }), true);
  assert.equal(
    getAcceptedCompletionLocationId(refreshedTask),
    completionLocation.location_event_id,
  );
});

test("the accepted reference is restored separately from a newer event", () => {
  const taskWithNewerEvent = {
    ...persistedTask,
    latest_completion_location: {
      ...persistedTask.latest_completion_location,
      location_event_id: "newer-event",
      capture_status: "INACCURATE",
      accepted_for_progress: false,
      latitude: null,
      longitude: null,
    },
  };

  assert.equal(getAcceptedCompletionLocationId(taskWithNewerEvent), null);
  assert.equal(isCompletionLocationCaptureNeeded(taskWithNewerEvent), true);
  assert.equal(isReady({ task: taskWithNewerEvent }), false);
});

test("arrival location alone never satisfies completion location readiness", () => {
  assert.equal(getAcceptedCompletionLocationId(task), null);
  assert.equal(isReady({ task }), false);
});

test("a completion response for another task or event cannot satisfy readiness", () => {
  const taskWithReference = {
    ...task,
    completion_location_event_id: completionLocation.location_event_id,
    completion_location_accepted: true,
  };
  const wrongTaskEvent = {
    ...completionLocation,
    task_id: "TASK-200",
  };
  const wrongEventReference = {
    ...persistedTask,
    completion_location_event_id: "different-event",
  };

  assert.equal(
    getAcceptedCompletionLocationId(taskWithReference, wrongTaskEvent),
    null,
  );
  assert.equal(getAcceptedCompletionLocationId(wrongEventReference), null);
});

test("inaccurate or over-threshold completion events are not accepted", () => {
  const inaccurateTask = {
    ...persistedTask,
    latest_completion_location: {
      ...persistedTask.latest_completion_location,
      capture_status: "INACCURATE",
    },
  };
  const overThresholdTask = {
    ...persistedTask,
    latest_completion_location: {
      ...persistedTask.latest_completion_location,
      accuracy_meters: 101,
    },
  };
  const arrivalAsCompletionTask = {
    ...persistedTask,
    latest_completion_location: {
      ...persistedTask.latest_completion_location,
      event_type: "ARRIVAL",
    },
  };

  assert.equal(getAcceptedCompletionLocationId(inaccurateTask), null);
  assert.equal(getAcceptedCompletionLocationId(overThresholdTask), null);
  assert.equal(getAcceptedCompletionLocationId(arrivalAsCompletionTask), null);
  assert.equal(isReady({ task: inaccurateTask }), false);
  assert.equal(isReady({ task: overThresholdTask }), false);
  assert.equal(isReady({ task: arrivalAsCompletionTask }), false);
});

test("completion map location uses the persisted completion event coordinates", () => {
  assert.deepEqual(getAcceptedCompletionLocation(persistedTask), {
    locationEventId: completionLocation.location_event_id,
    taskId: task.task_id,
    latitude: completionLocation.latitude,
    longitude: completionLocation.longitude,
    eventType: "COMPLETION",
    accuracyMeters: completionLocation.accuracy_meters,
    capturedAt: completionLocation.captured_at_device,
    receivedAt: completionLocation.received_at_server,
    isAccepted: true,
  });
});

test("arrival and completion map locations stay independent", () => {
  const arrivalEvent = {
    location_event_id: "arrival-event",
    event_type: "ARRIVAL",
    capture_status: "CAPTURED",
    accepted_for_progress: true,
    latitude: 23.2,
    longitude: 77.4,
    accuracy_meters: 55,
    captured_at_device: "2026-11-02T02:00:00Z",
    received_at_server: "2026-11-02T02:00:01Z",
  };
  const taskWithBothEvents = {
    ...persistedTask,
    accepted_arrival_location: arrivalEvent,
  };
  const arrivalMapLocation = getAcceptedArrivalLocation(taskWithBothEvents);
  const completionMapLocation =
    getAcceptedCompletionLocation(taskWithBothEvents);

  assert.equal(arrivalMapLocation.eventType, "ARRIVAL");
  assert.equal(arrivalMapLocation.latitude, arrivalEvent.latitude);
  assert.equal(completionMapLocation.eventType, "COMPLETION");
  assert.equal(completionMapLocation.latitude, completionLocation.latitude);
  assert.notEqual(arrivalMapLocation.latitude, completionMapLocation.latitude);
});

test("missing or invalid completion coordinates do not create a map location", () => {
  const missingCoordinates = {
    ...persistedTask,
    latest_completion_location: {
      ...completionSummary,
      latitude: null,
      longitude: null,
    },
  };
  const invalidCoordinates = {
    ...persistedTask,
    latest_completion_location: {
      ...completionSummary,
      latitude: 91,
    },
  };

  assert.equal(getAcceptedCompletionLocation(missingCoordinates), null);
  assert.equal(getAcceptedCompletionLocation(invalidCoordinates), null);
});

test("loading and API failure keep completion submission disabled", () => {
  assert.equal(isReady({ isRefreshing: true }), false);
  assert.equal(isReady({ readinessError: new Error("API unavailable") }), false);
  assert.equal(isReady({ task: null }), false);
});

test("completion submission needs every task and evidence prerequisite", () => {
  assert.equal(isReady(), true);
  assert.equal(isReady({ actionsDisabled: true }), false);
  assert.equal(isReady({ evidence: evidence.slice(0, 1) }), false);
  assert.equal(
    isReady({
      evidence: evidence.map((item) => ({
        ...item,
        worker_id: "worker-002",
      })),
    }),
    false,
  );
  assert.equal(
    isReady({ task: { ...persistedTask, status: "PAUSED" } }),
    false,
  );
  assert.equal(
    isReady({
      task: {
        ...persistedTask,
        arrival_location_accepted: false,
      },
    }),
    false,
  );
});
