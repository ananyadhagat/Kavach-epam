import assert from "node:assert/strict";
import test from "node:test";
import {
  acquireBestDeviceLocation,
  DEFAULT_GPS_ACQUISITION_TIMEOUT_MS,
  GPS_POSITION_TIMEOUT_MS,
  isLocationAcceptable,
  toLocationEventPayload,
} from "../src/location/geolocation.js";

const FIXED_NOW = Date.parse("2026-10-30T12:00:00.000Z");

function position({
  latitude = 28.6139,
  longitude = 77.209,
  accuracy = 12.5,
  timestamp = FIXED_NOW,
} = {}) {
  return {
    coords: { latitude, longitude, accuracy },
    timestamp,
  };
}

function createHarness() {
  let success;
  let failure;
  let timeoutCallback;
  const clearedWatchIds = [];
  const geolocation = {
    watchPosition(onSuccess, onFailure, options) {
      success = onSuccess;
      failure = onFailure;
      this.options = options;
      return 37;
    },
    clearWatch(id) {
      clearedWatchIds.push(id);
    },
  };

  return {
    geolocation,
    clearedWatchIds,
    send: (reading) => success(reading),
    fail: (error) => failure(error),
    fireTimeout: () => timeoutCallback(),
    schedule(callback, delay) {
      timeoutCallback = callback;
      this.timeoutDelay = delay;
      return 91;
    },
    cancel(id) {
      this.cancelledTimerId = id;
    },
  };
}

function acquire(harness, options = {}) {
  return acquireBestDeviceLocation(harness.geolocation, {
    thresholdMeters: 100,
    now: () => FIXED_NOW,
    schedule: harness.schedule.bind(harness),
    cancel: harness.cancel.bind(harness),
    ...options,
  });
}

test("continues after an initial 103 m reading and stops on a better acceptable fix", async () => {
  const harness = createHarness();
  const statuses = [];
  const resultPromise = acquire(harness, {
    onUpdate: ({ status }) => statuses.push(status),
  });

  harness.send(position({ accuracy: 103 }));
  harness.send(position({ accuracy: 82, latitude: 28.614 }));

  const result = await resultPromise;
  assert.equal(result.accuracy_meters, 82);
  assert.equal(result.latitude, 28.614);
  assert.equal(result.acquisition_status, "ACCEPTABLE");
  assert.deepEqual(statuses, ["ACQUIRING", "POOR", "ACCEPTABLE"]);
  assert.deepEqual(harness.geolocation.options, {
    enableHighAccuracy: true,
    maximumAge: 0,
    timeout: GPS_POSITION_TIMEOUT_MS,
  });
  assert.deepEqual(harness.clearedWatchIds, [37]);
  assert.equal(harness.cancelledTimerId, 91);
});

test("keeps the best reading and ignores later worse readings", async () => {
  const harness = createHarness();
  const resultPromise = acquire(harness, { thresholdMeters: 50 });

  harness.send(position({ accuracy: 75 }));
  harness.send(position({ accuracy: 80 }));
  harness.send(position({ accuracy: 40 }));

  const result = await resultPromise;
  assert.equal(result.accuracy_meters, 40);
  assert.equal(result.acquisition_status, "ACCEPTABLE");
  assert.equal(harness.clearedWatchIds.length, 1);
});

test("returns the best poor fix at the bounded acquisition timeout", async () => {
  const harness = createHarness();
  const statuses = [];
  const resultPromise = acquire(harness, {
    timeoutMs: DEFAULT_GPS_ACQUISITION_TIMEOUT_MS,
    onUpdate: ({ status }) => statuses.push(status),
  });

  harness.send(position({ accuracy: 130 }));
  harness.send(position({ accuracy: 103 }));
  harness.fireTimeout();

  const result = await resultPromise;
  assert.equal(result.accuracy_meters, 103);
  assert.equal(result.acquisition_status, "TIMEOUT");
  assert.deepEqual(statuses, ["ACQUIRING", "POOR", "IMPROVING", "TIMEOUT"]);
  assert.equal(harness.timeoutDelay, DEFAULT_GPS_ACQUISITION_TIMEOUT_MS);
  assert.equal(harness.clearedWatchIds.length, 1);
});

