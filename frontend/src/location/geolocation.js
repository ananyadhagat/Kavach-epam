export const DEFAULT_GPS_ACQUISITION_TIMEOUT_MS = 60_000;
export const DEFAULT_GPS_POSITION_MAX_AGE_MS = 2 * 60_000;
export const GPS_POSITION_TIMEOUT_MS = 20_000;

const GEOLOCATION_ERROR_MESSAGES = {
  1: "Location permission was denied. Allow location access for this site in your browser settings, and make sure Location is enabled in your phone settings before trying again.",
  2: "Your phone could not get a location fix. Turn on Location/GPS in phone settings, move somewhere with a clearer view of the sky, and try again. This website cannot switch GPS on for you.",
  3: "GPS acquisition timed out. Check that Location/GPS is enabled and try again outdoors or near a window for a clearer signal.",
};

export class LocationCaptureError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "LocationCaptureError";
    this.code = code;
  }
}

export function getGpsAccuracyThreshold(taskDetails) {
  const threshold = taskDetails?.gps_accuracy_threshold_meters;
  return Number.isFinite(threshold) && threshold > 0 ? threshold : null;
}

function validatePosition(position, now, maxAge) {
  const latitude = position?.coords?.latitude;
  const longitude = position?.coords?.longitude;
  const accuracy = position?.coords?.accuracy;
  const timestamp = position?.timestamp;

  if (
    !Number.isFinite(latitude) ||
    latitude < -90 ||
    latitude > 90 ||
    !Number.isFinite(longitude) ||
    longitude < -180 ||
    longitude > 180 ||
    !Number.isFinite(accuracy) ||
    accuracy <= 0 ||
    accuracy > 100_000
  ) {
    return null;
  }

  if (!Number.isFinite(timestamp)) return null;

  const capturedAt = new Date(timestamp);
  const age = now() - timestamp;
  if (
    Number.isNaN(capturedAt.getTime()) ||
    age < -5_000 ||
    age > maxAge
  ) {
    return null;
  }

  return {
    capture_status: "CAPTURED",
    latitude,
    longitude,
    accuracy_meters: accuracy,
    captured_at_device: capturedAt.toISOString(),
    coordinate_source: "Browser Geolocation API",
  };
}

