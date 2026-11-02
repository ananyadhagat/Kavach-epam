import { useEffect, useRef, useState } from "react";
import { submitTaskLocation } from "../api/tasks.js";
import {
  acquireBestDeviceLocation,
  getGpsAccuracyThreshold,
  isLocationAcceptable,
} from "../location/geolocation.js";
import {
  isCompletionLocationCaptureNeeded,
  getAcceptedCompletionLocation,
} from "../location/completion-location.js";
import Button from "./Button.jsx";
import ErrorMessage from "./ErrorMessage.jsx";
import InteractiveMap from "./InteractiveMap.jsx";
import LoadingState from "./LoadingState.jsx";

const LOCATION_ACTIONS = {
  ARRIVAL: {
    label: "Arrival location",
    taskField: "arrival_location_event_id",
    allowedStatuses: new Set(["ACCEPTED", "IN_PROGRESS", "PAUSED"]),
  },
  COMPLETION: {
    label: "Completion location",
    taskField: "completion_location_event_id",
    allowedStatuses: new Set(["IN_PROGRESS", "PAUSED"]),
  },
};

function errorTitle(error) {
  if (error.status === 401) return "Authentication required";
  if (error.status === 403) return "Location access forbidden";
  if (error.status === 404) return "Task not found";
  if (error.status === 409) return "Location conflicts with task state";
  if (error.status === 422) return "Location could not be accepted";
  if (error.status === 503) return "Location service unavailable";
  return "Could not submit location";
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function distanceMeters(first, second) {
  const radians = (degrees) => (degrees * Math.PI) / 180;
  const latitudeDelta = radians(second.latitude - first.latitude);
  const longitudeDelta = radians(second.longitude - first.longitude);
  const firstLatitude = radians(first.latitude);
  const secondLatitude = radians(second.latitude);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(firstLatitude) *
      Math.cos(secondLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;

  const clampedHaversine = Math.min(1, Math.max(0, haversine));
  return (
    6_371_000 *
    2 *
    Math.atan2(
      Math.sqrt(clampedHaversine),
      Math.sqrt(1 - clampedHaversine),
    )
  );
}

function hasCoordinates(location) {
  return (
    Number.isFinite(location?.latitude) &&
    location.latitude >= -90 &&
    location.latitude <= 90 &&
    Number.isFinite(location?.longitude) &&
    location.longitude >= -180 &&
    location.longitude <= 180
  );
}

function formatAccuracy(value) {
  return Number.isFinite(value) && value > 0
    ? value.toFixed(1)
    : null;
}

export default function LocationSection({
  actionsDisabled = false,
  task,
  taskLocation,
  workerLocation,
  onLocationCaptured,
  onLocationSubmitted,
  onRefreshTask,
}) {
  const [capture, setCapture] = useState(null);
  const [captureError, setCaptureError] = useState(null);
  const [gpsAcquisition, setGpsAcquisition] = useState(null);
  const [capturingType, setCapturingType] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [submittingType, setSubmittingType] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [syncError, setSyncError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const activeTaskIdRef = useRef(task.task_id);
  const captureSequenceRef = useRef(0);
  const acquisitionControllerRef = useRef(null);
  const requestControllerRef = useRef(null);
  const refreshControllerRef = useRef(null);
  const pendingRef = useRef(false);
  const gpsAccuracyThresholdMeters = getGpsAccuracyThreshold(task);

  useEffect(() => {
    activeTaskIdRef.current = task.task_id;
    captureSequenceRef.current += 1;
    setCapture(null);
    setCaptureError(null);
    setGpsAcquisition(null);
    onLocationCaptured?.(null);
    setCapturingType(null);
    setConfirmed(false);
    setSubmittingType(null);
    setFeedback(null);
    setSyncError(null);
    setIsRefreshing(false);
    pendingRef.current = false;

    return () => {
      activeTaskIdRef.current = null;
      captureSequenceRef.current += 1;
      acquisitionControllerRef.current?.abort();
      requestControllerRef.current?.abort();
      refreshControllerRef.current?.abort();
    };
  }, [task.task_id]);

  function captureCurrentLocation(eventType) {
    setCaptureError(null);
    setFeedback(null);
    setCapture(null);
    setConfirmed(false);
    onLocationCaptured?.(null);

    if (gpsAccuracyThresholdMeters === null) {
      setCapturingType(null);
      setGpsAcquisition({ eventType, status: "THRESHOLD_UNAVAILABLE" });
      return;
    }

    setGpsAcquisition({ eventType, status: "ACQUIRING" });

    if (globalThis.isSecureContext === false) {
      setGpsAcquisition({ eventType, status: "UNAVAILABLE" });
      setCaptureError({
        eventType,
        message:
          "Location access requires a secure browser context (HTTPS or localhost).",
      });
      return;
    }

    setCapturingType(eventType);
    const sequence = captureSequenceRef.current + 1;
    captureSequenceRef.current = sequence;
    acquisitionControllerRef.current?.abort();
    const controller = new AbortController();
    acquisitionControllerRef.current = controller;
    acquireBestDeviceLocation(globalThis.navigator?.geolocation, {
      thresholdMeters: gpsAccuracyThresholdMeters,
      signal: controller.signal,
      onUpdate: (update) => {
        if (
          captureSequenceRef.current !== sequence ||
          activeTaskIdRef.current !== task.task_id
        ) {
          return;
        }

        setGpsAcquisition({ eventType, ...update });
        if (hasCoordinates(update.location)) {
          const locationForTask = {
            ...update.location,
            event_type: eventType,
            acquisition_status: update.status,
          };
          setCapture(locationForTask);
          onLocationCaptured?.(locationForTask);
        }
      },
    })
      .then((capturedLocation) => {
        if (
          captureSequenceRef.current !== sequence ||
          activeTaskIdRef.current !== task.task_id
        ) {
          return;
        }

        setCapturingType(null);
        const locationForTask = {
          ...capturedLocation,
          event_type: eventType,
        };
        setCapture(locationForTask);
        setGpsAcquisition({
          eventType,
          status: capturedLocation.acquisition_status,
          location: capturedLocation,
          bestAccuracyMeters: capturedLocation.accuracy_meters,
          thresholdMeters: gpsAccuracyThresholdMeters,
        });
        onLocationCaptured?.(locationForTask);
      })
      .catch((error) => {
        if (
          captureSequenceRef.current === sequence &&
          activeTaskIdRef.current === task.task_id
        ) {
          setCapturingType(null);
          if (error?.name === "AbortError") return;
          setGpsAcquisition((current) =>
            current?.eventType === eventType
              ? {
                  ...current,
                  status:
                    error?.code === "permission-denied"
                      ? "PERMISSION_DENIED"
                      : error?.code === "position-unavailable" ||
                          error?.code === "unsupported"
                        ? "UNAVAILABLE"
                        : "TIMEOUT",
                }
              : current,
          );
          setCaptureError({
            eventType,
            message:
              error?.message ??
              "GPS capture failed unexpectedly. Check Location/GPS settings and retry.",
          });
        }
      });
  }

  async function refreshBackendState() {
    refreshControllerRef.current?.abort();
    const controller = new AbortController();
    refreshControllerRef.current = controller;
    setIsRefreshing(true);

    try {
      const refreshedTask = await onRefreshTask({ signal: controller.signal });
      if (
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return false;
      }

      setSyncError(null);
      return refreshedTask;
    } catch (error) {
      if (error.name !== "AbortError" && !controller.signal.aborted) {
        setSyncError(error);
      }
      return false;
    } finally {
      if (refreshControllerRef.current === controller) {
        refreshControllerRef.current = null;
        setIsRefreshing(false);
      }
    }
  }

  async function submitLocation(event, eventType) {
    event.preventDefault();
    if (
      !capture ||
      capture.event_type !== eventType ||
      !confirmed ||
      pendingRef.current ||
      actionsDisabled ||
      syncError ||
      !LOCATION_ACTIONS[eventType].allowedStatuses.has(task.status)
    ) {
      return;
    }

    pendingRef.current = true;
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setSubmittingType(eventType);
    setFeedback(null);
    setSyncError(null);

    try {
      const locationEvent = await submitTaskLocation(
        task.task_id,
        eventType,
        capture,
        { signal: controller.signal },
      );
      if (
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return;
      }

      setFeedback({ eventType, locationEvent });
      onLocationSubmitted?.(locationEvent);
      setCapture(null);
      setConfirmed(false);

      const refreshedTask = await refreshBackendState();
      if (!refreshedTask) {
        setFeedback((current) =>
          current?.eventType === eventType
            ? {
                ...current,
                message:
                  "Refresh task details before submitting another location.",
              }
            : current,
        );
      }
    } catch (error) {
      if (
        error.name === "AbortError" ||
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return;
      }

      setFeedback({ eventType, error });
      const refreshedTask = await refreshBackendState();
      if (refreshedTask) {
        setFeedback((current) =>
          current?.eventType === eventType
            ? {
                ...current,
                message:
                  "Task details were refreshed before another submission can be made. If the event was recorded, its task reference is shown below.",
              }
            : current,
        );
      }
    } finally {
      if (activeTaskIdRef.current === task.task_id) {
        pendingRef.current = false;
        setSubmittingType(null);
      }
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
    }
  }

  function retryRefresh() {
    refreshBackendState();
  }

  const enabledActions = Object.entries(LOCATION_ACTIONS).filter(
    ([, action]) => action.allowedStatuses.has(task.status),
  );
  const captureIsAcceptable = isLocationAcceptable(
    capture,
    gpsAccuracyThresholdMeters,
  );

  return (
    <section className="location-panel" aria-labelledby="location-heading">
      <div className="location-panel__heading">
        <div>
          <p className="eyebrow">Separate from task photos</p>
          <h2 id="location-heading">Location capture</h2>
        </div>
      </div>

      <p className="location-guidance">
        Your browser will request permission only after you choose to capture.
        Location and its reported accuracy come from your device; GPS is not
        exact. The device is monitored for up to 60 seconds so accuracy can
        improve; readings above the server's acceptance threshold cannot be
        submitted. Review the best result and confirm before sending it.
        {gpsAccuracyThresholdMeters === null
          ? "GPS capture is unavailable because task details did not provide a valid gps_accuracy_threshold_meters value. The backend must expose the configured MAX_GPS_ACCURACY_METERS value. Refresh task details; if it is still missing, restart or update the Field Worker API. No GPS reading will be requested until the server threshold is available."
          : `The backend acceptance threshold is ${gpsAccuracyThresholdMeters} m. `}
        Location requires HTTPS when deployed; localhost is allowed for local
        development. If GPS is off, enable Location in your phone settings.
      </p>

      {enabledActions.length === 0 && (
        <p className="location-guidance">
          Location actions are unavailable while this task is {task.status}.
        </p>
      )}

      {enabledActions.length === 0 && feedback?.error && (
        <ErrorMessage title={errorTitle(feedback.error)}>
          {feedback.error.message}
        </ErrorMessage>
      )}

      {enabledActions.length === 0 && feedback?.message && (
        <p className="location-success" role="status">
          {feedback.message}
        </p>
      )}

      {isRefreshing && (
        <LoadingState label="Refreshing task location references..." />
      )}

      {syncError && (
        <div className="location-sync-error">
          <ErrorMessage title="Could not confirm the latest task state">
            {syncError.message} Refresh task details before submitting another
            location.
          </ErrorMessage>
          <Button
            disabled={isRefreshing}
            onClick={retryRefresh}
            type="button"
            variant="secondary"
          >
            Refresh task details
          </Button>
        </div>
      )}

      <section
        aria-labelledby="arrival-map-heading"
        className="location-map-section"
      >
        <h3 id="arrival-map-heading">Arrival location map</h3>
        <InteractiveMap
          taskLocation={taskLocation}
          workerLocation={workerLocation}
        />
      </section>

      {enabledActions.map(([eventType, action]) => {
        const actionFeedback =
          feedback?.eventType === eventType ? feedback : null;
        const existingEventId = task[action.taskField];
        const latestLocation =
          eventType === "ARRIVAL"
            ? task.latest_arrival_location
            : task.latest_completion_location;
        const locationAccepted =
          eventType === "COMPLETION"
            ? !isCompletionLocationCaptureNeeded(task)
            : task.arrival_location_accepted === true;
        const acceptedCompletionLocation =
          eventType === "COMPLETION"
            ? getAcceptedCompletionLocation(task)
            : null;
        return (
        <section
          aria-labelledby={`location-${eventType.toLowerCase()}-heading`}
          className="location-action"
          key={eventType}
        >
          <div className="location-action__heading">
            <h3 id={`location-${eventType.toLowerCase()}-heading`}>
              {action.label}
            </h3>
            {locationAccepted === true ? (
              <span className="location-recorded" role="status">
                An acceptable location is saved for task progression.
              </span>
            ) : locationAccepted === false && existingEventId ? (
              <span className="location-not-recorded" role="status">
                A location event is referenced, but it is not confirmed as
                acceptable for task progression.
              </span>
            ) : locationAccepted === false ? (
              <span className="location-not-recorded">
                No {eventType === "ARRIVAL" ? "arrival" : "completion"} location
                has been saved yet.
              </span>
            ) : (
              <span className="location-not-recorded" role="alert">
                The task-details API did not include this location's acceptance
                status. Refresh task details or update the backend before
                relying on this location for task progression.
              </span>
            )}
          </div>

          <p className="location-guidance">
            {eventType === "ARRIVAL"
              ? "Capture and save your arrival before starting an accepted task."
              : "Capture and save a separate completion location after work is underway. It is not reused from arrival."}
          </p>

          {eventType === "COMPLETION" && (
            <section
              aria-labelledby="completion-map-heading"
              className="location-map-section"
            >
              <h4 id="completion-map-heading">Completion location map</h4>
              {acceptedCompletionLocation ? (
                <InteractiveMap
                  locationKind="completion"
                  locationLabel="Accepted completion location"
                  taskLocation={taskLocation}
                  workerLocation={acceptedCompletionLocation}
                />
              ) : (
                <p className="interactive-map__empty" role="status">
                  No accepted completion location with valid backend coordinates
                  is available to map.
                </p>
              )}
            </section>
          )}

          <Button
            disabled={
              gpsAccuracyThresholdMeters === null ||
              locationAccepted ||
              Boolean(submittingType) ||
              capturingType !== null ||
              actionsDisabled ||
              isRefreshing ||
              Boolean(syncError)
            }
            onClick={() => captureCurrentLocation(eventType)}
            type="button"
            variant="secondary"
          >
            Capture My Current Location
          </Button>
          {gpsAccuracyThresholdMeters === null && (
            <Button
              disabled={isRefreshing}
              onClick={retryRefresh}
              type="button"
              variant="secondary"
            >
              Refresh task details
            </Button>
          )}

          {capturingType === eventType && (
            <LoadingState
              label={
                  gpsAcquisition?.status === "IMPROVING" &&
                  formatAccuracy(gpsAcquisition.bestAccuracyMeters)
                    ? `Improving accuracy; best reading ±${formatAccuracy(gpsAcquisition.bestAccuracyMeters)} m`
                    : gpsAcquisition?.status === "POOR" &&
                        formatAccuracy(gpsAcquisition.bestAccuracyMeters)
                      ? `Poor accuracy; continuing GPS acquisition (best ±${formatAccuracy(gpsAcquisition.bestAccuracyMeters)} m)`
                      : "Acquiring GPS signal..."
                }
              />
          )}

          {gpsAcquisition?.eventType === eventType && (
            <p
              className={`location-quality location-quality--${gpsAcquisition.status.toLowerCase()}`}
              role="status"
            >
              {gpsAcquisition.status === "ACQUIRING" &&
                "Acquiring GPS signal. Keep this page open while your phone searches for a fix."}
              {gpsAcquisition.status === "POOR" &&
                (formatAccuracy(gpsAcquisition.bestAccuracyMeters)
                  ? `Poor GPS accuracy: ±${formatAccuracy(gpsAcquisition.bestAccuracyMeters)} m. Continuing to watch for a better reading; acceptable threshold: ${gpsAcquisition.thresholdMeters} m.`
                  : "GPS has not returned a valid position yet. Continuing to acquire a fix.")}
              {gpsAcquisition.status === "IMPROVING" &&
                (formatAccuracy(gpsAcquisition.bestAccuracyMeters)
                  ? `Improving accuracy. Best reading so far: ±${formatAccuracy(gpsAcquisition.bestAccuracyMeters)} m; acceptable threshold: ${gpsAcquisition.thresholdMeters} m.`
                  : "GPS accuracy is improving; waiting for a valid position.")}
              {gpsAcquisition.status === "ACCEPTABLE" &&
                (formatAccuracy(gpsAcquisition.bestAccuracyMeters)
                  ? `Acceptable accuracy: ±${formatAccuracy(gpsAcquisition.bestAccuracyMeters)} m (server threshold ${gpsAcquisition.thresholdMeters} m).`
                  : "GPS reported an invalid accuracy value. Capture again.")}
              {gpsAcquisition.status === "TIMEOUT" &&
                (formatAccuracy(gpsAcquisition.bestAccuracyMeters)
                  ? `GPS acquisition timed out without an acceptable fix. Best accuracy was ±${formatAccuracy(gpsAcquisition.bestAccuracyMeters)} m; the server requires ${gpsAcquisition.thresholdMeters} m or better. Arrival location has not been accepted. Enable phone Location/GPS and retry outdoors or near a window.`
                  : "GPS acquisition timed out before a valid position was received. Arrival location has not been accepted. Enable phone Location/GPS and retry outdoors or near a window.")}
              {gpsAcquisition.status === "PERMISSION_DENIED" &&
                "Location permission denied. Allow location for this site in browser settings and enable Location in phone settings, then retry."}
              {gpsAcquisition.status === "UNAVAILABLE" &&
                `${gpsAcquisition.message ?? "Device location is temporarily unavailable."} Still waiting for a fix; enable Location/GPS in phone settings and retry outdoors or near a window.`}
              {gpsAcquisition.status === "POSITION_TIMEOUT" &&
                `${gpsAcquisition.message ?? "No new GPS fix was received yet."} Acquisition will continue until the overall time limit.`}
              {gpsAcquisition.status === "THRESHOLD_UNAVAILABLE" &&
                "GPS was not started because the server's acceptance threshold is missing or invalid. Refresh task details and contact support if it remains unavailable."}
            </p>
          )}

          {latestLocation && (
            <div className="location-history-summary">
              <strong>Latest {eventType.toLowerCase()} location event</strong>
              <span>
                {latestLocation.accepted_for_progress
                  ? "Accepted for task progression"
                  : `Recorded, not accepted (${latestLocation.capture_status})`}
              </span>
              {formatAccuracy(latestLocation.accuracy_meters) && (
                <span>
                  Reported accuracy: ±
                  {formatAccuracy(latestLocation.accuracy_meters)} m
                </span>
              )}
              <span>
                Device capture:{" "}
                {latestLocation.captured_at_device
                  ? formatDate(latestLocation.captured_at_device)
                  : "not provided"}
              </span>
              <span>
                Server received: {formatDate(latestLocation.received_at_server)}
              </span>
              {latestLocation.rejection_reason && (
                <span>{latestLocation.rejection_reason}</span>
              )}
            </div>
          )}

          {captureError?.eventType === eventType && (
            <p className="location-inline-error" role="alert">
              {captureError.message}
            </p>
          )}

          {capture?.event_type === eventType &&
            hasCoordinates(capture) &&
            formatAccuracy(capture.accuracy_meters) && (
            <form
              className="location-confirmation"
              onSubmit={(event) => submitLocation(event, eventType)}
            >
              <dl className="location-coordinates">
                <div>
                  <dt>Latitude</dt>
                  <dd>{capture.latitude.toFixed(6)}</dd>
                </div>
                <div>
                  <dt>Longitude</dt>
                  <dd>{capture.longitude.toFixed(6)}</dd>
                </div>
                <div>
                  <dt>Distance from assigned task location</dt>
                  <dd>
                    {hasCoordinates(task.location)
                      ? `${Math.round(
                          distanceMeters(task.location, capture),
                        ).toLocaleString()} m`
                      : "Unavailable: assigned coordinates are invalid."}
                  </dd>
                </div>
                <div>
                  <dt>Reported accuracy</dt>
                  <dd>
                    ±
                    {capture.accuracy_meters.toLocaleString(undefined, {
                      maximumFractionDigits: 1,
                    })}{" "}
                    m
                  </dd>
                </div>
                <div>
                  <dt>Captured at (device)</dt>
                  <dd>
                    <time dateTime={capture.captured_at_device}>
                      {formatDate(capture.captured_at_device)}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt>Coordinate source</dt>
                  <dd>{capture.coordinate_source}</dd>
                </div>
              </dl>
              <p className="location-accuracy-note">
                GPS status:{" "}
                {capture.acquisition_status === "ACCEPTABLE"
                  ? `acceptable under the server threshold of ${gpsAccuracyThresholdMeters} m`
                  : `poor; best reading remains above the server threshold of ${gpsAccuracyThresholdMeters} m`}
                .{" "}
                {hasCoordinates(task.location)
                  ? "Distance is informational; it is not an acceptance rule."
                  : "Distance cannot be calculated because assigned task coordinates are invalid."}{" "}
                The backend remains the final authority when saving.
                GPS proximity is not proof of identity or physical presence.
              </p>
              <label className="location-confirmation__check">
                <input
                  checked={confirmed}
                  disabled={
                    !captureIsAcceptable ||
                    Boolean(submittingType) ||
                    capturingType !== null ||
                    actionsDisabled ||
                    isRefreshing
                  }
                  onChange={(event) => setConfirmed(event.target.checked)}
                  type="checkbox"
                />
                I reviewed this reading and confirm sending it as{" "}
                {action.label.toLowerCase()}.
              </label>
              <div className="location-confirmation__actions">
                <Button
                  disabled={
                    !confirmed ||
                    !captureIsAcceptable ||
                    Boolean(submittingType) ||
                    capturingType !== null ||
                    actionsDisabled ||
                    isRefreshing ||
                    Boolean(syncError)
                  }
                  type="submit"
                >
                  {submittingType === eventType
                    ? "Submitting..."
                    : eventType === "ARRIVAL"
                      ? "Confirm & Save Arrival Location"
                      : "Confirm & Save Completion Location"}
                </Button>
                <Button
                  disabled={
                    Boolean(submittingType) ||
                    capturingType !== null ||
                    actionsDisabled ||
                    isRefreshing
                  }
                  onClick={() => captureCurrentLocation(eventType)}
                  type="button"
                  variant="secondary"
                >
                  Capture again
                </Button>
              </div>
            </form>
          )}

          {actionFeedback?.error && (
            <ErrorMessage title={errorTitle(actionFeedback.error)}>
              {actionFeedback.error.message}
            </ErrorMessage>
          )}

          {actionFeedback?.locationEvent && (
            <div
              className={
                actionFeedback.locationEvent.capture_status === "CAPTURED"
                  ? "location-success"
                  : "location-recorded-warning"
              }
              role="status"
            >
              <p>
                Backend assessment:{" "}
                {actionFeedback.locationEvent.capture_status === "CAPTURED"
                  ? "the location was accepted as CAPTURED under the backend's configured accuracy rule."
                  : actionFeedback.locationEvent.capture_status ===
                      "INACCURATE"
                    ? "the event was recorded, but the reported accuracy did not meet the backend's configured threshold. It is not a usable arrival/completion location. Capture again with Location/GPS enabled and a clearer signal."
                    : "the location was not captured."}
              </p>
              <p>
                This result does not prove identity or physical presence.
              </p>
              <dl className="location-coordinates">
                <div>
                  <dt>Event ID</dt>
                  <dd>{actionFeedback.locationEvent.location_event_id}</dd>
                </div>
                <div>
                  <dt>Device captured</dt>
                  <dd>
                    {actionFeedback.locationEvent.captured_at_device
                      ? formatDate(
                          actionFeedback.locationEvent.captured_at_device,
                        )
                      : "Not provided"}
                  </dd>
                </div>
                <div>
                  <dt>Server received</dt>
                  <dd>
                    <time
                      dateTime={actionFeedback.locationEvent.received_at_server}
                    >
                      {formatDate(
                        actionFeedback.locationEvent.received_at_server,
                      )}
                    </time>
                  </dd>
                </div>
                {actionFeedback.locationEvent.latitude !== null &&
                  actionFeedback.locationEvent.longitude !== null && (
                    <div>
                      <dt>Backend coordinates</dt>
                      <dd>
                        {actionFeedback.locationEvent.latitude.toFixed(6)},{" "}
                        {actionFeedback.locationEvent.longitude.toFixed(6)}
                      </dd>
                    </div>
                  )}
                {actionFeedback.locationEvent.accuracy_meters !== null && (
                  <div>
                    <dt>Backend-reported accuracy</dt>
                    <dd>
                      ±
                      {actionFeedback.locationEvent.accuracy_meters.toLocaleString(
                        undefined,
                        { maximumFractionDigits: 1 },
                      )}{" "}
                      m
                    </dd>
                  </div>
                )}
              </dl>
              {actionFeedback.message && <p>{actionFeedback.message}</p>}
            </div>
          )}

        </section>
        );
      })}
    </section>
  );
}
