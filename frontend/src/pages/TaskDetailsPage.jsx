import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getTaskDetails, transitionTask } from "../api/tasks.js";
import Button from "../components/Button.jsx";
import BlockerSection from "../components/BlockerSection.jsx";
import CompletionSection from "../components/CompletionSection.jsx";
import EvidenceSection from "../components/EvidenceSection.jsx";
import ErrorMessage from "../components/ErrorMessage.jsx";
import LoadingState from "../components/LoadingState.jsx";
import LocationErrorBoundary from "../components/LocationErrorBoundary.jsx";
import LocationSection from "../components/LocationSection.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { getWorkerLocationForMap } from "../location/worker-location.js";

function getErrorTitle(error, fallbackTitle = "Could not load task") {
  if (error.status === 401) {
    return "Authentication required";
  }

  if (error.status === 403) {
    return "Access forbidden";
  }

  if (error.status === 404) {
    return "Task not found";
  }

  if (error.status === 409) {
    return "Task state conflict";
  }

  if (error.status === 503) {
    return "Task service unavailable";
  }

  return fallbackTitle;
}

function getPriorityClass(priority) {
  return `priority priority--${priority.toLowerCase()}`;
}

function hasTaskCoordinates(location) {
  return (
    Number.isFinite(location?.latitude) &&
    location.latitude >= -90 &&
    location.latitude <= 90 &&
    Number.isFinite(location?.longitude) &&
    location.longitude >= -180 &&
    location.longitude <= 180
  );
}

function createSupersededRefreshError() {
  const error = new Error("This task refresh was superseded.");
  error.name = "AbortError";
  return error;
}