export function acquireBestDeviceLocation(
  geolocation = globalThis.navigator?.geolocation,
  {
    thresholdMeters,
    onUpdate = () => {},
    now = Date.now,
    timeoutMs = DEFAULT_GPS_ACQUISITION_TIMEOUT_MS,
    positionTimeoutMs = GPS_POSITION_TIMEOUT_MS,
    maxAgeMs = DEFAULT_GPS_POSITION_MAX_AGE_MS,
    schedule = globalThis.setTimeout,
    cancel = globalThis.clearTimeout,
    signal,
  } = {},
) {
  if (!geolocation?.watchPosition) {
    return Promise.reject(
      new LocationCaptureError(
        "unsupported",
        "This browser does not support continuous device location. Use a browser with Geolocation support.",
      ),
    );
  }
  if (!Number.isFinite(thresholdMeters) || thresholdMeters <= 0) {
    return Promise.reject(
      new LocationCaptureError(
        "threshold-unavailable",
        "The server's GPS accuracy acceptance threshold is unavailable. Refresh task details before capturing location.",
      ),
    );
  }

  return new Promise((resolve, reject) => {
    let watchId = null;
    let timerId = null;
    let settled = false;
    let best = null;

    const clearWatch = (id) => {
      try {
        geolocation.clearWatch(id);
      } catch (error) {
        console.error("Could not stop the device location watcher.", error);
      }
    };

    const stop = () => {
      if (timerId !== null) {
        try {
          cancel(timerId);
        } catch (error) {
          console.error("Could not stop the GPS acquisition timer.", error);
        }
        timerId = null;
      }
      if (watchId !== null) {
        const activeWatchId = watchId;
        watchId = null;
        clearWatch(activeWatchId);
      }
    };

    const finish = (result, error) => {
      if (settled) return;
      settled = true;
      stop();
      signal?.removeEventListener("abort", onAbort);
      if (error) reject(error);
      else resolve(result);
    };

    const publishUpdate = (update) => {
      try {
        onUpdate(update);
        return true;
      } catch (error) {
        console.error("GPS acquisition update callback failed.", error);
        finish(
          null,
          new LocationCaptureError(
            "update-failed",
            "The location display could not be updated safely. Retry GPS capture.",
          ),
        );
        return false;
      }
    };

    const onAbort = () => {
      const error = new Error("GPS acquisition was cancelled.");
      error.name = "AbortError";
      finish(null, error);
    };

    const onPosition = (position) => {
      if (settled) return;
      try {
        const location = validatePosition(position, now, maxAgeMs);
        if (!location) return;
        if (best && location.accuracy_meters >= best.accuracy_meters) return;

        const hadPreviousReading = best !== null;
        best = location;
        const acceptable = location.accuracy_meters <= thresholdMeters;
        const status = acceptable
          ? "ACCEPTABLE"
          : hadPreviousReading
            ? "IMPROVING"
            : "POOR";

        if (
          !publishUpdate({
            status,
            location,
            bestAccuracyMeters: location.accuracy_meters,
            thresholdMeters,
          })
        ) {
          return;
        }

        if (acceptable) {
          finish({ ...location, acquisition_status: "ACCEPTABLE" });
        }
      } catch (error) {
        console.error("Could not process a device location reading.", error);
        finish(
          null,
          new LocationCaptureError(
            "invalid-reading",
            "The browser returned a location that could not be processed safely. Retry GPS capture.",
          ),
        );
      }
    };

    const onPositionError = (error) => {
      if (settled) return;
      const message =
        GEOLOCATION_ERROR_MESSAGES[error?.code] ??
        "The browser could not determine your location. Check phone Location/GPS settings and try again.";
      const code =
        error?.code === 1
          ? "permission-denied"
          : error?.code === 2
            ? "position-unavailable"
            : error?.code === 3
              ? "timeout"
              : "unknown";
      if (code === "permission-denied") {
        publishUpdate({
          status: "PERMISSION_DENIED",
          location: best,
          bestAccuracyMeters: best?.accuracy_meters ?? null,
          thresholdMeters,
          message,
        });
        finish(null, new LocationCaptureError(code, message));
        return;
      }

      if (code === "position-unavailable" || code === "timeout") {
        publishUpdate({
          status: code === "position-unavailable"
            ? "UNAVAILABLE"
            : "POSITION_TIMEOUT",
          location: best,
          bestAccuracyMeters: best?.accuracy_meters ?? null,
          thresholdMeters,
          message,
        });
        return;
      }

      publishUpdate({
        status: "UNAVAILABLE",
        location: best,
        bestAccuracyMeters: best?.accuracy_meters ?? null,
        thresholdMeters,
        message,
      });
      finish(null, new LocationCaptureError(code, message));
    };

    if (!publishUpdate({
      status: "ACQUIRING",
      location: null,
      bestAccuracyMeters: null,
      thresholdMeters,
    })) {
      return;
    }

    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });

    timerId = schedule(() => {
      if (best) {
        publishUpdate({
          status: "TIMEOUT",
          location: best,
          bestAccuracyMeters: best.accuracy_meters,
          thresholdMeters,
        });
        finish({ ...best, acquisition_status: "TIMEOUT" });
      } else {
        publishUpdate({
          status: "TIMEOUT",
          location: null,
          bestAccuracyMeters: null,
          thresholdMeters,
        });
        finish(
          null,
          new LocationCaptureError(
            "acquisition-timeout",
            GEOLOCATION_ERROR_MESSAGES[3],
          ),
        );
      }
    }, timeoutMs);

    try {
      watchId = geolocation.watchPosition(onPosition, onPositionError, {
        enableHighAccuracy: true,
        maximumAge: 0,
        timeout: positionTimeoutMs,
      });
      if (settled && watchId !== null) {
        clearWatch(watchId);
        watchId = null;
      }
    } catch (error) {
      finish(
        null,
        new LocationCaptureError(
          "unavailable",
          "The browser could not start GPS acquisition. Check phone Location/GPS settings and try again.",
        ),
      );
    }
  });
}

export function toLocationEventPayload(eventType, location) {
  return {
    event_type: eventType,
    capture_status: location.capture_status,
    latitude: location.latitude,
    longitude: location.longitude,
    accuracy_meters: location.accuracy_meters,
    captured_at_device: location.captured_at_device,
  };
}

export function isLocationAcceptable(location, thresholdMeters) {
  return (
    location?.acquisition_status === "ACCEPTABLE" &&
    Number.isFinite(thresholdMeters) &&
    thresholdMeters > 0 &&
    Number.isFinite(location.accuracy_meters) &&
    location.accuracy_meters > 0 &&
    location.accuracy_meters <= thresholdMeters
  );
}
