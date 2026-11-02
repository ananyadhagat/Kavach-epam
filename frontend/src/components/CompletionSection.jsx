import { useEffect, useRef, useState } from "react";
import {
  getTaskEvidence,
  submitTaskCompletion,
} from "../api/tasks.js";
import {
  getAcceptedCompletionLocationId,
  isCompletionWorkflowReady,
} from "../location/completion-location.js";
import Button from "./Button.jsx";
import ErrorMessage from "./ErrorMessage.jsx";
import LoadingState from "./LoadingState.jsx";
import StatusBadge from "./StatusBadge.jsx";

function createIdempotencyKey() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }

  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0"));
    return [
      hex.slice(0, 4).join(""),
      hex.slice(4, 6).join(""),
      hex.slice(6, 8).join(""),
      hex.slice(8, 10).join(""),
      hex.slice(10).join(""),
    ].join("-");
  }

  throw new Error("Secure random keys are unavailable in this browser.");
}

function attemptStorageKey(taskId) {
  return `field-worker-completion-attempt:${taskId}`;
}

function readStoredAttempt(taskId) {
  let serializedAttempt;
  try {
    serializedAttempt = window.sessionStorage.getItem(
      attemptStorageKey(taskId),
    );
  } catch {
    const error = new Error("Completion retry storage is unavailable.");
    error.code = "STORAGE_UNAVAILABLE";
    throw error;
  }

  if (serializedAttempt === null) return null;

  let storedAttempt;
  try {
    storedAttempt = JSON.parse(serializedAttempt);
  } catch {
    const error = new Error("Saved completion retry data is malformed.");
    error.code = "INVALID_ATTEMPT";
    throw error;
  }
  const claim = storedAttempt?.claim;
  const claimKeys = claim && Object.keys(claim);
  const validClaim =
    claim &&
    typeof claim === "object" &&
    Array.isArray(claim.evidence_ids) &&
    claim.evidence_ids.length >= 2 &&
    claim.evidence_ids.every(
      (evidenceId) =>
        typeof evidenceId === "string" && evidenceId.trim().length > 0,
    ) &&
    new Set(claim.evidence_ids).size === claim.evidence_ids.length &&
    typeof claim.completion_location_event_id === "string" &&
    claim.completion_location_event_id.trim().length > 0 &&
    (claim.notes === undefined ||
      (typeof claim.notes === "string" && claim.notes.length <= 2000)) &&
    claimKeys.every((key) =>
      ["evidence_ids", "completion_location_event_id", "notes"].includes(key),
    );

  if (
    !validClaim ||
    typeof storedAttempt.idempotencyKey !== "string" ||
    storedAttempt.idempotencyKey.trim().length === 0 ||
    storedAttempt.idempotencyKey.length > 200
  ) {
    const error = new Error("Saved completion retry data could not be validated.");
    error.code = "INVALID_ATTEMPT";
    throw error;
  }

  return {
    claim,
    idempotencyKey: storedAttempt.idempotencyKey,
    uncertain: true,
  };
}

function writeStoredAttempt(taskId, logicalAttempt) {
  window.sessionStorage.setItem(
    attemptStorageKey(taskId),
    JSON.stringify({
      claim: logicalAttempt.claim,
      idempotencyKey: logicalAttempt.idempotencyKey,
    }),
  );
}

