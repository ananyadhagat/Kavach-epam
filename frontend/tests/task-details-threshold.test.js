import assert from "node:assert/strict";
import test from "node:test";
import { getGpsAccuracyThreshold } from "../src/location/geolocation.js";

const taskDetails = {
  task_id: "TASK-THRESHOLD-TEST",
  title: "Threshold contract test",
  description: "API response mapping test",
  status: "ACCEPTED",
  priority: "MEDIUM",
  location: {
    address: "Test location",
    latitude: 28.6139,
    longitude: 77.209,
  },
  gps_accuracy_threshold_meters: 100,
  arrival_location_accepted: false,
  completion_location_accepted: false,
  accepted_arrival_location: null,
  latest_arrival_location: null,
  latest_completion_location: null,
};

test("reads the authoritative GPS threshold from task details", () => {
  const parsedTaskDetails = JSON.parse(JSON.stringify(taskDetails));
  assert.equal(getGpsAccuracyThreshold(parsedTaskDetails), 100);
});

test("does not substitute a fallback when the details response omits threshold", () => {
  const { gps_accuracy_threshold_meters: _threshold, ...missingThreshold } =
    taskDetails;
  const parsedTaskDetails = JSON.parse(JSON.stringify(missingThreshold));
  assert.equal(getGpsAccuracyThreshold(parsedTaskDetails), null);
});

test("rejects null, non-numeric and non-positive GPS thresholds", () => {
  assert.equal(getGpsAccuracyThreshold({ gps_accuracy_threshold_meters: null }), null);
  assert.equal(
    getGpsAccuracyThreshold({ gps_accuracy_threshold_meters: "100" }),
    null,
  );
  assert.equal(getGpsAccuracyThreshold({ gps_accuracy_threshold_meters: 0 }), null);
  assert.equal(
    getGpsAccuracyThreshold({ gps_accuracy_threshold_meters: Number.NaN }),
    null,
  );
});
