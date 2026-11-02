import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <section className="page-section not-found" aria-labelledby="not-found-heading">
      <p className="eyebrow">Page not found</p>
      <h1 id="not-found-heading">We could not find that page</h1>
      <p className="page-intro">
        Check the address or return to your task workspace.
      </p>
      <Link className="button button--primary" to="/tasks">
        Go to my tasks
      </Link>
    </section>
  );
}