function clearStoredAttempt(taskId) {
  window.sessionStorage.removeItem(attemptStorageKey(taskId));
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function errorTitle(error) {
  if (error.status === 401) return "Authentication required";
  if (error.status === 403) return "Completion submission forbidden";
  if (error.status === 404) return "Task or evidence not found";
  if (error.status === 409) return "Task state conflict";
  if (error.status === 422) return "Completion prerequisites were rejected";
  if (error.status === 503) return "Completion service unavailable";
  return "Could not submit completion";
}

function isUncertainOutcome(error) {
  return (
    error.status === null ||
    error.status === 200 ||
    error.status === 409 ||
    error.status >= 500
  );
}

export default function CompletionSection({
  actionsDisabled = false,
  completionLocationEvent,
  onRefreshRelated,
  onRefreshTask,
  prerequisiteRevision,
  task,
}) {
  const [evidence, setEvidence] = useState(null);
  const [readinessTask, setReadinessTask] = useState(null);
  const [readinessError, setReadinessError] = useState(null);
  const [attemptStorageError, setAttemptStorageError] = useState(null);
  const [storageMode, setStorageMode] = useState("persistent");
  const [storageRecoveryTask, setStorageRecoveryTask] = useState(null);
  const [isRecoveringStorage, setIsRecoveringStorage] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(true);
  const [notes, setNotes] = useState("");
  const [attempt, setAttempt] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [confirmedSubmission, setConfirmedSubmission] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const activeTaskIdRef = useRef(task.task_id);
  const requestControllerRef = useRef(null);
  const refreshControllerRef = useRef(null);
  const pendingRef = useRef(false);

  useEffect(() => {
    activeTaskIdRef.current = task.task_id;
    setEvidence(null);
    setReadinessTask(null);
    setReadinessError(null);
    setAttemptStorageError(null);
    setStorageMode("persistent");
    setStorageRecoveryTask(null);
    setIsRecoveringStorage(false);
    setIsRefreshing(true);
    setNotes("");
    try {
      const savedAttempt = readStoredAttempt(task.task_id);
      setAttempt(savedAttempt);
      if (savedAttempt) {
        setSubmitError({
          error: new Error(
            "A previous completion request may not have received a response.",
          ),
          uncertain: true,
        });
      } else {
        setSubmitError(null);
      }
    } catch (error) {
      setAttempt(null);
      setAttemptStorageError({
        code: error.code,
        message:
          error.code === "STORAGE_UNAVAILABLE"
            ? "This tab cannot access saved completion retry data."
            : "Saved completion retry data is malformed or cannot be trusted.",
      });
      setSubmitError(null);
    }
    setConfirmedSubmission(null);
    setIsSubmitting(false);
    pendingRef.current = false;

    return () => {
      activeTaskIdRef.current = null;
      requestControllerRef.current?.abort();
      refreshControllerRef.current?.abort();
    };
  }, [task.task_id]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    refreshControllerRef.current?.abort();
    refreshControllerRef.current = controller;
    setIsRefreshing(true);
    setReadinessError(null);

    Promise.all([
      onRefreshTask({ signal: controller.signal }),
      getTaskEvidence(task.task_id, { signal: controller.signal }),
    ])
      .then(([freshTask, records]) => {
        if (!active || activeTaskIdRef.current !== task.task_id) return;
        setReadinessTask(freshTask);
        setEvidence(records);
        setReadinessError(null);
      })
      .catch((error) => {
        if (!active || error.name === "AbortError") return;
        setReadinessError(error);
        setReadinessTask(null);
        setEvidence(null);
      })
      .finally(() => {
        if (active && refreshControllerRef.current === controller) {
          refreshControllerRef.current = null;
          setIsRefreshing(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
      if (refreshControllerRef.current === controller) {
        refreshControllerRef.current = null;
      }
    };
  }, [
    task.task_id,
    task.status,
    prerequisiteRevision,
    onRefreshTask,
  ]);

  useEffect(() => {
    if (readinessTask?.task_id === task.task_id) {
      setReadinessTask(task);
    }
  }, [task, readinessTask?.task_id]);

  async function refreshReadiness() {
    refreshControllerRef.current?.abort();
    const controller = new AbortController();
    refreshControllerRef.current = controller;
    setIsRefreshing(true);
    setReadinessError(null);

    try {
      const [freshTask, records] = await Promise.all([
        onRefreshTask({ signal: controller.signal }),
        getTaskEvidence(task.task_id, { signal: controller.signal }),
      ]);

      if (
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return false;
      }

      setReadinessTask(freshTask);
      setEvidence(records);
      setReadinessError(null);
      return freshTask;
    } catch (error) {
      if (error.name !== "AbortError" && !controller.signal.aborted) {
        setReadinessTask(null);
        setEvidence(null);
        setReadinessError(error);
      }
      return false;
    } finally {
      if (refreshControllerRef.current === controller) {
        refreshControllerRef.current = null;
        setIsRefreshing(false);
      }
    }
  }

  const beforeEvidence = evidence?.find(
    (item) =>
      item.evidence_type === "BEFORE" &&
      item.status === "STORED" &&
      item.worker_id === readinessTask?.assigned_worker_id,
  );
  const afterEvidence = evidence?.find(
    (item) =>
      item.evidence_type === "AFTER" &&
      item.status === "STORED" &&
      item.worker_id === readinessTask?.assigned_worker_id,
  );
  const arrivalReady = Boolean(
    readinessTask?.arrival_location_accepted === true &&
      readinessTask?.arrival_location_event_id,
  );
  const completionEventId = readinessTask?.completion_location_event_id;
  const completionLocationReady = Boolean(
    readinessTask &&
      getAcceptedCompletionLocationId(
        readinessTask,
        completionLocationEvent,
      ),
  );
  const taskReady = readinessTask?.status === "IN_PROGRESS";
  const taskStatus = readinessTask?.status;
  const accepted =
    taskStatus !== undefined &&
    !["ASSIGNED", "REJECTED"].includes(taskStatus);
  const workStarted = ["IN_PROGRESS", "PAUSED", "COMPLETION_SUBMITTED"].includes(
    taskStatus,
  );
  const completionSubmitted =
    taskStatus === "COMPLETION_SUBMITTED" ||
    confirmedSubmission?.submission?.status === "COMPLETION_SUBMITTED";
  const ready = isCompletionWorkflowReady({
    isRefreshing,
    readinessError,
    attemptStorageError,
    actionsDisabled,
    task: readinessTask,
    evidence,
    submittedCompletionEvent: completionLocationEvent,
  });
  const canRetryUncertainAttempt =
    Boolean(attempt?.uncertain) &&
    !isRefreshing &&
    !readinessError &&
    readinessTask &&
    readinessTask.status === "IN_PROGRESS" &&
    !isSubmitting &&
    !actionsDisabled;
  const progressStages = [
    {
      label: "Task accepted",
      complete: accepted,
      action: "Accept the assigned task to continue.",
    },
    {
      label: "Arrival location saved",
      complete: arrivalReady,
      action: "Capture and confirm your arrival location.",
    },
    {
      label: "BEFORE photo uploaded",
      complete: Boolean(beforeEvidence),
      action: "Upload one BEFORE photo using the photo section.",
    },
    {
      label: "Work started",
      complete: workStarted,
      action:
        taskStatus === "BLOCKED"
          ? "This task is blocked. Ask Dispatch or a Supervisor to resolve it."
          : "Save the arrival location and BEFORE photo, then start the task.",
    },
    {
      label: "AFTER photo uploaded",
      complete: Boolean(afterEvidence),
      action: "After work is underway, upload one AFTER photo.",
    },
    {
      label: "Completion location saved",
      complete: completionLocationReady,
      action: "Capture and confirm a separate completion location.",
    },
    {
      label: "Completion submitted",
      complete: completionSubmitted,
      action: "Submit the completion report when all earlier steps are complete.",
    },
  ];

  async function runSubmission(logicalAttempt) {
    if (pendingRef.current || actionsDisabled) return;
    pendingRef.current = true;
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setIsSubmitting(true);
    setSubmitError(null);
    setConfirmedSubmission(null);

    try {
      const response = await submitTaskCompletion(
        task.task_id,
        logicalAttempt.claim,
        logicalAttempt.idempotencyKey,
        { signal: controller.signal },
      );
      if (
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return;
      }

      setConfirmedSubmission(response);
      setAttempt(null);
      setNotes("");
      if (storageMode === "persistent") {
        try {
          clearStoredAttempt(task.task_id);
          setAttemptStorageError(null);
        } catch {
          setAttemptStorageError({
            code: "STORAGE_UNAVAILABLE",
            message:
              "Completion was submitted, but saved retry data could not be cleared.",
          });
        }
      }
      onRefreshRelated();
      await refreshReadiness();
    } catch (error) {
      if (
        error.name === "AbortError" ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return;
      }

      const uncertain = isUncertainOutcome(error);
      setSubmitError({ error, uncertain });
      setAttempt(
        uncertain ? { ...logicalAttempt, uncertain: true } : null,
      );
      if (!uncertain && storageMode === "persistent") {
        try {
          clearStoredAttempt(task.task_id);
          setAttemptStorageError(null);
        } catch {
          setAttemptStorageError({
            code: "STORAGE_UNAVAILABLE",
            message:
              "The server rejected this attempt, but saved retry data could not be cleared.",
          });
        }
      }
      onRefreshRelated();
      await refreshReadiness();
    } finally {
      if (activeTaskIdRef.current === task.task_id) {
        pendingRef.current = false;
        setIsSubmitting(false);
      }
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
    }
  }

  function startSubmission(event) {
    event.preventDefault();
    if (
      !ready ||
      attempt ||
      pendingRef.current ||
      notes.length > 2000 ||
      !beforeEvidence ||
      !afterEvidence ||
      !completionEventId
    ) {
      return;
    }

    try {
      const claim = {
        evidence_ids: [beforeEvidence.evidence_id, afterEvidence.evidence_id],
        completion_location_event_id: completionEventId,
      };
      const trimmedNotes = notes.trim();
      if (trimmedNotes) claim.notes = trimmedNotes;
      const logicalAttempt = {
        claim,
        idempotencyKey: createIdempotencyKey(),
        uncertain: false,
      };
      if (storageMode === "persistent") {
        try {
          writeStoredAttempt(task.task_id, logicalAttempt);
        } catch {
          setAttemptStorageError({
            code: "STORAGE_UNAVAILABLE",
            message:
              "This tab could not save retry information, so no completion request was sent.",
          });
          setStorageRecoveryTask(null);
          setSubmitError(null);
          return;
        }
      }
      setAttemptStorageError(null);
      setAttempt(logicalAttempt);
      runSubmission(logicalAttempt);
    } catch (error) {
      setSubmitError({ error, uncertain: false });
    }
  }

  function reviseDefinitiveFailure() {
    if (submitError?.uncertain || isSubmitting) return;
    if (storageMode === "persistent") {
      try {
        clearStoredAttempt(task.task_id);
        setAttemptStorageError(null);
      } catch {
        setAttemptStorageError({
          code: "STORAGE_UNAVAILABLE",
          message:
            "The saved retry data could not be cleared. Refresh task state before recovery.",
        });
        return;
      }
    }
    setAttempt(null);
    setSubmitError(null);
    setConfirmedSubmission(null);
  }

  async function recoverRetryStorage() {
    setIsRecoveringStorage(true);
    setStorageRecoveryTask(null);
    try {
      const refreshedTask = await refreshReadiness();
      if (!refreshedTask || activeTaskIdRef.current !== task.task_id) {
        return;
      }

      setStorageRecoveryTask(refreshedTask);
    } finally {
      setIsRecoveringStorage(false);
    }
  }

  function continueAfterStorageRecovery() {
    if (
      !storageRecoveryTask ||
      storageRecoveryTask.status === "COMPLETION_SUBMITTED" ||
      isRefreshing ||
      readinessError
    ) {
      return;
    }

    let canUsePersistentStorage = false;
    if (attemptStorageError.code !== "STORAGE_UNAVAILABLE") {
      try {
        clearStoredAttempt(task.task_id);
        canUsePersistentStorage = true;
      } catch {
        canUsePersistentStorage = false;
      }
    }

    setStorageMode(canUsePersistentStorage ? "persistent" : "memory");
    setAttemptStorageError(null);
    setSubmitError(null);
    setAttempt(null);
  }

  return (
    <section
      aria-labelledby="completion-heading"
      className="completion-panel"
    >
      <p className="eyebrow">Submit completed work</p>
      <h2 id="completion-heading">Completion submission</h2>
      <p>
        Submit the task for independent verification after its evidence and
        location prerequisites are recorded. Submission does not mean the task
        is verified or closed.
      </p>

      {isRefreshing && (
        <LoadingState label="Refreshing completion prerequisites..." />
      )}

      {readinessError && (
        <div className="completion-panel__error">
          <ErrorMessage title="Could not verify completion prerequisites">
            {readinessError.message} Submission remains disabled until task and
            evidence data can be refreshed.
          </ErrorMessage>
          <Button
            disabled={isRefreshing}
            onClick={refreshReadiness}
            type="button"
            variant="secondary"
          >
            Refresh prerequisites
          </Button>
        </div>
      )}

      {attemptStorageError && (
        <div className="completion-panel__error">
          <ErrorMessage title="Could not safely recover the completion attempt">
            {attemptStorageError.message} Refresh task state before choosing
            whether to continue. No new completion request will be sent
            automatically.
          </ErrorMessage>
          <Button
            disabled={isRecoveringStorage || isRefreshing}
            onClick={recoverRetryStorage}
            type="button"
            variant="secondary"
          >
            {isRecoveringStorage
              ? "Refreshing task state..."
              : "Refresh task state for recovery"}
          </Button>
          {storageRecoveryTask?.status === "COMPLETION_SUBMITTED" && (
            <p className="completion-panel__success" role="status">
              Backend task status:{" "}
              <StatusBadge status={storageRecoveryTask.status} />. Completion
              is already submitted; no duplicate submission will be offered.
            </p>
          )}
          {storageRecoveryTask &&
            storageRecoveryTask.status !== "COMPLETION_SUBMITTED" && (
              <>
                <p className="completion-panel__limitation">
                  The backend currently reports{" "}
                  <strong>{storageRecoveryTask.status}</strong>. The saved
                  retry key and request could not be recovered. Continuing
                  discards the untrusted local value; if tab storage is
                  unavailable, retries can be retained only while this page
                  remains open.
                </p>
                <Button
                  disabled={isRefreshing || isRecoveringStorage}
                  onClick={continueAfterStorageRecovery}
                  type="button"
                >
                  Continue after confirming task state
                </Button>
              </>
            )}
        </div>
      )}

      {storageMode === "memory" && !attemptStorageError && (
        <p className="completion-panel__limitation" role="status">
          Saved retry storage is unavailable. Any new attempt will keep its
          original key and request only in this page's memory for retry.
        </p>
      )}

      {!attemptStorageError &&
        readinessTask?.status === "COMPLETION_SUBMITTED" &&
        !confirmedSubmission && (
          <div className="completion-panel__success" role="status">
            <h3>COMPLETED – SUBMITTED FOR VERIFICATION</h3>
            <p>
              Task {task.task_id} is already submitted. The existing task
              response confirms its status but does not include the original
              submission time. No duplicate submission is available.
            </p>
          </div>
        )}

      <ol className="completion-readiness" aria-label="Task progress">
        {progressStages.map((stage, index) => (
          <li
            className={
              stage.complete
                ? "completion-readiness__stage is-complete"
                : "completion-readiness__stage"
            }
            key={stage.label}
          >
            <span className="completion-readiness__number">{index + 1}</span>
            <div className="completion-readiness__details">
              <span>{stage.label}</span>
              {!stage.complete && !readinessError && !completionSubmitted && (
                <small>{stage.action}</small>
              )}
            </div>
            <span className="completion-readiness__status">
              {isRefreshing
                ? "Checking"
                : readinessError
                  ? "Not checked"
                : stage.complete
                  ? "Completed"
                  : "Pending"}
            </span>
          </li>
        ))}
      </ol>

      {!isRefreshing && !readinessError && !taskReady && readinessTask && (
        <p className="completion-panel__limitation">
          {readinessTask.status === "PAUSED"
            ? "Resume the paused task before submitting completion."
            : readinessTask.status === "BLOCKED"
              ? "Ask Dispatch or a Supervisor to resolve the blocker before continuing."
              : readinessTask.status === "ASSIGNED"
                ? "Accept this task before recording work."
                : readinessTask.status === "REJECTED"
                  ? "This task was rejected and cannot be completed in this workflow."
                  : `The task must be IN_PROGRESS before completion can be submitted. Current status: ${readinessTask.status}.`}
        </p>
      )}

      {!completionLocationReady && completionEventId && (
        <p className="completion-panel__limitation">
          The task references a completion-location event, but the API has no
          event-history read endpoint. This page can verify capture status only
          after a successful completion-location response in this session.
          Capture and submit the completion location again if needed.
        </p>
      )}

      {!completionLocationReady && !completionEventId && (
        <p className="completion-panel__limitation">
          Submit a captured completion location in the Location capture section
          before submitting completion.
        </p>
      )}

      {confirmedSubmission && (
        <div className="completion-panel__success" role="status">
          <h3>COMPLETED – SUBMITTED FOR VERIFICATION</h3>
          <p>{confirmedSubmission.message}</p>
          <p>Task ID: {confirmedSubmission.submission.task_id}</p>
          <p>
            Submission status:{" "}
            <StatusBadge status={confirmedSubmission.submission.status} />.
            The task has not been verified or closed.
          </p>
          {!isRefreshing && !readinessError && readinessTask ? (
            <p>
              Current task status: <StatusBadge status={readinessTask.status} />
            </p>
          ) : (
            <p>
              Refresh task details to confirm the current task status.
            </p>
          )}
          <p>
            Submitted at{" "}
            <time dateTime={confirmedSubmission.submission.submitted_at}>
              {formatDate(confirmedSubmission.submission.submitted_at)}
            </time>
          </p>
        </div>
      )}

      {submitError && (
        <ErrorMessage title={errorTitle(submitError.error)}>
          {submitError.error.message}
          {submitError.uncertain
            ? " The outcome may be uncertain. Refresh backend state, then retry only this same submission with its original idempotency key."
            : " The server rejected this attempt. Correct any issue and start a new submission attempt."}
        </ErrorMessage>
      )}

      {attempt?.uncertain &&
        readinessTask?.status === "COMPLETION_SUBMITTED" && (
          <p className="completion-panel__success" role="status">
          Task {task.task_id} is COMPLETED – SUBMITTED FOR VERIFICATION.
          Backend status: <StatusBadge status={readinessTask.status} />.
          Retrying or submitting again is disabled.
          </p>
        )}

      {attempt?.uncertain &&
        readinessTask?.status !== "COMPLETION_SUBMITTED" && (
          <div className="completion-panel__retry">
            <p>
              The original request is retained. Retrying sends the identical
              request with the same Idempotency-Key.
            </p>
            <Button
              disabled={!canRetryUncertainAttempt}
              onClick={() => runSubmission(attempt)}
              type="button"
            >
              {isSubmitting ? "Retrying..." : "Retry same submission"}
            </Button>
          </div>
        )}

      {submitError && !submitError.uncertain && (
        <Button
          disabled={isSubmitting}
          onClick={reviseDefinitiveFailure}
          type="button"
          variant="secondary"
        >
          Correct and start a new attempt
        </Button>
      )}

      {!attempt?.uncertain &&
        !confirmedSubmission &&
        readinessTask?.status !== "COMPLETION_SUBMITTED" && (
          <form className="completion-form" onSubmit={startSubmission}>
            <label htmlFor={`completion-notes-${task.task_id}`}>
              Optional completion notes
            </label>
            <textarea
              disabled={!ready || Boolean(attempt) || isSubmitting}
              id={`completion-notes-${task.task_id}`}
              maxLength={2000}
              onChange={(event) => setNotes(event.target.value)}
              rows={4}
              value={notes}
            />
            <p className="completion-form__count">{notes.length}/2000</p>
            {attempt && !attempt.uncertain && (
              <Button
                disabled={isSubmitting}
                onClick={reviseDefinitiveFailure}
                type="button"
                variant="secondary"
              >
                Correct submission details
              </Button>
            )}
            <Button
              disabled={!ready || Boolean(attempt) || isSubmitting}
              type="submit"
            >
              {isSubmitting ? "Submitting completion..." : "Submit completion"}
            </Button>
          </form>
        )}
    </section>
  );
}