test("rejects when acquisition times out without a valid fix", async () => {
  const harness = createHarness();
  const updates = [];
  const resultPromise = acquire(harness, {
    onUpdate: (update) => updates.push(update),
  });
  harness.fireTimeout();

  await assert.rejects(resultPromise, (error) => {
    assert.equal(error.code, "acquisition-timeout");
    return /timed out/i.test(error.message);
  });
  assert.deepEqual(
    updates.map(({ status, bestAccuracyMeters }) => ({
      status,
      bestAccuracyMeters,
    })),
    [
      { status: "ACQUIRING", bestAccuracyMeters: null },
      { status: "TIMEOUT", bestAccuracyMeters: null },
    ],
  );
  assert.deepEqual(harness.clearedWatchIds, [37]);
});

test("permission denial ends acquisition immediately", async () => {
  const deniedHarness = createHarness();
  const deniedPromise = acquire(deniedHarness);
  deniedHarness.fail(Object.assign(new Error(), { code: 1 }));
  await assert.rejects(deniedPromise, (error) => {
    assert.equal(error.code, "permission-denied");
    return /browser settings.*phone settings/i.test(error.message);
  });
});

test("position unavailable and per-position timeout allow acquisition to continue", async () => {
  const unavailableHarness = createHarness();
  const statuses = [];
  const unavailablePromise = acquire(unavailableHarness, {
    onUpdate: ({ status }) => statuses.push(status),
  });
  unavailableHarness.fail(Object.assign(new Error(), { code: 2 }));
  unavailableHarness.fail(Object.assign(new Error(), { code: 3 }));
  unavailableHarness.send(position({ accuracy: 34 }));

  const result = await unavailablePromise;
  assert.equal(result.accuracy_meters, 34);
  assert.equal(result.acquisition_status, "ACCEPTABLE");
  assert.deepEqual(statuses, [
    "ACQUIRING",
    "UNAVAILABLE",
    "POSITION_TIMEOUT",
    "ACCEPTABLE",
  ]);
  assert.equal(unavailableHarness.clearedWatchIds.length, 1);
});

test("ignores invalid and stale positions while continuing acquisition", async () => {
  const harness = createHarness();
  const resultPromise = acquire(harness);

  harness.send(position({ latitude: 91, accuracy: 5 }));
  harness.send(position({ timestamp: FIXED_NOW - 3 * 60_000, accuracy: 5 }));
  harness.send(position({ accuracy: 25 }));

  const result = await resultPromise;
  assert.equal(result.accuracy_meters, 25);
  assert.equal(result.acquisition_status, "ACCEPTABLE");
});

test("does not allow poor-quality readings to be submitted as acceptable", async () => {
  assert.equal(
    isLocationAcceptable(
      { acquisition_status: "TIMEOUT", accuracy_meters: 103 },
      100,
    ),
    false,
  );
  assert.equal(
    isLocationAcceptable(
      { acquisition_status: "ACCEPTABLE", accuracy_meters: 103 },
      100,
    ),
    false,
  );
  assert.equal(
    isLocationAcceptable(
      { acquisition_status: "ACCEPTABLE", accuracy_meters: 100 },
      100,
    ),
    true,
  );
  assert.equal(
    isLocationAcceptable(
      { acquisition_status: "ACCEPTABLE", accuracy_meters: 10 },
      null,
    ),
    false,
  );
});

test("builds the exact arrival API payload without browser-only metadata", () => {
  const payload = toLocationEventPayload("ARRIVAL", {
    capture_status: "CAPTURED",
    latitude: 28.6139,
    longitude: 77.209,
    accuracy_meters: 12.5,
    captured_at_device: "2026-10-30T12:00:00.000Z",
    coordinate_source: "Browser Geolocation API",
  });

  assert.deepEqual(payload, {
    event_type: "ARRIVAL",
    capture_status: "CAPTURED",
    latitude: 28.6139,
    longitude: 77.209,
    accuracy_meters: 12.5,
    captured_at_device: "2026-10-30T12:00:00.000Z",
  });
});