export default function TaskDetailsPage() {
  const { taskId } = useParams();
  const [result, setResult] = useState({
    taskId: null,
    task: null,
    error: null,
    isLoading: true,
  });
  const [requestNumber, setRequestNumber] = useState(0);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [syncError, setSyncError] = useState(null);
  const [completionLocationEvent, setCompletionLocationEvent] = useState(null);
  const [workerLocation, setWorkerLocation] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
  const [relatedRefreshNumber, setRelatedRefreshNumber] = useState(0);
  const [prerequisiteRevision, setPrerequisiteRevision] = useState(0);
  const actionControllerRef = useRef(null);
  const actionPendingRef = useRef(false);
  const rejectDialogRef = useRef(null);
  const refreshSequenceRef = useRef(0);
  const currentTaskIdRef = useRef(taskId);
  currentTaskIdRef.current = taskId;
  const currentResult =
    result.taskId === taskId
      ? result
      : { task: null, error: null, isLoading: true };
  const taskLocation = useMemo(
    () =>
      currentResult.task
        ? {
            latitude: currentResult.task.location.latitude,
            longitude: currentResult.task.location.longitude,
            label:
              currentResult.task.location.name ??
              currentResult.task.location.address,
          }
        : null,
    [currentResult.task?.location],
  );
  const displayedWorkerLocation =
    currentResult.task
      ? getWorkerLocationForMap(currentResult.task, workerLocation)
      : workerLocation;

  const refreshTaskDetails = useCallback(
    async ({ signal } = {}) => {
      const requestId = refreshSequenceRef.current + 1;
      refreshSequenceRef.current = requestId;

      try {
        const refreshedTask = await getTaskDetails(taskId, { signal });
        if (
          currentTaskIdRef.current !== taskId ||
          refreshSequenceRef.current !== requestId ||
          signal?.aborted
        ) {
          throw createSupersededRefreshError();
        }

        setResult({
          taskId,
          task: refreshedTask,
          error: null,
          isLoading: false,
        });
        setSyncError(null);
        return refreshedTask;
      } catch (error) {
        if (
          error.name !== "AbortError" &&
          !signal?.aborted &&
          currentTaskIdRef.current === taskId &&
          refreshSequenceRef.current === requestId
        ) {
          setSyncError(error);
        }
        throw error;
      }
    },
    [taskId],
  );

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const requestId = refreshSequenceRef.current + 1;
    refreshSequenceRef.current = requestId;

    actionControllerRef.current?.abort();
    actionControllerRef.current = null;
    setActionPending(false);
    setActionError(null);
    setSyncError(null);
    setCompletionLocationEvent(null);
    setWorkerLocation(null);
    actionPendingRef.current = false;
    if (rejectDialogRef.current?.open) {
      rejectDialogRef.current.close();
    }
    setRejectReason("");
    setRejectDialogOpen(false);
    setResult({ taskId, task: null, error: null, isLoading: true });

    getTaskDetails(taskId, { signal: controller.signal })
      .then((loadedTask) => {
        if (
          active &&
          currentTaskIdRef.current === taskId &&
          refreshSequenceRef.current === requestId
        ) {
          setResult({
            taskId,
            task: loadedTask,
            error: null,
            isLoading: false,
          });
        }
      })
      .catch((requestError) => {
        if (
          active &&
          requestError.name !== "AbortError" &&
          !controller.signal.aborted &&
          currentTaskIdRef.current === taskId &&
          refreshSequenceRef.current === requestId
        ) {
          setResult({
            taskId,
            task: null,
            error: requestError,
            isLoading: false,
          });
        }
      });

    return () => {
      active = false;
      controller.abort();
      actionControllerRef.current?.abort();
      if (refreshSequenceRef.current === requestId) {
        refreshSequenceRef.current += 1;
      }
    };
  }, [taskId, requestNumber]);

  useEffect(() => {
    const dialog = rejectDialogRef.current;
    if (rejectDialogOpen && dialog && !dialog.open) {
      dialog.showModal();
    }
  }, [rejectDialogOpen]);

  function retry() {
    setActionError(null);
    setSyncError(null);
    setResult({ taskId, task: null, error: null, isLoading: true });
    setRequestNumber((current) => current + 1);
  }

  function closeRejectDialog() {
    if (rejectDialogRef.current?.open) {
      rejectDialogRef.current.close();
    }
    setRejectDialogOpen(false);
    setRejectReason("");
  }

  function openRejectDialog() {
    setActionError(null);
    setRejectReason("");
    setRejectDialogOpen(true);
  }

  async function runAction(action, body) {
    const task = currentResult.task;
    if (
      actionPendingRef.current ||
      !task ||
      syncError ||
      (["accept", "reject"].includes(action) && task.status !== "ASSIGNED") ||
      (action === "reject" &&
        (typeof body?.reason !== "string" || !body.reason.trim()))
    ) {
      return;
    }

    actionPendingRef.current = true;
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setActionPending(true);
    setActionError(null);
    setSyncError(null);

    try {
      const actionResponse = await transitionTask(taskId, action, {
        body,
        signal: controller.signal,
      });

      if (currentTaskIdRef.current !== taskId || controller.signal.aborted) {
        return;
      }

      refreshSequenceRef.current += 1;
      setResult({
        taskId,
        task: actionResponse.task,
        error: null,
        isLoading: false,
      });
      if (action === "reject") {
        closeRejectDialog();
      }

      try {
        await refreshTaskDetails({ signal: controller.signal });
      } catch (refreshError) {
        if (refreshError.name === "AbortError") return;
      }
    } catch (requestError) {
      if (
        currentTaskIdRef.current !== taskId ||
        requestError.name === "AbortError"
      ) {
        return;
      }

      setActionError(requestError);

      try {
        await refreshTaskDetails({ signal: controller.signal });
      } catch (refreshError) {
        if (refreshError.name === "AbortError") return;
      }
    } finally {
      if (currentTaskIdRef.current === taskId) {
        setActionPending(false);
      }

      if (actionControllerRef.current === controller) {
        actionPendingRef.current = false;
        actionControllerRef.current = null;
      }
    }
  }

  return (
    <section className="page-section" aria-labelledby="task-details-heading">
      <Link className="back-link" to="/tasks">
        <span aria-hidden="true">←</span> Back to my tasks
      </Link>
      {currentResult.isLoading && (
        <LoadingState label="Loading task details..." />
      )}

      {currentResult.error && (
        <div className="task-details-error">
          <ErrorMessage title={getErrorTitle(currentResult.error)}>
            {currentResult.error.message}
          </ErrorMessage>
          <Button onClick={retry} type="button">
            Try again
          </Button>
        </div>
      )}

      {actionError && !rejectDialogOpen && (
        <div className="task-details-action-error">
          <ErrorMessage
            title={getErrorTitle(actionError, "Action could not be completed")}
          >
            {actionError.message}
          </ErrorMessage>
        </div>
      )}

      {syncError && (
        <div className="task-details-sync-error">
          <ErrorMessage title="Could not confirm the latest task state">
            {syncError.message} Refresh task details before trying another
            action.
          </ErrorMessage>
          <Button
            disabled={actionPending}
            onClick={retry}
            type="button"
            variant="secondary"
          >
            Refresh task
          </Button>
        </div>
      )}

      {currentResult.task && (
        <>
          <div className="page-heading task-details-heading">
            <div>
              <p className="eyebrow">Task details</p>
              <h1 id="task-details-heading">{currentResult.task.title}</h1>
              <p className="task-details-id">
                Task ID: {currentResult.task.task_id}
              </p>
            </div>
            <StatusBadge status={currentResult.task.status} />
          </div>

          {currentResult.task.status === "ASSIGNED" && (
            <section
              aria-label="Task decision"
              className="lifecycle-controls lifecycle-controls--decision"
            >
              <h2>Review assignment</h2>
              <p>
                Accept to begin documenting this task, or reject it with a
                reason. Your decision is recorded and cannot be changed here.
              </p>
              <div className="task-decision-actions">
                <Button
                  disabled={actionPending || Boolean(syncError)}
                  onClick={() => runAction("accept")}
                  type="button"
                >
                  {actionPending ? "Accepting..." : "Accept Task"}
                </Button>
                <Button
                  disabled={actionPending || Boolean(syncError)}
                  onClick={openRejectDialog}
                  type="button"
                  variant="secondary"
                >
                  Reject Task
                </Button>
              </div>
              <dialog
                aria-describedby={`rejection-dialog-description-${taskId}`}
                aria-labelledby={`rejection-dialog-title-${taskId}`}
                className="task-rejection-dialog"
                onCancel={(event) => {
                  event.preventDefault();
                  if (!actionPending) {
                    closeRejectDialog();
                  }
                }}
                ref={rejectDialogRef}
              >
                <h2 id={`rejection-dialog-title-${taskId}`}>
                  Reject assigned task?
                </h2>
                <p id={`rejection-dialog-description-${taskId}`}>
                  Enter a reason to record your decision. This task will not be
                  silently removed or reassigned.
                </p>
                {actionError && (
                  <ErrorMessage
                    title={getErrorTitle(
                      actionError,
                      "Rejection could not be recorded",
                    )}
                  >
                    {actionError.message}
                  </ErrorMessage>
                )}
                {syncError && (
                  <ErrorMessage title="Could not confirm the latest task state">
                    {syncError.message} Refresh task details before trying
                    again.
                  </ErrorMessage>
                )}
                <form
                  className="task-rejection-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const reason = rejectReason.trim();
                    if (reason) {
                      runAction("reject", { reason });
                    }
                  }}
                >
                  <label htmlFor={`rejection-reason-${taskId}`}>
                    Rejection reason
                  </label>
                  <textarea
                    autoFocus
                    disabled={actionPending || Boolean(syncError)}
                    id={`rejection-reason-${taskId}`}
                    maxLength={500}
                    onChange={(event) => setRejectReason(event.target.value)}
                    required
                    rows={4}
                    value={rejectReason}
                  />
                  <span className="task-rejection-form__count">
                    {rejectReason.length}/500
                  </span>
                  <div className="task-rejection-dialog__actions">
                    <Button
                      disabled={actionPending}
                      onClick={closeRejectDialog}
                      type="button"
                      variant="secondary"
                    >
                      Cancel
                    </Button>
                    <Button
                      disabled={
                        actionPending ||
                        Boolean(syncError) ||
                        !rejectReason.trim()
                      }
                      type="submit"
                      variant="primary"
                    >
                      {actionPending ? "Rejecting task..." : "Confirm Reject"}
                    </Button>
                  </div>
                </form>
              </dialog>
            </section>
          )}

          {currentResult.task.status === "ACCEPTED" && (
            <section className="lifecycle-controls" aria-label="Task actions">
              <p role="status">
                Task accepted. You can now record arrival and BEFORE evidence.
              </p>
              <p>
                Starting requires a stored BEFORE photo and a captured
                arrival location.
              </p>
              <Button
                disabled={actionPending || Boolean(syncError)}
                onClick={() => runAction("start")}
                type="button"
              >
                {actionPending ? "Starting..." : "Start task"}
              </Button>
            </section>
          )}

          {currentResult.task.status === "IN_PROGRESS" && (
            <section className="lifecycle-controls" aria-label="Task actions">
              <Button
                disabled={actionPending || Boolean(syncError)}
                onClick={() => runAction("pause")}
                type="button"
              >
                {actionPending ? "Pausing..." : "Pause task"}
              </Button>
            </section>
          )}

          {currentResult.task.status === "PAUSED" && (
            <section className="lifecycle-controls" aria-label="Task actions">
              <Button
                disabled={actionPending || Boolean(syncError)}
                onClick={() => runAction("resume")}
                type="button"
              >
                {actionPending ? "Resuming..." : "Resume task"}
              </Button>
            </section>
          )}

          {currentResult.task.status === "BLOCKED" && (
            <p className="task-lifecycle-status" role="status">
              This task is blocked. Work actions remain unavailable until
              Dispatch or a Supervisor resolves the blocker.
            </p>
          )}

          {currentResult.task.status === "COMPLETION_SUBMITTED" && (
            <p className="task-lifecycle-status" role="status">
              Completion has been submitted for verification. No further work
              or completion submission is available from this page.
            </p>
          )}

          <article className="task-details-card">
            <div className="task-details-card__topline">
              <span
                className={getPriorityClass(currentResult.task.priority)}
                aria-label={`Priority: ${currentResult.task.priority}`}
              >
                {currentResult.task.priority} priority
              </span>
            </div>

            <section
              className="task-details-section"
              aria-labelledby="task-description-heading"
            >
              <h2 id="task-description-heading">Description</h2>
              <p>{currentResult.task.description}</p>
            </section>

            <section
              className="task-details-section"
              aria-labelledby="task-location-heading"
            >
              <h2 id="task-location-heading">Location</h2>
              {typeof currentResult.task.location.name === "string" &&
                currentResult.task.location.name.length > 0 && (
                  <p>{currentResult.task.location.name}</p>
                )}
              <p>{currentResult.task.location.address}</p>
              {hasTaskCoordinates(currentResult.task.location) ? (
                <p className="task-details-coordinates">
                  {currentResult.task.location.latitude},{" "}
                  {currentResult.task.location.longitude}
                </p>
              ) : (
                <p className="task-details-note" role="status">
                  Assigned coordinates are unavailable or invalid.
                </p>
              )}
            </section>

          </article>

          <EvidenceSection
            key={`evidence-${currentResult.task.task_id}-${relatedRefreshNumber}`}
            onEvidenceChanged={() =>
              setPrerequisiteRevision((current) => current + 1)
            }
            task={currentResult.task}
          />

          <LocationErrorBoundary
            key={`location-boundary-${currentResult.task.task_id}-${relatedRefreshNumber}`}
          >
            <LocationSection
              actionsDisabled={actionPending || Boolean(syncError)}
              taskLocation={taskLocation}
              workerLocation={displayedWorkerLocation}
              onLocationCaptured={(location) =>
                setWorkerLocation(
                  location?.event_type === "ARRIVAL"
                    ? {
                        latitude: location.latitude,
                        longitude: location.longitude,
                        eventType: location.event_type,
                        accuracyMeters: location.accuracy_meters,
                        capturedAt: location.captured_at_device,
                        isAccepted: false,
                      }
                    : null,
                )
              }
              onLocationSubmitted={(event) => {
                if (
                  event.event_type === "ARRIVAL" &&
                  event.capture_status === "CAPTURED"
                ) {
                  setWorkerLocation({
                    latitude: event.latitude,
                    longitude: event.longitude,
                    eventType: event.event_type,
                    accuracyMeters: event.accuracy_meters,
                    capturedAt: event.captured_at_device,
                    receivedAt: event.received_at_server,
                    isAccepted: true,
                  });
                }
                if (event.event_type === "COMPLETION") {
                  setCompletionLocationEvent(event);
                }
              }}
              onRefreshTask={refreshTaskDetails}
              task={currentResult.task}
            />
          </LocationErrorBoundary>

          <BlockerSection
            actionsDisabled={actionPending || Boolean(syncError)}
            key={`blockers-${currentResult.task.task_id}-${relatedRefreshNumber}`}
            onRefreshTask={refreshTaskDetails}
            task={currentResult.task}
          />

          <CompletionSection
            actionsDisabled={actionPending || Boolean(syncError)}
            completionLocationEvent={completionLocationEvent}
            onRefreshRelated={() =>
              setRelatedRefreshNumber((current) => current + 1)
            }
            onRefreshTask={refreshTaskDetails}
            prerequisiteRevision={prerequisiteRevision}
            task={currentResult.task}
          />

        </>
      )}
    </section>
  );
}
