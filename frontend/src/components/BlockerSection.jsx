import { useEffect, useRef, useState } from "react";
import {
  getBlockerReasonCodes,
  getTaskBlockers,
  reportTaskBlocker,
} from "../api/tasks.js";
import Button from "./Button.jsx";
import ErrorMessage from "./ErrorMessage.jsx";
import LoadingState from "./LoadingState.jsx";
import StatusBadge from "./StatusBadge.jsx";

const BLOCKABLE_STATES = new Set(["ACCEPTED", "IN_PROGRESS", "PAUSED"]);
const DESCRIPTION_MAX_LENGTH = 500;

function errorTitle(error) {
  if (error.status === 401) return "Authentication required";
  if (error.status === 403) return "Blocker access forbidden";
  if (error.status === 404) return "Task not found";
  if (error.status === 409) return "Task cannot accept another blocker";
  if (error.status === 422) return "Blocker details were not accepted";
  if (error.status === 503) return "Blocker reporting unavailable";
  return "Could not load or report blocker";
}

function formatDate(value) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function BlockerSection({
  actionsDisabled = false,
  task,
  onRefreshTask,
}) {
  const [reasonCodes, setReasonCodes] = useState([]);
  const [reasonCodesLoading, setReasonCodesLoading] = useState(true);
  const [reasonCodesError, setReasonCodesError] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(null);
  const [historyRefreshing, setHistoryRefreshing] = useState(false);
  const [retryNumber, setRetryNumber] = useState(0);
  const [reasonCode, setReasonCode] = useState("");
  const [description, setDescription] = useState("");
  const [descriptionError, setDescriptionError] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [confirmedBlocker, setConfirmedBlocker] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [syncError, setSyncError] = useState(null);
  const [isRefreshingState, setIsRefreshingState] = useState(false);
  const activeTaskIdRef = useRef(task.task_id);
  const pendingRef = useRef(false);
  const loadControllerRef = useRef(null);
  const submitControllerRef = useRef(null);
  const refreshControllerRef = useRef(null);
  const reportable = BLOCKABLE_STATES.has(task.status);
  const hasOpenBlocker = history.some((blocker) => blocker.status === "OPEN");
  const canSubmit =
    reportable &&
    !hasOpenBlocker &&
    !reasonCodesLoading &&
    !reasonCodesError &&
    reasonCodes.length > 0 &&
    !historyLoading &&
    !historyError &&
    Boolean(reasonCode) &&
    description.trim().length > 0 &&
    description.trim().length <= DESCRIPTION_MAX_LENGTH &&
    !isSubmitting &&
    !isRefreshingState &&
    !actionsDisabled &&
    !syncError;

  useEffect(() => {
    activeTaskIdRef.current = task.task_id;
    loadControllerRef.current?.abort();
    loadControllerRef.current = null;
    submitControllerRef.current?.abort();
    submitControllerRef.current = null;
    refreshControllerRef.current?.abort();
    refreshControllerRef.current = null;
    pendingRef.current = false;
    setReasonCodes([]);
    setReasonCodesLoading(false);
    setReasonCodesError(null);
    setHistory([]);
    setHistoryLoading(true);
    setHistoryError(null);
    setHistoryRefreshing(false);
    setReasonCode("");
    setDescription("");
    setDescriptionError(null);
    setSubmitError(null);
    setSuccessMessage(null);
    setConfirmedBlocker(null);
    setIsSubmitting(false);
    setSyncError(null);
    setIsRefreshingState(false);

    const controller = new AbortController();
    loadControllerRef.current = controller;
    let active = true;

    getTaskBlockers(task.task_id, { signal: controller.signal })
      .then((records) => {
        if (active) {
          setHistory(records);
          setHistoryLoading(false);
        }
      })
      .catch((error) => {
        if (active && error.name !== "AbortError") {
          setHistoryError(error);
          setHistoryLoading(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
      submitControllerRef.current?.abort();
      refreshControllerRef.current?.abort();
      if (loadControllerRef.current === controller) {
        loadControllerRef.current = null;
      }
      activeTaskIdRef.current = null;
    };
  }, [task.task_id, retryNumber]);

  useEffect(() => {
    if (!reportable) {
      setReasonCodes([]);
      setReasonCodesLoading(false);
      setReasonCodesError(null);
      setReasonCode("");
      return undefined;
    }

    const controller = new AbortController();
    let active = true;
    setReasonCodes([]);
    setReasonCodesLoading(true);
    setReasonCodesError(null);
    setReasonCode("");

    getBlockerReasonCodes({ signal: controller.signal })
      .then((codes) => {
        if (!active) return;
        setReasonCodes(codes);
        setReasonCode(codes[0] ?? "");
        setReasonCodesLoading(false);
      })
      .catch((error) => {
        if (active && error.name !== "AbortError") {
          setReasonCodesError(error);
          setReasonCodesLoading(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [task.task_id, retryNumber, reportable]);

  async function refreshBackendState() {
    refreshControllerRef.current?.abort();
    const controller = new AbortController();
    refreshControllerRef.current = controller;
    setIsRefreshingState(true);
    setHistoryRefreshing(true);

    const [historyResult, taskResult] = await Promise.allSettled([
      getTaskBlockers(task.task_id, { signal: controller.signal }),
      onRefreshTask({ signal: controller.signal }),
    ]);

    if (
      controller.signal.aborted ||
      activeTaskIdRef.current !== task.task_id
    ) {
      return false;
    }

    const failures = [];
    if (historyResult.status === "fulfilled") {
      setHistory(historyResult.value);
      setHistoryError(null);
    } else {
      failures.push(historyResult.reason);
      if (historyResult.reason.name !== "AbortError") {
        setHistoryError(historyResult.reason);
      }
    }

    if (taskResult.status === "fulfilled") {
      setSyncError(null);
    } else {
      failures.push(taskResult.reason);
      if (taskResult.reason.name !== "AbortError") {
        setSyncError(taskResult.reason);
      }
    }

    if (refreshControllerRef.current === controller) {
      refreshControllerRef.current = null;
      setIsRefreshingState(false);
      setHistoryRefreshing(false);
    }

    return failures.length === 0;
  }

  async function refreshHistory() {
    refreshControllerRef.current?.abort();
    const controller = new AbortController();
    refreshControllerRef.current = controller;
    setHistoryRefreshing(true);
    setHistoryError(null);

    try {
      const records = await getTaskBlockers(task.task_id, {
        signal: controller.signal,
      });
      if (
        !controller.signal.aborted &&
        activeTaskIdRef.current === task.task_id
      ) {
        setHistory(records);
      }
    } catch (error) {
      if (
        error.name !== "AbortError" &&
        !controller.signal.aborted &&
        activeTaskIdRef.current === task.task_id
      ) {
        setHistoryError(error);
      }
    } finally {
      if (refreshControllerRef.current === controller) {
        refreshControllerRef.current = null;
        setHistoryRefreshing(false);
      }
    }
  }

  function updateDescription(value) {
    setDescription(value);
    setDescriptionError(
      value.trim().length > DESCRIPTION_MAX_LENGTH
        ? `Description must be no more than ${DESCRIPTION_MAX_LENGTH} characters.`
        : null,
    );
    setSubmitError(null);
    setSuccessMessage(null);
  }

  async function submitReport(event) {
    event.preventDefault();
    const trimmedDescription = description.trim();
    if (
      !canSubmit ||
      pendingRef.current ||
      actionsDisabled ||
      !reasonCodes.includes(reasonCode)
    ) {
      return;
    }

    if (
      trimmedDescription.length < 1 ||
      trimmedDescription.length > DESCRIPTION_MAX_LENGTH
    ) {
      setDescriptionError(
        `Enter a description between 1 and ${DESCRIPTION_MAX_LENGTH} characters.`,
      );
      return;
    }

    pendingRef.current = true;
    const controller = new AbortController();
    submitControllerRef.current = controller;
    setIsSubmitting(true);
    setSubmitError(null);
    setSuccessMessage(null);
    setConfirmedBlocker(null);
    setSyncError(null);

    try {
      const response = await reportTaskBlocker(
        task.task_id,
        reasonCode,
        trimmedDescription,
        { signal: controller.signal },
      );
      if (
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return;
      }

      setConfirmedBlocker(response.blocker);
      setSuccessMessage(response.message);
      setDescription("");
      setDescriptionError(null);
      await refreshBackendState();
    } catch (error) {
      if (
        error.name === "AbortError" ||
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return;
      }

      setSubmitError(error);
      const refreshed = await refreshBackendState();
      if (!refreshed) {
        setSyncError((current) => current ?? error);
      }
    } finally {
      if (activeTaskIdRef.current === task.task_id) {
        pendingRef.current = false;
        setIsSubmitting(false);
      }
      if (submitControllerRef.current === controller) {
        submitControllerRef.current = null;
      }
    }
  }

  return (
    <section className="blocker-panel" aria-labelledby="blocker-heading">
      <div className="blocker-panel__heading">
        <div>
          <p className="eyebrow">Task support</p>
          <h2 id="blocker-heading">Blocker reporting</h2>
        </div>
        <Button
          disabled={historyLoading || historyRefreshing}
          onClick={refreshHistory}
          type="button"
          variant="secondary"
        >
          {historyRefreshing ? "Refreshing..." : "Refresh history"}
        </Button>
      </div>

      {reportable ? (
        <form className="blocker-form" onSubmit={submitReport}>
          <p className="blocker-guidance">
            Report an issue preventing work from continuing. The task will
            become BLOCKED; only Dispatch or a Supervisor can resolve it.
          </p>

          {hasOpenBlocker && (
            <p className="blocker-warning" role="status">
              This task already has an open blocker. It must be resolved by
              Dispatch or a Supervisor before another report can be made.
            </p>
          )}

          {historyError && (
            <p className="blocker-warning" role="status">
              Blocker history could not be confirmed, so submission is
              disabled until history is refreshed.
            </p>
          )}

          {reasonCodesLoading && (
            <LoadingState label="Loading available blocker reason codes..." />
          )}

          {reasonCodesError && (
            <div className="blocker-error">
              <ErrorMessage title={errorTitle(reasonCodesError)}>
                {reasonCodesError.message} Blocker reporting is disabled until
                reason codes can be loaded.
              </ErrorMessage>
              <Button
                onClick={() => setRetryNumber((current) => current + 1)}
                type="button"
                variant="secondary"
              >
                Retry reason codes
              </Button>
            </div>
          )}

          {!reasonCodesLoading &&
            !reasonCodesError &&
            reasonCodes.length === 0 && (
              <p className="blocker-warning" role="status">
                No blocker reason codes are configured. Reporting is disabled;
                do not substitute a different code.
              </p>
            )}

          {reasonCodes.length > 0 && (
            <div className="blocker-field">
              <label htmlFor="blocker-reason-code">Reason code</label>
              <select
                disabled={
                  hasOpenBlocker ||
                  reasonCodesLoading ||
                  Boolean(reasonCodesError) ||
                  isSubmitting ||
                  isRefreshingState ||
                  actionsDisabled ||
                  Boolean(syncError)
                }
                id="blocker-reason-code"
                onChange={(event) => {
                  setReasonCode(event.target.value);
                  setSubmitError(null);
                  setSuccessMessage(null);
                }}
                required
                value={reasonCode}
              >
                {reasonCodes.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="blocker-field">
            <label htmlFor="blocker-description">Description</label>
            <textarea
              aria-describedby="blocker-description-hint blocker-description-count"
              disabled={
                hasOpenBlocker ||
                reasonCodesLoading ||
                Boolean(reasonCodesError) ||
                reasonCodes.length === 0 ||
                isSubmitting ||
                isRefreshingState ||
                actionsDisabled ||
                Boolean(syncError)
              }
              id="blocker-description"
              maxLength={DESCRIPTION_MAX_LENGTH}
              onChange={(event) => updateDescription(event.target.value)}
              placeholder={
                reasonCode === "OTHER"
                  ? "Explain the issue that does not fit the listed reasons."
                  : "Describe the issue and how it prevents work."
              }
              required
              rows={4}
              value={description}
            />
            <span className="blocker-field__hint" id="blocker-description-hint">
              {reasonCode === "OTHER"
                ? "For OTHER, explain the issue in 1–500 characters. A description is required for every reason code; whitespace at the beginning or end is removed."
                : "Describe the issue in 1–500 characters. A description is required for every reason code; whitespace at the beginning or end is removed."}
            </span>
            <span
              className="blocker-field__count"
              id="blocker-description-count"
              aria-live="polite"
            >
              {description.length}/{DESCRIPTION_MAX_LENGTH}
            </span>
            {descriptionError && (
              <span className="blocker-inline-error" role="alert">
                {descriptionError}
              </span>
            )}
          </div>

          {!hasOpenBlocker && (
            <Button disabled={!canSubmit} type="submit">
              {isSubmitting ? "Reporting blocker..." : "Report blocker"}
            </Button>
          )}
        </form>
      ) : (
        <p className="blocker-guidance" role="status">
          Blockers can be reported only while a task is ACCEPTED, IN_PROGRESS,
          or PAUSED. This task is {task.status}.
        </p>
      )}

      {submitError && (
        <ErrorMessage title={errorTitle(submitError)}>
          {submitError.message}
        </ErrorMessage>
      )}

      {successMessage && confirmedBlocker && (
        <div className="blocker-success" role="status">
          <p>{successMessage}</p>
          <p>
            Backend confirmed blocker status:{" "}
            <strong>{confirmedBlocker.status}</strong>. The worker cannot
            resolve or unblock this task.
          </p>
        </div>
      )}

      {isRefreshingState && (
        <LoadingState label="Refreshing task and blocker history..." />
      )}

      {syncError && (
        <div className="blocker-error">
          <ErrorMessage title="Could not confirm the latest blocker state">
            {syncError.message} Refresh blocker history and task details before
            trying again.
          </ErrorMessage>
          <Button
            disabled={isRefreshingState}
            onClick={refreshBackendState}
            type="button"
            variant="secondary"
          >
            Refresh task and blocker history
          </Button>
        </div>
      )}

      <section className="blocker-history" aria-labelledby="blocker-history-heading">
        <div className="blocker-history__heading">
          <h3 id="blocker-history-heading">Blocker history</h3>
          {history.length > 0 && (
            <span>
              {history.length} {history.length === 1 ? "record" : "records"}
            </span>
          )}
        </div>

        {historyLoading && <LoadingState label="Loading blocker history..." />}

        {historyError && (
          <div className="blocker-error">
            <ErrorMessage title={errorTitle(historyError)}>
              {historyError.message}
            </ErrorMessage>
            <Button
              onClick={refreshHistory}
              type="button"
              variant="secondary"
            >
              Retry blocker history
            </Button>
          </div>
        )}

        {!historyLoading && !historyError && history.length === 0 && (
          <p className="blocker-history__empty">
            No blockers have been reported for this task.
          </p>
        )}

        {history.length > 0 && (
          <ol className="blocker-history__list">
            {history.map((blocker, index) => (
              <li
                className="blocker-history__item"
                key={`${blocker.reason_code}-${blocker.reported_at}-${index}`}
              >
                <div className="blocker-history__item-heading">
                  <strong>{blocker.reason_code}</strong>
                  <StatusBadge status={blocker.status} />
                </div>
                <p className="blocker-history__description">
                  {blocker.description}
                </p>
                <dl className="blocker-history__details">
                  <div>
                    <dt>Reported</dt>
                    <dd>
                      <time dateTime={blocker.reported_at}>
                        {formatDate(blocker.reported_at)}
                      </time>
                    </dd>
                  </div>
                  <div>
                    <dt>Task status before report</dt>
                    <dd>{blocker.previous_status}</dd>
                  </div>
                  {blocker.status === "RESOLVED" && (
                    <>
                      <div>
                        <dt>Resolved</dt>
                        <dd>
                          {blocker.resolved_at ? (
                            <time dateTime={blocker.resolved_at}>
                              {formatDate(blocker.resolved_at)}
                            </time>
                          ) : (
                            "Resolution time not available"
                          )}
                        </dd>
                      </div>
                      {blocker.resolved_by && (
                        <div>
                          <dt>Resolved by</dt>
                          <dd>{blocker.resolved_by}</dd>
                        </div>
                      )}
                      {blocker.resolution_note && (
                        <div>
                          <dt>Resolution note</dt>
                          <dd>{blocker.resolution_note}</dd>
                        </div>
                      )}
                    </>
                  )}
                  {blocker.status === "OPEN" && (
                    <div className="blocker-history__open-notice">
                      This blocker is open and has not been resolved.
                    </div>
                  )}
                </dl>
              </li>
            ))}
          </ol>
        )}
      </section>
    </section>
  );
}
