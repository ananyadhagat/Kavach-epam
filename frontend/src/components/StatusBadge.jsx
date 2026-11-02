const STATUS_CLASS = {
  ASSIGNED: "status-badge--neutral",
  ACCEPTED: "status-badge--blue",
  IN_PROGRESS: "status-badge--green",
  PAUSED: "status-badge--amber",
  BLOCKED: "status-badge--red",
  COMPLETION_SUBMITTED: "status-badge--violet",
  REJECTED: "status-badge--neutral",
};

export default function StatusBadge({ status }) {
  const label = status?.replaceAll("_", " ") || "Unknown";
  const className = STATUS_CLASS[status] ?? "status-badge--neutral";

  return (
    <span className={`status-badge ${className}`} aria-label={`Status: ${label}`}>
      {label}
    </span>
  );
}
