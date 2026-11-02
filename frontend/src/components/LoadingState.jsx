export default function LoadingState({ label = "Loading..." }) {
  return (
    <p className="loading-state" role="status" aria-live="polite">
      {label}
    </p>
  );
}
