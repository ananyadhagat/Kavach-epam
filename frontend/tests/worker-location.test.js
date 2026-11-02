import assert from "node:assert/strict";
import test from "node:test";
import {
  getAcceptedArrivalLocation,
  getWorkerLocationForMap,
} from "../src/location/worker-location.js";

const acceptedArrival = {
  location_event_id: "arrival-event-1",
  event_type: "ARRIVAL",
  capture_status: "CAPTURED",
  accepted_for_progress: true,
  latitude: 23.251983,
  longitude: 77.47637,
  accuracy_meters: 92,
  captured_at_device: "2026-11-01T10:00:29.060Z",
  received_at_server: "2026-11-01T10:00:34.987Z",
};

test("hydrates only the backend-confirmed accepted arrival location", () => {
  const task = {
    arrival_location_accepted: true,
    arrival_location_event_id: acceptedArrival.location_event_id,
    accepted_arrival_location: acceptedArrival,
    latest_completion_location: {
      ...acceptedArrival,
      event_type: "COMPLETION",
      latitude: 0,
      longitude: 0,
      received_at_server: "2026-11-02T10:00:00.000Z",
    },
  };

  assert.deepEqual(getAcceptedArrivalLocation(task), {
    latitude: 23.251983,
    longitude: 77.47637,
    eventType: "ARRIVAL",
    accuracyMeters: 92,
    capturedAt: "2026-11-01T10:00:29.060Z",
    receivedAt: "2026-11-01T10:00:34.987Z",
    isAccepted: true,
  });
});

test("supports a confirmed latest-arrival summary from older API responses", () => {
  const task = {
    arrival_location_accepted: true,
    arrival_location_event_id: acceptedArrival.location_event_id,
    latest_arrival_location: acceptedArrival,
  };

  assert.equal(getAcceptedArrivalLocation(task).latitude, 23.251983);
});

test("does not display an inaccurate or unconfirmed arrival as accepted", () => {
  assert.equal(
    getAcceptedArrivalLocation({
      arrival_location_accepted: false,
      arrival_location_event_id: acceptedArrival.location_event_id,
      latest_arrival_location: {
        ...acceptedArrival,
        accepted_for_progress: false,
      },
    }),
    null,
  );
  assert.equal(
    getAcceptedArrivalLocation({
      arrival_location_accepted: true,
      arrival_location_event_id: acceptedArrival.location_event_id,
      accepted_arrival_location: {
        ...acceptedArrival,
        capture_status: "INACCURATE",
      },
    }),
    null,
  );
});

test("ignores invalid backend coordinates without falling back to task location", () => {
  assert.equal(
    getAcceptedArrivalLocation({
      arrival_location_accepted: true,
      arrival_location_event_id: acceptedArrival.location_event_id,
      accepted_arrival_location: {
        ...acceptedArrival,
        latitude: 91,
      },
    }),
    null,
  );
});

test("shows a live GPS preview before save, then prefers a newer accepted backend fix", () => {
  const preview = {
    latitude: 23.25,
    longitude: 77.47,
    isAccepted: false,
  };
  const task = {
    arrival_location_accepted: true,
    arrival_location_event_id: acceptedArrival.location_event_id,
    accepted_arrival_location: {
      ...acceptedArrival,
      received_at_server: "2026-11-03T10:00:00.000Z",
    },
  };

  assert.equal(getWorkerLocationForMap(task, preview), preview);

  const newerAccepted = {
    ...preview,
    isAccepted: true,
    receivedAt: "2026-11-02T10:00:00.000Z",
  };
  assert.equal(
    getWorkerLocationForMap(task, newerAccepted).latitude,
    acceptedArrival.latitude,
  );
});
