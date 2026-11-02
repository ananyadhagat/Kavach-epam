import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DEVELOPMENT_TOKEN_CHANGE_EVENT } from "../auth/session.js";
import { getAssignedTasks } from "../api/tasks.js";
import Button from "../components/Button.jsx";
import ErrorMessage from "../components/ErrorMessage.jsx";
import LoadingState from "../components/LoadingState.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

function getErrorTitle(error) {
  if (error.status === 401) {
    return "Authentication required";
  }

  if (error.status === 503) {
    return "Task service unavailable";
  }

  return "Could not load tasks";
}

function getPriorityClass(priority) {
  return `priority priority--${priority?.toLowerCase() ?? "unknown"}`;
}

export default function TaskListPage() {
  const [tasks, setTasks] = useState(null);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [requestNumber, setRequestNumber] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    setError(null);
    getAssignedTasks({ signal: controller.signal })
      .then((assignedTasks) => {
        if (active) {
          setTasks(assignedTasks);
          setIsRefreshing(false);
        }
      })
      .catch((requestError) => {
        if (active && requestError.name !== "AbortError") {
          setError(requestError);
          setIsRefreshing(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [requestNumber]);

  useEffect(() => {
    function handleDevelopmentTokenChange() {
      refreshTasks();
    }

    window.addEventListener(
      DEVELOPMENT_TOKEN_CHANGE_EVENT,
      handleDevelopmentTokenChange,
    );
    return () =>
      window.removeEventListener(
        DEVELOPMENT_TOKEN_CHANGE_EVENT,
        handleDevelopmentTokenChange,
      );
  }, []);

  function refreshTasks() {
    setIsRefreshing(true);
    setRequestNumber((current) => current + 1);
  }

  const isLoading = tasks === null && error === null;

  return (
    <section className="page-section" aria-labelledby="tasks-heading">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Field operations</p>
          <h1 id="tasks-heading">My tasks</h1>
          <p className="page-intro">
            Tasks assigned to the authenticated worker.
          </p>
        </div>
        <Button
          aria-label="Refresh task list"
          disabled={isLoading || isRefreshing}
          onClick={refreshTasks}
          type="button"
          variant="secondary"
        >
          {isRefreshing ? "Refreshing..." : "Refresh"}
        </Button>
      </div>

      {isLoading && <LoadingState label="Loading your assigned tasks..." />}

      {error && (
        <div className="task-list-error">
          <ErrorMessage title={getErrorTitle(error)}>
            {error.message}
          </ErrorMessage>
          <Button onClick={refreshTasks} type="button">
            Try again
          </Button>
        </div>
      )}

      {!isLoading && !error && tasks?.length === 0 && (
        <div className="message-panel message-panel--empty">
          <span className="empty-icon" aria-hidden="true">
            ✓
          </span>
          <h2>No assigned tasks</h2>
          <p>
            There are no tasks assigned to this worker right now. Refresh to
            check again.
          </p>
        </div>
      )}

      {!error && tasks?.length > 0 && (
        <ul className="task-list" aria-label="Assigned tasks">
          {tasks.map((task) => (
            <li className="task-card" key={task.task_id}>
              <Link
                className="task-card__link"
                to={`/tasks/${encodeURIComponent(task.task_id)}`}
                aria-label={`Open task ${task.task_id}: ${task.title}`}
              >
                <div className="task-card__topline">
                  <span className="task-card__id">{task.task_id}</span>
                  <StatusBadge status={task.status} />
                </div>
                <div className="task-card__heading">
                  <div>
                    <h2>{task.title}</h2>
                    <p className="task-card__description">{task.description}</p>
                  </div>
                  <span
                    className={getPriorityClass(task.priority)}
                    aria-label={`Priority: ${task.priority}`}
                  >
                    {task.priority} priority
                  </span>
                </div>
                <div className="task-card__meta">
                  <span className="task-card__location">
                    <span aria-hidden="true">⌖</span>
                    {task.location?.address ?? "Location unavailable"}
                  </span>
                </div>
                <span className="task-card__open" aria-hidden="true">
                  View task <span>→</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
